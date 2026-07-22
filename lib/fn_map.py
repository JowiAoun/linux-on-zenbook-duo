#!/usr/bin/env python3
"""Guided key-mapping wizard for the ASUS Zenbook Duo keyboard (0b05:1b2c).

`duo fn-probe` dumps raw HID reports and leaves you to read hex. This is the
friendly version: it names one key at a time ("Press Fn+F6 - brightness up"),
waits for the press, captures the raw report that key emits, and after the whole
row writes a key->report map on disk that `duo watch-fn` will later turn into
real actions (brightness, volume, keyboard backlight, ...).

IMPORTANT - the media functions are the *Fn layer*. On this laptop the bare
F-row keys are ordinary F1..F12 (they reach the terminal as escape sequences and
trigger F10=menu / F11=fullscreen); the brightness/volume/backlight icons only
fire when you HOLD Fn. So hold Fn while pressing each "Fn+Fx" key below. The one
dedicated key left of PrtSc has no F-key meaning and fires bare.

Why raw reports at all: the Duo's media/Fn keys are ASUS vendor HID usages that
hid-generic does not translate into input events, and hid_asus has no entry for
this device (PLAN.md V8) - so the only place their signal appears is the raw
hidraw stream.

Reading the keyboard's hidraw stream also sees ordinary typing, so we only
accept the ASUS *vendor* reports (report id 0x5a); normal keystrokes use a
different report id and are ignored. That keeps the "type s to skip" input from
being mistaken for a key press.

Controls at each prompt: press the named key, OR type `s` + Enter to skip a key
that does nothing / you don't care about, OR `q` + Enter to stop early (whatever
you mapped so far is still saved).

Usage:
  fn_map.py            run the wizard
  fn_map.py --show     print the saved map, without re-capturing anything

Unprivileged hidraw access needs the udev uaccess rule (system/45-duo-udev.sh);
if opening a node is denied, re-run `sudo make system HOST=zenbook-duo`, or sudo.
Map is written to  $XDG_CONFIG_HOME/zenduo/fn-map.json  (default ~/.config/...).
Exit: 0 finished (map saved) - 1 no keyboard / nothing readable.
"""

import glob
import json
import os
import select
import sys
import time

VID = "0B05"
PID = "1B2C"

# ASUS vendor "hotkey" reports start with this report id; ordinary keystrokes
# use a different one, so filtering on it ignores typing (incl. skip/quit input).
VENDOR_REPORT_ID = 0x5A

# The Fn-row plus the dedicated second-screen key, in press order. `action` is
# the stable name a future `duo watch-fn` keys off; `key`/`desc` drive the
# prompt. Everything labelled "Fn+Fx" needs Fn HELD (the bare key is F1..F12).
KEYS = [
    ("mute",            "Fn+F1",  "mute (speaker with x)"),
    ("volume-down",     "Fn+F2",  "volume DOWN (speaker -)"),
    ("volume-up",       "Fn+F3",  "volume UP (speaker +)"),
    ("kbd-backlight",   "Fn+F4",  "keyboard backlight (cycles levels)"),
    ("brightness-down", "Fn+F5",  "screen brightness DOWN (small sun)"),
    ("brightness-up",   "Fn+F6",  "screen brightness UP (large sun)"),
    ("display-switch",  "Fn+F7",  "external display / projector"),
    ("split-screen",    "Fn+F8",  "screen-layout / MyASUS split"),
    ("mic-mute",        "Fn+F9",  "microphone mute"),
    ("camera-toggle",   "Fn+F10", "camera on/off"),
    ("emoji",           "Fn+F11", "emoji picker"),
    ("myasus",          "Fn+F12", "MyASUS"),
    ("second-screen",   "key",    "dedicated second-screen toggle, left of PrtSc (NO Fn)"),
]


def map_path():
    cfg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(cfg_home, "zenduo", "fn-map.json")


def keyboard_hidraw_nodes():
    # USB enumerates as 0003:00000B05:00001B2C, but detached the same keyboard
    # re-enumerates on the Bluetooth bus (0005) with whatever ids/name BT
    # advertises — so match the ASUS vendor id on ANY bus, or the model name.
    nodes = []
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if f":0000{VID}:" in text or "ZENBOOK DUO" in text:
            nodes.append("/dev/" + uevent.split("/")[4])
    return nodes


def is_key_event(data):
    # A vendor key press: right report id, and a nonzero byte after it (an
    # all-zero tail is the key-release report we ignore).
    return len(data) >= 2 and data[0] == VENDOR_REPORT_ID and any(data[1:])


def trim(data):
    # Drop trailing zero bytes so the signature is stable regardless of the
    # report's fixed on-wire length.
    end = len(data)
    while end > 1 and data[end - 1] == 0:
        end -= 1
    return bytes(data[:end])


def flush(fds):
    # Discard anything already buffered, without blocking.
    while True:
        ready, _, _ = select.select(list(fds), [], [], 0)
        if not ready:
            return
        for fd in ready:
            try:
                os.read(fd, 64)
            except OSError:
                pass


def drain(fds, seconds):
    # Discard everything readable within a window (key auto-repeat + release).
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        ready, _, _ = select.select(list(fds), [], [], remaining)
        for fd in ready:
            try:
                os.read(fd, 64)
            except OSError:
                pass


def capture_one(fds):
    # Returns ("ok", (sig_bytes, node)) | ("skip", None) | ("quit", None).
    flush(fds)
    while True:
        ready, _, _ = select.select(list(fds) + [sys.stdin], [], [], None)
        if sys.stdin in ready:
            line = sys.stdin.readline().strip().lower()
            if line in ("", "s", "skip"):
                return ("skip", None)
            if line in ("q", "quit"):
                return ("quit", None)
            continue  # stray typing / F-key escape sequence: keep waiting
        for fd in ready:
            try:
                data = os.read(fd, 64)
            except OSError:
                continue
            if is_key_event(data):
                sig = trim(data)
                drain(fds, 0.35)  # swallow auto-repeat + the release report
                return ("ok", (sig, fds[fd]))
            # wrong report id / all-zero release: ignore, keep waiting


def show_map():
    path = map_path()
    try:
        with open(path) as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"fn-map: no map yet at {path} — run 'duo fn-map' to create one.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"fn-map: cannot read {path}: {e}", file=sys.stderr)
        return 1
    keys = doc.get("keys", {})
    print(f"fn-map: {len(keys)} key(s) mapped in {path}\n")
    if not keys:
        print("  (empty) — run 'duo fn-map' to capture some.")
        return 0
    width = max(len(a) for a in keys)
    for action, info in keys.items():
        print(f"  {action:<{width}}  {info.get('key', ''):<6} {info.get('report', ''):<18} "
              f"{info.get('label', '')}")
    return 0


def run_wizard():
    nodes = keyboard_hidraw_nodes()
    if not nodes:
        print("fn-map: Zenbook Duo keyboard not found on hidraw (USB or BT).", file=sys.stderr)
        return 1

    fds = {}
    denied = False
    for n in nodes:
        try:
            fds[os.open(n, os.O_RDONLY | os.O_NONBLOCK)] = os.path.basename(n)
        except PermissionError:
            denied = True
        except OSError:
            pass
    if not fds:
        msg = "fn-map: could not open any hidraw node"
        if denied:
            msg += " (permission denied - run 'sudo make system HOST=zenbook-duo', or use sudo)"
        print(msg, file=sys.stderr)
        return 1

    print(f"fn-map: reading {', '.join(sorted(fds.values()))}", file=sys.stderr)
    print("HOLD Fn while pressing each 'Fn+Fx' key (the bare key is just F1..F12).", file=sys.stderr)
    print("s+Enter = skip a key,  q+Enter = stop early.\n", file=sys.stderr)

    mapping = {}
    seen = {}  # report hex -> action, to flag two keys that look identical
    for action, key, desc in KEYS:
        sys.stderr.write(f"  -> Press {key:<6}  -  {desc} ... ")
        sys.stderr.flush()
        status, payload = capture_one(fds)
        if status == "quit":
            print("stopping.", file=sys.stderr)
            break
        if status == "skip":
            print("skipped.", file=sys.stderr)
            continue
        sig, node = payload
        sighex = sig.hex(" ")
        if sighex in seen:
            print(f"captured [{sighex}]  (!) same report as '{seen[sighex]}'", file=sys.stderr)
        else:
            print(f"captured [{sighex}]", file=sys.stderr)
        seen[sighex] = action
        mapping[action] = {"key": key, "label": desc, "node": node, "report": sighex}

    for fd in fds:
        os.close(fd)

    out_path = map_path()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = {"version": 1, "keyboard": "0b05:1b2c", "keys": mapping}
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    print(f"\nfn-map: saved {len(mapping)} key(s) to {out_path}", file=sys.stderr)
    if not mapping:
        print("fn-map: nothing captured. If keys fired but weren't seen, the vendor\n"
              "        report id may differ - run 'duo fn-probe' and share a sample.",
              file=sys.stderr)
    print("\n---- copy the block below and share it ----")
    print(json.dumps(doc, indent=2))
    print("---- end ----")
    return 0


def main(argv):
    if "--show" in argv:
        return show_map()
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    return run_wizard()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nfn-map: stopped", file=sys.stderr)
        sys.exit(0)
