#!/usr/bin/env python3
"""watch-displays — keep the panel layout matching the keyboard dock state.

Policy: **keyboard docked -> top panel only; undocked -> both panels.**
External monitors are never touched; whatever is enabled stays enabled, in
place.

This daemon *converges* rather than reacting to edges. The bash loop it
replaces only ever acted when the KEYBOARD changed, remembering the last
transition it had applied — so any reconfiguration behind its back left the
layout wrong until the keyboard was physically re-docked. That is the
long-standing "docked, but the bottom screen is still on under the keyboard
after resuming from sleep" bug: waking up makes Mutter re-read
~/.config/monitors.xml (which lists both panels), zenduo's own apply used the
deliberately non-persistent "temporary" method, and the keyboard never moved,
so nothing ever corrected it.

So every wake-up re-derives the layout the machine SHOULD have and compares it
to the layout it HAS, which covers all of these at once:

  * resume from suspend (Mutter restores monitors.xml)
  * lid close/open, session lock/unlock, VT switch
  * docking or undocking *while suspended*
  * external monitor hotplug/unplug (Mutter reconfigures everything)
  * gnome-shell restart, or a layout applied from GNOME Settings
  * the daemon starting into an already-wrong layout

Wake-ups come from three sources:

  1. a 1 Hz sysfs poll of the keyboard with a 2-sample debounce — deliberately
     NOT udev, which storms on this pogo-pin device forest (PLAN.md V14);
  2. Mutter's MonitorsChanged signal, so a layout change is corrected in the
     same breath instead of up to a second later;
  3. logind's PrepareForSleep, so resume re-checks even when nothing else
     moved. USB re-enumeration is not instant, so resume waits for the layout
     and the dock state to settle before acting.

A manual `duo top/bottom/both/toggle/only` (including the second-screen Fn key,
which runs `duo toggle`) records an override; while it matches the current dock
state the policy is not enforced, so a deliberate choice sticks. Docking or
undocking retires it. `duo apply-displays` drops it and converges once.

Usage: watch_displays.py [--once]
Exit codes: 0 ok · 1 Mutter/D-Bus failure (--once only) · 2 refused by R10.
"""

import os
import signal
import subprocess
import sys
import syslog
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dock  # noqa: E402  (same directory)
import displayctl  # noqa: E402  (also imports gi; exits 1 if python3-gi is missing)

from gi.repository import Gio, GLib  # noqa: E402  (safe: displayctl imported it)

POLL_SECONDS = 1
DEBOUNCE_SAMPLES = 2      # 2 s of agreement before a dock/undock counts
COALESCE_MS = 300         # Mutter emits MonitorsChanged several times per change
RESUME_SETTLE_SECONDS = 3  # let USB re-enumerate and Mutter finish restoring
RETRY_SECONDS = 5

# If we ever end up in a tug-of-war with something else that re-applies a
# layout, stop pulling: log it and stand down instead of burning the CPU and
# flashing the panels.
STORM_APPLIES = 5
STORM_WINDOW_SECONDS = 20
STORM_BACKOFF_SECONDS = 60

INTERNAL = (displayctl.TOP, displayctl.BOTTOM)

DUO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "bin", "duo"))


def log(msg):
    print(f"watch-displays: {msg}", flush=True)
    try:
        syslog.syslog(msg)  # so `duo log` (journalctl -t zenduo) shows it too
    except OSError:
        pass


class Watcher:
    def __init__(self):
        self.docked = None      # debounced truth; None until the first samples
        self._raw = None        # last raw sample
        self._streak = 0        # consecutive identical raw samples
        self._proxy = None
        self._timer = 0
        self._quiet_until = 0.0
        self._applies = []      # monotonic timestamps, for storm detection
        self._announced_override = None
        self._children = []     # backgrounded sync-backlight runs, reaped by the poll
        self.loop = GLib.MainLoop()

    # ── plumbing ─────────────────────────────────────────────────────────────

    def proxy(self):
        if self._proxy is None:
            self._proxy = displayctl.proxy()
        return self._proxy

    def schedule(self, delay_ms=COALESCE_MS):
        """Queue a converge, replacing any already-queued one."""
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay_ms, self._on_timer)

    def _on_timer(self):
        self._timer = 0
        self.converge()
        return GLib.SOURCE_REMOVE

    def quit(self, *_):
        log("stopping")
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    # ── wake-up sources ──────────────────────────────────────────────────────

    def sync_bottom_backlight(self):
        """Match the bottom panel's brightness to the top panel's.

        The bottom panel comes back at whatever level it was last left at —
        typically full brightness against a dimmed top panel, which is jarring
        the moment you undock. Strictly best effort and never blocking: the
        sync needs the root helper (system/50-duo-sudoers.sh), and a machine
        without it must still get the layout change.
        """
        try:
            self._children.append(subprocess.Popen(
                [DUO, "sync-backlight"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True))
            log("bottom panel enabled — syncing its backlight to the top panel")
        except OSError as e:
            log(f"could not start sync-backlight: {e}")

    def poll_keyboard(self):
        self._children = [c for c in self._children if c.poll() is None]
        raw = dock.keyboard_docked()
        if raw == self._raw:
            self._streak += 1
        else:
            self._raw, self._streak = raw, 1
        if self._streak < DEBOUNCE_SAMPLES or raw == self.docked:
            return GLib.SOURCE_CONTINUE
        first = self.docked is None
        self.docked = raw
        # A physical dock/undock retires any manual override: the user's last
        # explicit choice was made for the other state.
        if not first and dock.clear_override():
            log("dock state changed — manual display override cleared")
        log(f"keyboard {'docked' if raw else 'undocked'}")
        self.schedule(0)
        return GLib.SOURCE_CONTINUE

    def on_monitors_changed(self, _proxy, _sender, signal_name, _params):
        if signal_name == "MonitorsChanged":
            self.schedule()

    def on_prepare_for_sleep(self, _conn, _sender, _path, _iface, _sig, params):
        (going_to_sleep,) = params.unpack()
        if going_to_sleep:
            log("suspending")
            return
        # Resume: the keyboard may re-enumerate a beat late, and Mutter is busy
        # restoring monitors.xml. Re-debounce the dock state from scratch and
        # converge once the dust settles, rather than acting on a half-probed
        # machine and flapping the panels.
        log("resumed — re-checking dock state and panel layout")
        self._raw, self._streak = None, 0
        self._quiet_until = time.monotonic() + RESUME_SETTLE_SECONDS
        self.schedule(RESUME_SETTLE_SECONDS * 1000 + 100)

    # ── the actual work ──────────────────────────────────────────────────────

    def desired_internal(self, monitors):
        want = [displayctl.TOP] if self.docked else list(INTERNAL)
        # A panel Mutter does not report cannot be asked for; the second panel
        # legitimately disappears on some kernels (PLAN.md V9).
        return [c for c in want if c in monitors]

    def storming(self):
        now = time.monotonic()
        self._applies = [t for t in self._applies if now - t < STORM_WINDOW_SECONDS]
        if len(self._applies) < STORM_APPLIES:
            return False
        log(f"{len(self._applies)} applies in {STORM_WINDOW_SECONDS}s — something else "
            f"keeps re-applying a layout; standing down for {STORM_BACKOFF_SECONDS}s "
            f"(check GNOME Settings > Displays)")
        self._quiet_until = now + STORM_BACKOFF_SECONDS
        self._applies = []
        self.schedule(STORM_BACKOFF_SECONDS * 1000)
        return True

    def converge(self):
        """Make the enabled panel set match the dock policy. Idempotent."""
        if self.docked is None:
            return 0  # dock state not established yet; the poll will call back
        now = time.monotonic()
        if now < self._quiet_until:
            self.schedule(int((self._quiet_until - now) * 1000) + 50)
            return 0

        override = dock.read_override()
        if override is not None and bool(override.get("docked")) == self.docked:
            if self._announced_override != override:
                self._announced_override = override
                want = ", ".join(override.get("want", [])) or "?"
                log(f"manual override active ({want}) — dock policy paused until the "
                    f"keyboard is docked or undocked, or `duo apply-displays` runs")
            return 0
        self._announced_override = None

        try:
            p = self.proxy()
            serial, monitors_raw, logical_raw, properties = displayctl.get_state(p)
        except displayctl.DisplayCtlError as e:
            log(f"{e} — retrying in {RETRY_SECONDS}s")
            self._proxy = None  # a restarted gnome-shell needs a fresh proxy
            self.schedule(RETRY_SECONDS * 1000)
            return e.code

        monitors = displayctl.parse_monitors(monitors_raw)
        enabled = displayctl.enabled_connectors(logical_raw)
        want_internal = self.desired_internal(monitors)
        if not want_internal:
            log("neither internal panel is present — leaving the layout alone (R10)")
            return 2
        have_internal = [c for c in INTERNAL if c in enabled]
        if have_internal == want_internal:
            return 0  # already right: no ApplyMonitorsConfig, no flicker

        if self.storming():
            return 0
        # Externals keep their own positions; build_config re-places them only
        # if the new internal stack would collide with where they already are.
        want = want_internal + [c for c in enabled if c not in INTERNAL]
        try:
            logicals = displayctl.build_config(monitors, logical_raw, properties, want)
            displayctl.apply_config(p, serial, logicals)
        except displayctl.DisplayCtlError as e:
            log(f"{e} — retrying in {RETRY_SECONDS}s")
            self.schedule(RETRY_SECONDS * 1000)
            return e.code
        self._applies.append(time.monotonic())
        log(f"{'docked' if self.docked else 'undocked'}: was [{', '.join(have_internal) or 'none'}]"
            f" -> enabled {', '.join(want)}")
        if displayctl.BOTTOM in want_internal and displayctl.BOTTOM not in have_internal:
            self.sync_bottom_backlight()
        return 0

    # ── entry points ─────────────────────────────────────────────────────────

    def run_once(self):
        """Converge a single time, ignoring debounce and any manual override."""
        self.docked = dock.keyboard_docked()
        if dock.clear_override():
            log("manual display override cleared")
        return self.converge()

    def run(self):
        log(f"started (poll {POLL_SECONDS} Hz + MonitorsChanged + resume; "
            f"debounce {DEBOUNCE_SAMPLES} samples)")
        # ZENDUO_MANAGED marks our own applies so displayctl does not mistake
        # them for a deliberate user choice and pause the policy on us.
        os.environ["ZENDUO_MANAGED"] = "1"

        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.quit)

        try:
            self.proxy().connect("g-signal", self.on_monitors_changed)
        except displayctl.DisplayCtlError as e:
            # Not fatal: the 1 Hz poll still works, and converge() retries the
            # proxy. Losing only the signal costs latency, not correctness.
            log(f"{e} — continuing on the poll alone")

        try:
            Gio.bus_get_sync(Gio.BusType.SYSTEM, None).signal_subscribe(
                "org.freedesktop.login1", "org.freedesktop.login1.Manager",
                "PrepareForSleep", "/org/freedesktop/login1", None,
                Gio.DBusSignalFlags.NONE, self.on_prepare_for_sleep)
        except GLib.Error as e:
            log(f"cannot watch logind for resume events: {e.message} — "
                f"resume is still covered by the poll and MonitorsChanged")

        GLib.timeout_add_seconds(POLL_SECONDS, self.poll_keyboard)
        self.poll_keyboard()  # establish the dock state now, don't wait a second
        self.loop.run()
        return 0


def main(argv):
    once = "--once" in argv
    extra = [a for a in argv if a != "--once"]
    if extra:
        print(__doc__, file=sys.stderr)
        return 64
    syslog.openlog("zenduo")
    watcher = Watcher()
    return watcher.run_once() if once else watcher.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
