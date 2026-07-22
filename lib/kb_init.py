#!/usr/bin/env python3
"""Switch the ASUS Zenbook Duo keyboard (0b05:1b2c) into hotkey mode.

Mainline hid-asus has no entry for this device (PLAN.md V8), so the keyboard
never receives the ASUS init handshake: Fn+Fx stay plain F1..F12 and the media
keys emit nothing distinct (watch-input shows Fn+F5 == bare F5). hid-asus turns
the Fn/media layer on by sending an "ASUS Tech.Inc." feature-report handshake to
report ids 0x5a / 0x5d / 0x5e (sequence + constants from hid-asus.c
asus_kbd_init — facts, not copied code). We send the same handshake over hidraw
HIDIOCSFEATURE. After it, Fn+Fx should start emitting ASUS vendor reports —
capture them with `duo fn-probe`, then map with `duo fn-map`.

The keyboard forgets this on re-enumeration (detach/reattach, reboot, resume),
so it must be re-sent on each attach; the watch-displays daemon or a udev hook
can call `duo kb-init`.

Transport: hidraw HIDIOCSFEATURE — never detaches the kernel driver, so typing
keeps working. Needs the udev uaccess rule (system/45-duo-udev.sh) or root.
Exit: 0 accepted - 1 no device / all writes failed - 13 permission denied.
"""

import fcntl
import glob
import os
import sys

VID = "0B05"
PID = "1B2C"

# hid-asus.c asus_kbd_init(): report_id followed by "ASUS Tech.Inc.\0", sent to
# each of these report ids to enable Fn/media (hotkey) reporting.
HANDSHAKE_TAIL = [0x41, 0x53, 0x55, 0x53, 0x20, 0x54, 0x65, 0x63,
                  0x68, 0x2E, 0x49, 0x6E, 0x63, 0x2E, 0x00]  # "ASUS Tech.Inc.\0"
REPORT_IDS = [0x5A, 0x5D, 0x5E]


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
        if f":0000{VID}:0000{PID}" in text:
            yield "/dev/" + uevent.split("/")[4]


def send_handshake():
    nodes = list(keyboard_hidraw_nodes())
    if not nodes:
        print("kb_init: keyboard 0b05:1b2c not found on hidraw (docked?)", file=sys.stderr)
        return 1

    denied = False
    accepted = 0
    for report_id in REPORT_IDS:
        report = bytes([report_id] + HANDSHAKE_TAIL)
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
                accepted += 1
                print(f"kb_init: handshake 0x{report_id:02x} accepted via {node}")
                break
            except OSError:
                continue
            finally:
                os.close(fd)

    if accepted:
        print(f"kb_init: {accepted}/{len(REPORT_IDS)} handshake(s) accepted — now press "
              "Fn+F5 etc. and watch `duo fn-probe`.")
        return 0
    if denied:
        print("kb_init: permission denied on hidraw — run with sudo, or install the "
              "udev rule (sudo make system HOST=zenbook-duo).", file=sys.stderr)
        return 13
    print("kb_init: the keyboard rejected every handshake (unexpected — share this).",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(send_handshake())
