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

VID = "0B05"
PID = "1B2C"


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
    report = bytes([0x5A, 0xBA, 0xC5, 0xC4, level])
    nodes = list(keyboard_hidraw_nodes())
    if not nodes:
        print("kb_backlight: keyboard 0b05:1b2c not found on hidraw "
              "(detached? paired over BT only?)", file=sys.stderr)
        return 1
    denied = False
    for node in nodes:
        try:
            fd = os.open(node, os.O_RDWR)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        try:
            fcntl.ioctl(fd, hidiocsfeature(len(report)), report)
            print(f"kb_backlight: level {level} sent via {node}")
            return 0
        except OSError:
            continue
        finally:
            os.close(fd)
    if denied:
        print("kb_backlight: permission denied on hidraw — install the udev rule "
              "(sudo make system HOST=zenbook-duo) or re-attach the keyboard",
              file=sys.stderr)
        return 13
    print("kb_backlight: all hidraw writes failed (device rejected the report?)",
          file=sys.stderr)
    return 1


def main(argv):
    if len(argv) != 1 or argv[0] not in ("0", "1", "2", "3"):
        print(__doc__, file=sys.stderr)
        return 64
    return set_level(int(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
