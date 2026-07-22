#!/usr/bin/env python3
"""Guided key-mapping wizard for the ASUS Zenbook Duo keyboard (0b05:1b2c).

`duo fn-probe` dumps raw HID reports and leaves you to read hex. This is the
friendly version: it names one Fn-row key at a time ("Press F6 - brightness
up"), waits for the press, captures the raw report that key emits, and after the
whole row writes a key->report map on disk that `duo watch-fn` will later turn
into real actions (brightness, volume, keyboard backlight, ...).

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

# The Fn-row, left -> right on the UX8406MA (2024). `action` is the stable name
# a future `duo watch-fn` keys off; `fkey`/`desc` are only for the prompt.
KEYS = [
    ("mute",            "F1",  "mute (speaker with x)"),
    ("volume-down",     "F2",  "volume DOWN (speaker -)"),
    ("volume-up",       "F3",  "volume UP (speaker +)"),
    ("kbd-backlight",   "F4",  "keyboard backlight (cycles levels)"),
    ("brightness-down", "F5",  "screen brightness DOWN (small sun)"),
    ("brightness-up",   "F6",  "screen brightness UP (large sun)"),
    ("display-switch",  "F7",  "external display / projector"),
    ("second-screen",   "F8",  "second-screen toggle"),
    ("mic-mute",        "F9",  "microphone mute"),
    ("camera-toggle",   "F10", "camera on/off"),
    ("emoji",           "F11", "emoji picker"),
    ("myasus",          "F12", "MyASUS"),
]


def keyboard_hidraw_nodes():
    nodes = []
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if f":0000{VID}:0000{PID}" in text:
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
            continue  # stray typing: keep waiting
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


def main():
    nodes = keyboard_hidraw_nodes()
    if not nodes:
        print("fn-map: keyboard 0b05:1b2c not on hidraw - is it docked?", file=sys.stderr)
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
    print("Press each key when named.  s+Enter = skip a key,  q+Enter = stop early.\n",
          file=sys.stderr)

    mapping = {}
    seen = {}  # report hex -> action, to flag two keys that look identical
    for action, fkey, desc in KEYS:
        sys.stderr.write(f"  -> Press {fkey}  -  {desc} ... ")
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
        mapping[action] = {"f": fkey, "label": desc, "node": node, "report": sighex}

    for fd in fds:
        os.close(fd)

    cfg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    out_dir = os.path.join(cfg_home, "zenduo")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "fn-map.json")
    doc = {"version": 1, "keyboard": "0b05:1b2c", "keys": mapping}
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    print(f"\nfn-map: saved {len(mapping)} key(s) to {out_path}", file=sys.stderr)
    if not mapping:
        print("fn-map: nothing captured. If keys did fire but weren't seen, the vendor\n"
              "        report id may differ - run 'duo fn-probe' and share a sample.",
              file=sys.stderr)
    print("\n---- copy the block below and share it ----")
    print(json.dumps(doc, indent=2))
    print("---- end ----")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nfn-map: stopped", file=sys.stderr)
        sys.exit(0)
