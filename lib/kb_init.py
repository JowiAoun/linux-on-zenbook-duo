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

# hid-asus.c asus_kbd_disable_oobe(): some ASUS keyboards ship in an
# "out-of-box experience" state and ignore hotkeys until these feature reports
# arrive (mainline sends them to the ProArt P16). The Duo keyboard behaves
# exactly OOBE-like — plain F-keys, media layer dormant — so we try them too.
OOBE_SEQUENCE = [
    [0x5A, 0x05, 0x20, 0x31, 0x00, 0x08],
    [0x5A, 0xBA, 0xC5, 0xC4],
    [0x5A, 0xD0, 0x8F, 0x01],
    [0x5A, 0xD0, 0x85, 0xFF],
]


def hidiocsfeature(length):
    # _IOC(_IOC_READ | _IOC_WRITE, 'H', 0x06, length)
    ioc_write, ioc_read = 1, 2
    return ((ioc_read | ioc_write) << 30) | (length << 16) | (ord("H") << 8) | 0x06


def keyboard_hidraw_nodes():
    # USB enumerates as 0003:00000B05:00001B2C, but detached the same keyboard
    # re-enumerates on the Bluetooth bus (0005) with whatever ids/name BT
    # advertises — so match the ASUS vendor id on ANY bus, or the model name.
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if f":0000{VID}:" in text or "ZENBOOK DUO" in text:
            yield "/dev/" + uevent.split("/")[4]


def send_handshake():
    nodes = list(keyboard_hidraw_nodes())
    if not nodes:
        print("kb_init: keyboard 0b05:1b2c not found on hidraw (docked?)", file=sys.stderr)
        return 1

    # Send the handshake to EVERY interface, not just the first that accepts it.
    # hid-asus targets the interface that carries the ASUS vendor collection
    # (on this keyboard that is a later hidraw node, not the main keyboard one),
    # so we must not stop early or the media layer never switches on.
    denied = False
    total_ok = 0
    for node in nodes:
        try:
            fd = os.open(node, os.O_RDWR)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        ok_ids = []
        oobe_ok = 0
        try:
            for report_id in REPORT_IDS:
                report = bytes([report_id] + HANDSHAKE_TAIL)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(len(report)), report)
                    ok_ids.append(report_id)
                except OSError:
                    pass  # this interface doesn't own this report id — expected
            for seq in OOBE_SEQUENCE:
                report = bytes(seq)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(len(report)), report)
                    oobe_ok += 1
                except OSError:
                    pass
        finally:
            os.close(fd)
        if ok_ids or oobe_ok:
            total_ok += len(ok_ids) + oobe_ok
            ids = " ".join(f"0x{r:02x}" for r in ok_ids) or "none"
            print(f"kb_init: {node}: handshake {ids}; oobe-disable {oobe_ok}/{len(OOBE_SEQUENCE)}")

    if total_ok:
        print("kb_init: handshake sent to every interface that accepted it — now press "
              "Fn+F5 etc. and watch `duo fn-probe` / `duo watch-input`.")
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
