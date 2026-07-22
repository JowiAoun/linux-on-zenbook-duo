#!/usr/bin/env python3
"""Watch decoded EV_KEY events from the Duo keyboard + "Asus WMI hotkeys".

The evdev complement to fn-probe/fn-map (which read raw hidraw). Many ASUS Fn+Fx
media keys do NOT travel through the USB keyboard's hidraw at all - they go
ACPI -> asus-nb-wmi -> an evdev device ("Asus WMI hotkeys", input handler
eventNN). This prints the key events every ASUS input device emits, so we can
see whether brightness / volume / backlight reach the input layer, and under
which key code (or, for an unmapped hotkey, its raw MSC_SCAN scancode).

Devices are found in /proc/bus/input/devices (vendor 0b05, or a name containing
"asus"/"wmi"). Reading evdev needs root, so run it as:

    sudo <repo>/duo/bin/duo watch-input

Assumes a 64-bit kernel (struct input_event = 24 bytes). Ctrl-C to stop.
Exit: 0 stopped by user - 1 no devices / nothing readable.
"""

import os
import select
import struct
import sys

# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
# 64-bit: timeval = 2x long (8+8), then H H i -> 24 bytes, native alignment.
EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)

EV_KEY = 0x01
EV_MSC = 0x04
MSC_SCAN = 0x04

VALUE = {0: "released", 1: "pressed", 2: "repeat"}

# Codes worth naming; anything else prints as code:<n> so it can be looked up.
KEY_NAMES = {
    59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5", 64: "F6", 65: "F7",
    66: "F8", 67: "F9", 68: "F10", 87: "F11", 88: "F12",
    99: "SYSRQ(PrtSc)", 111: "DELETE",
    113: "MUTE", 114: "VOLUMEDOWN", 115: "VOLUMEUP",
    148: "PROG1", 149: "PROG2", 202: "PROG3", 203: "PROG4",
    152: "SCREENLOCK", 190: "F20", 212: "CAMERA",
    224: "BRIGHTNESSDOWN", 225: "BRIGHTNESSUP", 226: "MEDIA",
    227: "SWITCHVIDEOMODE", 228: "KBDILLUMTOGGLE", 229: "KBDILLUMDOWN",
    230: "KBDILLUMUP", 238: "WLAN", 240: "UNKNOWN", 245: "DISPLAY_OFF",
    247: "RFKILL", 248: "MICMUTE", 464: "FN", 560: "ALS_TOGGLE",
    530: "TOUCHPAD_TOGGLE", 583: "ASSISTANT", 585: "EMOJI_PICKER",
}


def asus_event_devices():
    """[('/dev/input/eventN', name), ...] for ASUS input devices."""
    out = []
    try:
        with open("/proc/bus/input/devices") as f:
            text = f.read()
    except OSError:
        return out
    for block in text.split("\n\n"):
        name, vendor, events = "", "", []
        for line in block.splitlines():
            if line.startswith("I:"):
                for tok in line.split():
                    if tok.startswith("Vendor="):
                        vendor = tok.split("=", 1)[1].lower()
            elif line.startswith("N:"):
                name = line.split("=", 1)[-1].strip().strip('"')
            elif line.startswith("H:"):
                for tok in line.replace("Handlers=", "").split():
                    if tok.startswith("event"):
                        events.append(tok)
        low = name.lower()
        if events and (vendor == "0b05" or "asus" in low or "wmi" in low):
            out.extend(("/dev/input/" + ev, name) for ev in events)
    return out


def main():
    devs = asus_event_devices()
    if not devs:
        print("watch-input: no ASUS input devices found (keyboard docked?)", file=sys.stderr)
        return 1

    fds = {}
    denied = False
    for path, name in devs:
        try:
            fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = (os.path.basename(path), name)
        except PermissionError:
            denied = True
        except OSError:
            pass
    if not fds:
        msg = "watch-input: could not open any event device"
        if denied:
            msg += " (permission denied - run with sudo)"
        print(msg, file=sys.stderr)
        return 1

    for _fd, (ev, name) in sorted(fds.items()):
        print(f"watch-input: reading {ev}  ({name})", file=sys.stderr)
    print("Press each media key; note the code it emits. Ctrl-C to stop.\n", file=sys.stderr)

    try:
        while True:
            ready, _, _ = select.select(list(fds), [], [], None)
            for fd in ready:
                try:
                    buf = os.read(fd, EV_SIZE * 64)
                except OSError:
                    continue
                ev = fds[fd][0]
                for i in range(0, len(buf) - EV_SIZE + 1, EV_SIZE):
                    _s, _us, etype, code, value = struct.unpack(EV_FMT, buf[i:i + EV_SIZE])
                    if etype == EV_KEY:
                        name = KEY_NAMES.get(code, f"code:{code}")
                        print(f"{ev:>8}  KEY  {name}  ({code})  {VALUE.get(value, value)}", flush=True)
                    elif etype == EV_MSC and code == MSC_SCAN:
                        print(f"{ev:>8}  MSC_SCAN  0x{value & 0xffffffff:08x}", flush=True)
    except KeyboardInterrupt:
        print("\nwatch-input: stopped", file=sys.stderr)
        return 0
    finally:
        for fd in fds:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
