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
        self.kb_level = 0  # kbd-backlight cycle state (device default is off)

    def spawn(self, argv):
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"failed to run {argv[0]}: {e}")

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
            self.kb_level = (self.kb_level + 1) % 4
            self.spawn([DUO, "kb-backlight", str(self.kb_level)])
        elif action == "second-screen":
            self.spawn([DUO, "toggle"])
        elif action == "fn-lock":
            pass  # the keyboard handles the layer swap itself; nothing to do
        else:
            log(f"no handler for '{action}' yet — captured for the future")


def main():
    actions = load_overrides()
    dispatcher = Dispatcher()
    fds = {}
    known = ()
    log(f"started (actions: {len(actions)} codes; map overrides honored)")
    while True:
        nodes = tuple(sorted(kb_init.keyboard_hidraw_nodes()))
        if nodes != known:
            for fd in list(fds):
                os.close(fd)
            fds = {}
            if nodes:
                log(f"keyboard present on {' '.join(nodes)} — sending init")
                kb_init.send_handshake(hint=False)
                for n in nodes:
                    try:
                        fds[os.open(n, os.O_RDONLY | os.O_NONBLOCK)] = n
                    except OSError as e:
                        log(f"cannot read {n}: {e}")
            else:
                log("keyboard gone (undocked / BT off) — waiting")
            known = nodes
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
