#!/usr/bin/env python3
"""watch-fn — make the Zenbook Duo keyboard's media keys actually do things.

Ground truth (INSTALL-LOG Round 10): mainline hid-asus has no entry for this
keyboard, so nothing in the kernel initializes it or handles its vendor codes.
After `kb-init` sends the ASUS handshake + OOBE-disable, the keyboard's media
layer switches on and the F-row emits ASUS vendor reports (report id 0x5a):
brightness-down = 5a 10, brightness-up = 5a 20, Fn-lock = 5a 4e, the dedicated
second-screen key = 5a 6a. Volume/mute arrive as standard consumer-page usages
that Linux already handles natively — no work needed there.

This daemon closes the loop:
  - watches for the keyboard's hidraw nodes (USB or Bluetooth; they come and go
    with docking/pairing) at 1 Hz, re-sending the init whenever the node set
    changes — the keyboard forgets hotkey mode on re-enumeration
  - reads the 0x5a vendor reports and dispatches actions:
      brightness     -> GNOME's own StepUp/StepDown D-Bus (OSD included)
      second-screen  -> `duo toggle` (bottom panel on/off)
      kbd-backlight  -> `duo kb-backlight` cycle 0..3
  - honors ~/.config/zenduo/fn-map.json (from `duo fn-map`) as overrides, so
    newly-captured codes map onto actions without touching this file

Run via the duo-watch-fn systemd user service (zenbook-duo home-manager module)
or by hand: `duo watch-fn`. Needs the udev uaccess rule for hidraw access.
"""

import json
import os
import select
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_init  # noqa: E402  (same directory; shares node discovery + handshake)
import kb_backlight  # noqa: E402  (same directory; owns the remembered level)
import dock  # noqa: E402  (same directory; keyboard dock state)

DUO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "bin", "duo"))

VENDOR_REPORT_ID = 0x5A

# code (second report byte) -> action. Codes confirmed on hardware are noted;
# the 0xc4/0xc5 pair is hid-asus's kbd-backlight mapping (unconfirmed here —
# run `duo fn-map` and the saved map overrides/extends this table).
DEFAULT_ACTIONS = {
    0x10: "brightness-down",   # confirmed: bare F5 over BT after kb-init
    0x20: "brightness-up",     # confirmed: bare F6
    0x4E: "fn-lock",           # confirmed: Fn+Esc
    0x6A: "second-screen",     # confirmed: dedicated key left of PrtSc
    0xC7: "kbd-backlight",     # confirmed: bare F4 (one key cycles levels)
}

# Actions from a fn-map.json we know how to perform (everything else logged).
KNOWN_ACTIONS = {"brightness-down", "brightness-up", "fn-lock", "second-screen",
                 "kbd-backlight", "mute", "volume-down", "volume-up",
                 "mic-mute", "display-switch", "split-screen", "camera-toggle",
                 "emoji", "myasus"}


def log(msg):
    print(f"watch-fn: {msg}", flush=True)


def load_overrides():
    """fn-map.json entries (action -> report hex) folded into code -> action."""
    cfg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(cfg_home, "zenduo", "fn-map.json")
    table = dict(DEFAULT_ACTIONS)
    try:
        with open(path) as f:
            doc = json.load(f)
    except FileNotFoundError:
        return table
    except (OSError, ValueError) as e:
        log(f"ignoring unreadable {path}: {e}")
        return table
    for action, info in doc.get("keys", {}).items():
        report = info.get("report", "")
        parts = report.split()
        if len(parts) >= 2 and parts[0] == "5a":
            try:
                table[int(parts[1], 16)] = action
            except ValueError:
                pass
    return table


class Dispatcher:
    def __init__(self):
        self.children = []  # (Popen, argv), reaped by reap()

    def restore_backlight(self):
        """Put the keyboard backlight back to the remembered level.

        Docking, undocking and resuming all blank it in hardware, which is why
        it "went dark" on every transition even though the level was known.
        """
        level = kb_backlight.read_level()
        if level:
            log(f"restoring keyboard backlight to level {level}")
        self.spawn([DUO, "kb-backlight", str(level)])

    def spawn(self, argv):
        try:
            # Capture rather than discard: a key that silently does nothing is
            # indistinguishable from a key that never arrived, which is exactly
            # the hole that made "the media keys stopped working" so hard to
            # place. reap() surfaces whatever the command complained about.
            self.children.append((subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE), argv))
        except OSError as e:
            log(f"failed to run {argv[0]}: {e}")

    def reap(self):
        still_running = []
        for proc, argv in self.children:
            if proc.poll() is None:
                still_running.append((proc, argv))
                continue
            if proc.returncode != 0:
                err = (proc.stderr.read() or b"").decode(errors="replace").strip()
                log(f"{' '.join(argv)} failed (rc={proc.returncode})"
                    + (f": {err.splitlines()[-1]}" if err else ""))
            proc.stderr.close()
        self.children = still_running

    def run(self, argv):
        try:
            subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"failed to run {argv[0]}: {e}")

    def gsd_screen(self, method):
        # GNOME settings-daemon's own brightness path: applies the change AND
        # shows the on-screen display, exactly like a natively-handled key.
        # Blocking, so the follow-up second-panel sync reads the updated level.
        self.run(["gdbus", "call", "--session",
                  "--dest", "org.gnome.SettingsDaemon.Power",
                  "--object-path", "/org/gnome/SettingsDaemon/Power",
                  "--method", f"org.gnome.SettingsDaemon.Power.Screen.{method}"])

    def brightness(self, method):
        self.gsd_screen(method)
        # GNOME drives only the primary panel; mirror the new level onto the
        # bottom panel so both screens dim together when the keyboard is undocked.
        self.spawn([DUO, "sync-backlight"])

    def dispatch(self, code, action):
        log(f"key 5a {code:02x} -> {action}")
        if action == "brightness-down":
            self.brightness("StepDown")
        elif action == "brightness-up":
            self.brightness("StepUp")
        elif action == "kbd-backlight":
            # Cycle from what is actually remembered, not from a counter held
            # in this process. The keyboard blanks its backlight every time it
            # re-enumerates, and an in-memory counter kept climbing from the
            # pre-dock value — so after docking at level 2 the first press went
            # to 3 instead of restoring 2.
            nxt = (kb_backlight.read_level() + 1) % (kb_backlight.MAX_LEVEL + 1)
            self.spawn([DUO, "kb-backlight", str(nxt)])
        elif action == "second-screen":
            # Docked, the keyboard is lying on the bottom panel: turning it on
            # would light a screen nobody can see, and (because a hand-issued
            # layout pauses the dock policy) it would stay lit until the next
            # dock or undock. The key is only meaningful once the panel is free.
            if dock.keyboard_docked():
                log("second-screen key ignored — the keyboard is docked over "
                    "the bottom panel")
            else:
                self.spawn([DUO, "toggle"])
        elif action == "fn-lock":
            pass  # see the module docstring: the swap is not ours to perform yet
        else:
            log(f"no handler for '{action}' yet — captured for the future")


def slept_since(last):
    """(suspended?, new marks) — CLOCK_BOOTTIME counts suspend, CLOCK_MONOTONIC
    does not, so the gap between them is exactly the time spent asleep.

    The keyboard forgets hotkey mode whenever it loses power, and a resume can
    hand back the very same hidraw node names — so watching the node set alone
    misses it, and the media layer stays dead until a physical re-dock. That is
    the "worked yesterday, dead after a few sleeps" failure. No D-Bus needed:
    two clock reads tell us the machine was away.
    """
    mono, boot = time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME)
    if last is None:
        return False, (mono, boot)
    slept = (boot - last[1]) - (mono - last[0])
    return slept > 1.0, (mono, boot)


def main():
    # Line-buffer stdout so kb_init's prints reach the journal when they happen.
    # Block-buffered through a pipe they sat unflushed for 37 minutes, arriving
    # stamped with a much later event and pointing diagnosis at the wrong time.
    sys.stdout.reconfigure(line_buffering=True)
    actions = load_overrides()
    dispatcher = Dispatcher()
    fds = {}
    known = ()
    clocks = None
    failures, retry_at = 0, 0.0
    log(f"started (actions: {len(actions)} codes; map overrides honored)")
    while True:
        dispatcher.reap()
        woke, clocks = slept_since(clocks)
        if woke:
            log("resumed from sleep — re-sending the keyboard handshake")
            known = ()  # the keyboard lost hotkey mode while the machine was off
        nodes = tuple(sorted(kb_init.keyboard_hidraw_nodes()))
        if nodes != known and time.monotonic() >= retry_at:
            for fd in list(fds):
                os.close(fd)
            fds = {}
            if nodes:
                log(f"keyboard present on {' '.join(nodes)} — sending init")
                rc = kb_init.send_handshake(hint=False)
                for n in nodes:
                    try:
                        fds[os.open(n, os.O_RDONLY | os.O_NONBLOCK)] = n
                    except OSError as e:
                        log(f"cannot read {n}: {e}")
                # Only remember this node set once the init AND at least one open
                # actually succeeded. Docking races udev: the hidraw nodes appear
                # a moment before the uaccess ACL lands, so the first attempt can
                # fail with EACCES — committing `known` there would wedge the
                # daemon in the 2 s idle loop until a physical re-dock.
                #
                # send_handshake now only reports success when the keyboard
                # echoes the handshake back, so a failure here means the media
                # layer really is off and retrying is the right thing. Back off
                # while doing so: the OOBE sequence shares a prefix with the
                # keyboard-backlight report, and re-sending it every couple of
                # seconds forever would poke the device far harder than intended.
                if rc == 0 and fds:
                    known = nodes
                    failures, retry_at = 0, 0.0
                    # The keyboard is back and initialised: give it its
                    # backlight back rather than leaving it dark until the
                    # user presses the key.
                    dispatcher.restore_backlight()
                else:
                    failures += 1
                    delay = min(60, 2 ** min(failures, 6))
                    retry_at = time.monotonic() + delay
                    if failures == 1 or failures % 10 == 0:
                        log(f"hotkey mode not confirmed (attempt {failures}) — "
                            f"media keys are dead; retrying in {delay}s")
            else:
                log("keyboard gone (undocked / BT off) — waiting")
                known = nodes
                failures, retry_at = 0, 0.0
        if not fds:
            time.sleep(2)
            continue
        ready, _, _ = select.select(list(fds), [], [], 2.0)
        for fd in ready:
            try:
                data = os.read(fd, 64)
            except OSError:
                os.close(fd)
                node = fds.pop(fd, None)
                log(f"lost {node}; rescanning")
                known = ()  # force a rescan + re-init next loop
                continue
            if len(data) >= 2 and data[0] == VENDOR_REPORT_ID and data[1] != 0:
                code = data[1]
                dispatcher.dispatch(code, actions.get(code, f"unmapped-0x{code:02x}"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nwatch-fn: stopped", file=sys.stderr)
        sys.exit(0)
