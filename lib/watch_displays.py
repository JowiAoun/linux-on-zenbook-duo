#!/usr/bin/env python3
"""watch-displays — keep the bottom panel in step with the keyboard.

Policy, and deliberately no more than this:

  * **while docked, the bottom panel is off** — the keyboard is lying on it, so
    nothing shown there can be seen. Enforced continuously.
  * **undocking turns it back on, if the laptop's own display is in use** —
    that edge is the moment the screen becomes usable again. Enforced once, at
    the transition. When the top panel is off (external-only, or the lid shut
    over the bottom panel) the bottom one stays off: uncovering a screen is not
    the same as wanting it.

Everything else in the layout belongs to the user: the top panel, external
monitors, their positions, scales, and which one is primary. The daemon reads
them, preserves them, and never asserts them. An earlier version described the
policy as "docked -> enable exactly [top]", which also switched the top panel
ON — so choosing "External Only" from Win+P while docked snapped the laptop
screen straight back on. Governing one panel instead of the whole layout is
what makes External Only, Laptop Only, and a hand-disabled panel all survive.

A mirrored layout is left alone entirely, since rebuilding it as one logical
monitor per connector would silently un-mirror the desktop.

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
     NOT udev, which storms on this pogo-pin device forest (docs/HARDWARE.md V14);
  2. Mutter's MonitorsChanged signal, so a layout change is corrected in the
     same breath instead of up to a second later;
  3. logind's PrepareForSleep, so resume re-checks even when nothing else
     moved. USB re-enumeration is not instant, so resume waits for the layout
     and the dock state to settle before acting.

A manual `duo top/bottom/both/toggle/only` (including the second-screen Fn key,
which runs `duo toggle`) records an override; while it matches the current dock
state the policy is not enforced, so a deliberate choice sticks. Docking,
undocking, or plugging a monitor in or out retires it. `duo apply-displays`
drops it and converges once.

The daemon also keeps Mutter's per-monitor-set layout memory up to date
(lib/monitors_xml.py), which is what makes the machine behave like Windows:
whatever layout is on screen when things settle is recorded as the layout for
the monitors that are connected, so the next lid-open, hotplug or boot comes
back to it — including the lock screen and, through `duo layout login`, the
greeter. Mutter only ever wrote that file for GNOME Settings' "Keep changes",
so a layout chosen with Super+P was forgotten the moment the connectors were
re-probed. Recording it needs no apply: no flicker, no confirmation dialog.

Two things are deliberately NOT remembered: a manual override (it is temporary
by definition, and lapses at the next dock change) and anything applied while
the daemon is in storm backoff. Restoring is a backstop only — Mutter does it
first and earlier — for the cases where Mutter falls back instead: a monitor
whose mode list changed, a stored layout it refused because the lid was shut
over a panel, or a gnome-shell restart. It runs when the monitor set changes
and after resume, never in the middle of the user changing things.

Usage: watch_displays.py [--once]   (--once: converge now, then record)
Exit codes: 0 ok · 1 Mutter/D-Bus failure (--once only) · 2 refused by R10.
"""

import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dock  # noqa: E402  (same directory)
import displayctl  # noqa: E402  (same directory)
import monitors_xml  # noqa: E402  (same directory)

try:
    from gi.repository import Gio, GLib  # noqa: E402
except ImportError:
    print(displayctl.GI_MISSING, file=sys.stderr)
    sys.exit(1)

POLL_SECONDS = 1
DEBOUNCE_SAMPLES = 2      # 2 s of agreement before a dock/undock counts
COALESCE_MS = 300         # Mutter emits MonitorsChanged several times per change
RESUME_SETTLE_SECONDS = 3  # let USB re-enumerate and Mutter finish restoring
RETRY_SECONDS = 5
# How long the layout has to hold still before it counts as the user's choice.
# Long enough to coalesce a dock transition (which applies twice) and GNOME
# Settings' preview-then-confirm, short enough that closing the lid and
# walking away still records what was on screen.
RECORD_SETTLE_SECONDS = 3

# If we ever end up in a tug-of-war with something else that re-applies a
# layout, stop pulling: log it and stand down instead of burning the CPU and
# flashing the panels.
STORM_APPLIES = 5
STORM_WINDOW_SECONDS = 20
STORM_BACKOFF_SECONDS = 60

INTERNAL = (displayctl.TOP, displayctl.BOTTOM)

DUO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "bin", "duo"))


def remembering():
    return os.environ.get("ZENDUO_REMEMBER_LAYOUT", "1") == "1"


def dock_policy_on():
    return os.environ.get("ZENDUO_DOCK_POLICY", "1") == "1"


def log(msg):
    # stdout is the journal under the unit's SyslogIdentifier=zenduo; a
    # syslog() copy used to land there a second time under the same identifier.
    print(f"watch-displays: {msg}", flush=True)


class Watcher:
    def __init__(self):
        self.docked = None      # debounced truth; None until the first samples
        self._raw = None        # last raw sample
        self._streak = 0        # consecutive identical raw samples
        self._proxy = None
        self._system_bus = None  # MUST be kept: see run(), it owns the logind subscription
        self._timer = 0
        self._quiet_until = 0.0     # storm backoff
        self._resume_deadline = 0.0  # how long to distrust a contradicting dock probe
        self._applies = []      # monotonic timestamps, for storm detection
        self._announced_override = None
        self._announced_mirror = False
        self._announced_policy_off = False
        self._pending_undock = False  # an undock edge still owing the bottom panel
        self._topology = None   # the set of connected monitors, as a config key
        self._restore_pending = True   # check the remembered layout once per set
        self._record_timer = 0
        self._announced_memory_error = False
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
        sync needs the root helper (system/50-sudoers.sh), and a machine
        without it must still get the layout change.
        """
        try:
            self._children.append(subprocess.Popen(
                [DUO, "sync-backlight"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True))
            log("bottom panel enabled — syncing its backlight to the top panel")
        except OSError as e:
            log(f"could not start sync-backlight: {e}")

    def schedule_record(self):
        """(Re)start the settle timer that records the layout on screen."""
        if not remembering():
            return
        if self._record_timer:
            GLib.source_remove(self._record_timer)
        self._record_timer = GLib.timeout_add_seconds(RECORD_SETTLE_SECONDS,
                                                      self.record_layout)

    def record_layout(self):
        """Remember the settled layout as this monitor set's layout."""
        self._record_timer = 0
        if not remembering() or self._pending_undock:
            return GLib.SOURCE_REMOVE
        if time.monotonic() < self._quiet_until:
            return GLib.SOURCE_REMOVE  # storming: this is not the user's layout
        override = dock.read_override()
        if override is not None and bool(override.get("docked")) == self.docked:
            # A manual nudge lapses at the next dock change, so it must not
            # become the layout that comes back for good. `duo layout` is the
            # verb that records, and it records at the moment it runs.
            return GLib.SOURCE_REMOVE
        try:
            _serial, monitors_raw, logical_raw, _properties = displayctl.get_state(
                self.proxy())
        except displayctl.DisplayCtlError:
            return GLib.SOURCE_REMOVE  # the next converge will come back to this
        config = monitors_xml.snapshot(displayctl.parse_monitors(monitors_raw),
                                       logical_raw)
        if not config.logicals:
            return GLib.SOURCE_REMOVE
        try:
            changed = monitors_xml.remember(config)
        except (monitors_xml.FormatError, OSError) as e:
            if not self._announced_memory_error:
                self._announced_memory_error = True
                log(f"not remembering layouts: {e}")
            return GLib.SOURCE_REMOVE
        self._announced_memory_error = False
        if changed:
            log(f"remembered for these monitors: {config.describe()}")
            self.push_login_screen()
        return GLib.SOURCE_REMOVE

    def push_login_screen(self):
        """Give the greeter the same layouts, so the password prompt follows.

        Best effort and never blocking: it needs the root helper, and a
        machine without it (or without GDM) must still get everything else.
        stderr is inherited so an unexpected failure lands in the journal.
        """
        if os.environ.get("ZENDUO_LOGIN_SCREEN_LAYOUT", "1") != "1":
            return
        if monitors_xml.gdm_monitors_path() is None:
            return
        try:
            # stdout and stderr are inherited, which under the unit is the
            # journal: `duo layout login` says one line and only on failure.
            self._children.append(subprocess.Popen(
                [DUO, "layout", "login", "--quiet"], start_new_session=True))
        except OSError as e:
            log(f"could not update the login screen layout: {e}")

    def restore_remembered(self, serial, monitors, logical_raw, properties):
        """Put this monitor set's remembered layout back. True if it applied."""
        try:
            stored = monitors_xml.stored_for(self._topology)
        except (monitors_xml.FormatError, OSError) as e:
            if not self._announced_memory_error:
                self._announced_memory_error = True
                log(f"cannot read remembered layouts: {e}")
            return False
        if stored is None:
            return False
        # Apply the dock policy to the remembered layout BEFORE handing it
        # over, so a remembered bottom panel is not lit under the keyboard for
        # the fraction of a second it would take to correct it.
        drop = ({displayctl.BOTTOM}
                if self.docked and dock_policy_on() else set())
        try:
            logicals = displayctl.build_from_stored(stored, monitors, properties,
                                                    drop=drop)
        except displayctl.DisplayCtlError as e:
            log(f"remembered layout does not fit this machine: {e}")
            return False
        live = monitors_xml.snapshot(monitors, logical_raw)
        if displayctl.logicals_shape(logicals) == live.shape():
            return False  # already exactly this; nothing to do
        if self.storming():
            return False
        try:
            displayctl.apply_config(self.proxy(), serial, logicals)
        except displayctl.DisplayCtlError as e:
            log(f"{e} — retrying in {RETRY_SECONDS}s")
            self.schedule(RETRY_SECONDS * 1000)
            return False
        self._applies.append(time.monotonic())
        log(f"restored the layout remembered for these monitors: {stored.describe()}")
        return True

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
        # Undocking earns the bottom panel back. Only a real edge does: at
        # startup we do not know what came before, so an undocked machine keeps
        # whatever layout it booted with rather than having a panel forced on.
        if not first and not raw:
            self._pending_undock = True
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
        # restoring monitors.xml. Re-debounce the dock state from scratch, but
        # converge straight away — deferring wholesale would leave a wrongly
        # lit bottom panel on screen for the whole settle window, which is the
        # exact thing this daemon exists to prevent. converge() distrusts only
        # a probe that CONTRADICTS what we knew before suspending.
        log("resumed — re-checking dock state and panel layout")
        # Mutter re-reads monitors.xml on resume; if it fell back instead (a
        # refused or stale stored config) the remembered layout is put back.
        self._restore_pending = True
        self._raw, self._streak = None, 0
        self._resume_deadline = time.monotonic() + RESUME_SETTLE_SECONDS
        self.schedule(0)

    # ── the actual work ──────────────────────────────────────────────────────

    @staticmethod
    def is_mirrored(logical_monitors):
        """True if any logical monitor drives more than one output.

        That is GNOME's mirror mode. build_config models one logical monitor
        per connector, so re-applying would silently un-mirror the desktop —
        we leave such a layout alone instead.
        """
        return any(len(assigned) > 1 for (*_rest, assigned, _props) in logical_monitors)

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
        """Reconcile the machine with what it should be showing. Idempotent.

        Three things, in the order they have to happen: the layout remembered
        for this set of monitors is put back if Mutter did not do it, the dock
        policy decides the bottom panel, and whatever ends up on screen is
        recorded as this monitor set's layout once it settles.
        """
        if self.docked is None:
            return 0  # dock state not established yet; the poll will call back
        now = time.monotonic()
        if now < self._quiet_until:
            self.schedule(int((self._quiet_until - now) * 1000) + 50)
            return 0
        if now < self._resume_deadline and dock.keyboard_docked() != self.docked:
            # Just resumed and the probe disagrees with the pre-suspend state:
            # either the keyboard really came off during sleep, or USB has not
            # re-enumerated yet. Ambiguous, so let the poll's debounce settle it
            # instead of flapping the panels on a half-probed machine. A probe
            # that AGREES is not ambiguous, so that path corrects immediately.
            self.schedule(POLL_SECONDS * 1000)
            return 0

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

        # Which monitors are connected is the key to the layout memory, and a
        # change of it is as much "the situation changed" as a dock or undock:
        # it retires a manual override and asks for the remembered layout.
        topology = monitors_xml.topology(monitors)
        if topology != self._topology:
            first = self._topology is None
            self._topology, self._restore_pending = topology, True
            if not first:
                log("monitor set changed: " + " · ".join(
                    monitors_xml.Spec(*spec).describe() for spec in topology))
                if dock.clear_override():
                    log("monitor set changed — manual display override cleared")

        override = dock.read_override()
        override_active = (override is not None
                           and bool(override.get("docked")) == self.docked)

        # The layout memory is its own feature: it keeps the machine coming
        # back to the layout the user chose even with DOCK_POLICY=0, and it
        # never fights a deliberate choice, because a change the user makes is
        # what gets recorded a moment later.
        if remembering() and self._restore_pending and not override_active:
            self._restore_pending = False
            if self.restore_remembered(serial, monitors, logical_raw, properties):
                return 0  # MonitorsChanged brings us back for the dock rule
        self.schedule_record()

        if not dock_policy_on():
            # DOCK_POLICY=0 in zenduo.conf: keep running (so the unit stays
            # healthy and the knob can be flipped back without a re-enable)
            # but never touch the bottom panel.
            if not self._announced_policy_off:
                self._announced_policy_off = True
                log("dock policy is OFF (DOCK_POLICY=0 in zenduo.conf) — watching, not acting")
            return 0
        self._announced_policy_off = False

        if override_active:
            if self._announced_override != override:
                self._announced_override = override
                want = ", ".join(override.get("want", [])) or "?"
                log(f"manual override active ({want}) — dock policy paused until the "
                    f"keyboard is docked or undocked, a monitor is plugged in or "
                    f"out, or `duo apply-displays` runs")
            return 0
        self._announced_override = None

        if self.is_mirrored(logical_raw):
            self._pending_undock = False  # hands off means the edge is spent
            if not self._announced_mirror:
                self._announced_mirror = True
                log("mirrored layout — leaving it alone (re-applying would un-mirror it)")
            return 0
        self._announced_mirror = False

        # The daemon governs exactly one thing: whether the BOTTOM panel is on.
        # The top panel, the externals, their positions, scales and which one is
        # primary are all the user's business — asserting a whole layout is what
        # made "External Only" (Win+P) snap the top panel back on.
        bottom_on = displayctl.BOTTOM in enabled
        if self.docked:
            # Continuous invariant: the keyboard is physically covering the
            # bottom panel, so nothing useful can be shown there.
            if not bottom_on:
                return 0
            want = [c for c in enabled if c != displayctl.BOTTOM]
            if not want:
                # Bottom was the only thing lit; blanking the machine is never
                # allowed (R10), so land on the panel the user can actually see.
                want = [displayctl.TOP]
            reason = "docked, bottom panel is under the keyboard"
        else:
            # Undocking is an *edge*: it means "the bottom screen just became
            # usable". Outside that moment an undocked layout is the user's own,
            # so External Only / Laptop Only / a bottom panel they turned off by
            # hand all survive.
            if not self._pending_undock:
                return 0
            # Evaluated exactly once, whatever the outcome — a deferred edge
            # that fires later, when the layout has moved on, is a surprise.
            # Only a failed apply below puts it back.
            self._pending_undock = False
            if bottom_on or displayctl.BOTTOM not in monitors:
                return 0
            if displayctl.TOP not in enabled:
                # The laptop's own display is off — external-only, or the lid is
                # shut over the bottom panel. The bottom screen follows the top
                # one: undocking uncovers it, but "uncovered" is not "wanted".
                log("undocked with the laptop display off — leaving the bottom "
                    "panel off (use `duo both` or Win+P to bring it back)")
                return 0
            want = list(enabled) + [displayctl.BOTTOM]
            reason = "undocked, bringing the bottom panel back"

        if self.storming():
            self._pending_undock = not self.docked  # unfinished edge: try later
            return 0
        # Externals keep their own positions; build_config re-places them only
        # if the new internal stack would collide with where they already are.
        want = displayctl.order_connectors(want)
        try:
            logicals = displayctl.build_config(monitors, logical_raw, properties, want)
            displayctl.apply_config(p, serial, logicals)
        except displayctl.DisplayCtlError as e:
            self._pending_undock = not self.docked  # unfinished edge: try again
            log(f"{e} — retrying in {RETRY_SECONDS}s")
            self.schedule(RETRY_SECONDS * 1000)
            return e.code
        self._applies.append(time.monotonic())
        log(f"{reason}: [{', '.join(displayctl.order_connectors(enabled)) or 'none'}]"
            f" -> [{', '.join(want)}]")
        if displayctl.BOTTOM in want and not bottom_on:
            self.sync_bottom_backlight()
        return 0

    # ── entry points ─────────────────────────────────────────────────────────

    def run_once(self):
        """Converge a single time, ignoring debounce and any manual override.

        Asking for the policy by hand means "make it match now", so this also
        claims the undock edge the daemon would otherwise wait for.
        """
        self.docked = dock.keyboard_docked()
        self._pending_undock = not self.docked
        if dock.clear_override():
            log("manual display override cleared")
        code = self.converge()
        # Asking for the policy by hand also settles what should come back:
        # record it now rather than leaving the file a layout behind (the
        # settle timer belongs to the daemon's main loop, which --once has not).
        if remembering():
            self.record_layout()
        return code

    def run(self):
        log(f"started (poll {POLL_SECONDS} Hz + MonitorsChanged + resume; "
            f"debounce {DEBOUNCE_SAMPLES} samples; layout memory "
            f"{'on' if remembering() else 'off'})")
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
            # Keep the connection alive for the lifetime of the daemon. Letting
            # it fall out of scope silently unsubscribes when Python collects
            # the wrapper — the subscription dies with the connection object
            # and resume events stop arriving, with nothing logged either way.
            self._system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self._system_bus.signal_subscribe(
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
    watcher = Watcher()
    return watcher.run_once() if once else watcher.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
