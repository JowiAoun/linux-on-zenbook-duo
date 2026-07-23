#!/usr/bin/env python3
"""Keyboard-backlight fallback for the ASUS Zenbook Duo keyboard (0b05:1b2c).

Mainline hid-asus has no entry for this device (PLAN.md V8), so on current
kernels there is no /sys/class/leds/asus::kbd_backlight node and we set the
backlight ourselves with the HID feature report the kernel driver would
send: {0x5a, 0xba, 0xc5, 0xc4, <level 0-3>} (constants from hid-asus.c —
facts, not copied code).

Transport: /dev/hidraw* via the HIDIOCSFEATURE ioctl. Unlike pyusb this
never detaches the kernel driver, so typing keeps working. Unprivileged
access requires the udev uaccess rule installed by system/45-duo-udev.sh.
A pyusb path is intentionally NOT implemented — if hidraw fails we want to
know why, not silently degrade to a driver-detaching transport.

Usage: kb_backlight.py <0|1|2|3>
Exit codes: 0 ok · 1 no device/all writes failed · 13 permission denied · 64 usage.
"""

import fcntl
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_init  # noqa: E402  (same directory; shares node discovery + sizing)

VID = "0B05"
PID = "1B2C"

MAX_LEVEL = 3


def state_path():
    """Where the chosen level is remembered across dock, undock and reboot.

    The keyboard loses its backlight whenever it re-enumerates, so the level
    has to live on this side. XDG_STATE_HOME is the right home for it: unlike
    the runtime dir it survives a reboot, and unlike config it is state the
    user set by pressing a key, not something they hand-edit.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "zenduo", "kb-backlight")


def read_level():
    """The remembered level, or 0 when nothing has been saved yet."""
    try:
        with open(state_path()) as f:
            level = int(f.read().strip())
    except (OSError, ValueError):
        return 0
    return level if 0 <= level <= MAX_LEVEL else 0


def save_level(level):
    path = state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(f"{level}\n")
        os.replace(tmp, path)
    except OSError:
        pass  # best effort: failing to remember must never fail the key press


def hidiocsfeature(length):
    # _IOC(_IOC_READ | _IOC_WRITE, 'H', 0x06, length)
    ioc_write, ioc_read = 1, 2
    return ((ioc_read | ioc_write) << 30) | (length << 16) | (ord("H") << 8) | 0x06


def keyboard_hidraw_nodes():
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        # HID_ID=0003:00000B05:00001B2C (USB). Detached, the keyboard
        # re-enumerates on the Bluetooth bus (0005) with different ids/name,
        # so match the ASUS vendor on ANY bus, or the model name.
        if f":0000{VID}:" in text or "ZENBOOK DUO" in text:
            yield "/dev/" + uevent.split("/")[4]


def set_level(level):
    payload = [0x5A, 0xBA, 0xC5, 0xC4, level]
    # Address the interface that owns the ASUS vendor collection. Sending to
    # "whichever node accepts first" is what made this work docked one minute
    # and not the next: several interfaces accept the write and drop it, and
    # which one is examined first changes every time the device re-enumerates.
    targets = list(kb_init.vendor_nodes())
    if not targets:
        # Bluetooth, or a descriptor that doesn't declare the report: fall back
        # to trying everything, which is all this could ever do before.
        targets = [(n, None) for n in kb_init.keyboard_hidraw_nodes()]
    if not targets:
        print("kb_backlight: keyboard 0b05:1b2c not found on hidraw "
              "(detached? paired over BT only?)", file=sys.stderr)
        return 1
    denied = False
    for node, _declared in targets:
        try:
            fd = os.open(node, os.O_RDWR)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        try:
            # Pad to the length the interface actually wants. The USB vendor
            # interface declares 16 and then STALLs anything but 17 (see
            # kb_init.candidate_sizes); a bare 5-byte write is refused there.
            for size in kb_init.candidate_sizes(node) + [len(payload)]:
                report = bytearray(max(size, len(payload)))
                report[:len(payload)] = bytes(payload)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(len(report)), bytes(report))
                except OSError:
                    continue
                save_level(level)
                print(f"kb_backlight: level {level} sent via {node} ({len(report)} bytes)")
                return 0
        finally:
            os.close(fd)
    if denied:
        print("kb_backlight: permission denied on hidraw — install the udev rule "
              "(sudo make system HOST=zenbook-duo) or re-attach the keyboard",
              file=sys.stderr)
        return 13
    print("kb_backlight: the vendor interface rejected the report at every length",
          file=sys.stderr)
    return 1


def main(argv):
    # --record just remembers a level someone else already applied (the native
    # LED path in bin/duo), so the cycle and the restore stay in step with the
    # hardware whichever transport set it.
    if len(argv) == 2 and argv[0] == "--record" and argv[1] in ("0", "1", "2", "3"):
        save_level(int(argv[1]))
        return 0
    if len(argv) == 1 and argv[0] == "--show":
        print(read_level())
        return 0
    if len(argv) != 1 or argv[0] not in ("0", "1", "2", "3"):
        print(__doc__, file=sys.stderr)
        return 64
    return set_level(int(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
