#!/usr/bin/env python3
"""uinput_keys — a virtual keyboard that presses keys the kernel never sees.

GNOME 49+ handles the brightness keys inside GNOME Shell: its keybindings
step the slider, set every panel through Mutter and show the OSD
(js/misc/brightnessManager.js, gnome-50 branch, read 2026-10-19). Nothing on
D-Bus does the same: a backlight changed through Mutter moves the panel but
GNOME Shell deliberately neither shows the OSD nor moves its slider for it.
The Duo keyboard's brightness keys arrive as ASUS vendor reports that never
become key events (mainline hid-asus has no entry for it, V8), so watch-fn
presses KEY_BRIGHTNESSUP / KEY_BRIGHTNESSDOWN on this device instead and GNOME
does the rest exactly as for a natively-handled key.

Needs write access to /dev/uinput: system/45-udev.sh tags it uaccess, the
same grant the hidraw nodes get. stdlib only.
"""

import fcntl
import os
import struct
import time

UINPUT_PATH = "/dev/uinput"

# linux/uinput.h and linux/input-event-codes.h
UI_SET_EVBIT = 0x40045564   # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565  # _IOW('U', 101, int)
UI_DEV_CREATE = 0x5501      # _IO('U', 1)
UI_DEV_DESTROY = 0x5502     # _IO('U', 2)
EV_SYN, EV_KEY, SYN_REPORT = 0x00, 0x01, 0
BUS_VIRTUAL = 0x06
ABS_CNT = 64

KEY_BRIGHTNESSDOWN = 224
KEY_BRIGHTNESSUP = 225
KEYS = (KEY_BRIGHTNESSDOWN, KEY_BRIGHTNESSUP)

NAME = b"zenduo virtual hotkeys"


def user_dev():
    """struct uinput_user_dev: name[80], input_id, ff_effects_max, 4 abs arrays."""
    return (struct.pack("80sHHHHi", NAME, BUS_VIRTUAL, 0, 0, 1, 0)
            + bytes(4 * 4 * ABS_CNT))


def event(ev_type, code, value):
    """struct input_event with a zero timestamp (the kernel stamps it)."""
    return struct.pack("llHHi", 0, 0, ev_type, code, value)


def tap_events(key):
    """Press, sync, release, sync: one key press as GNOME reads it."""
    return b"".join((event(EV_KEY, key, 1), event(EV_SYN, SYN_REPORT, 0),
                     event(EV_KEY, key, 0), event(EV_SYN, SYN_REPORT, 0)))


class VirtualKeys:
    """Create the device once and keep it: libinput adds a new device
    asynchronously, so a device made per key press loses that press."""

    def __init__(self, path=UINPUT_PATH):
        self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for key in KEYS:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            os.write(self.fd, user_dev())
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise
        # Give the compositor a moment to open the new device before any tap.
        time.sleep(0.2)

    def tap(self, key):
        os.write(self.fd, tap_events(key))

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
