#!/usr/bin/env python3
"""Raw HID report capture for the ASUS Zenbook Duo keyboard (0b05:1b2c).

The media/Fn-row keys (brightness, volume, keyboard backlight, …) are ASUS
vendor usages that hid-generic does not translate into input events (and
hid_asus has no entry for this device — PLAN.md V8). So they emit nothing the
input layer sees; the only place their signal appears is the raw hidraw stream.

This reads every hidraw node belonging to the keyboard and prints each report as
hex. Press one media key at a time and note which line it produced — that map
becomes the lookup table for a `duo watch-fn` remap daemon (brightness → backlight
sysfs, volume → wpctl/pactl, kb backlight → duo kb-backlight, …).

Unprivileged access needs the udev uaccess rule (system/45-duo-udev.sh); if a
node can't be opened, re-run after `sudo make system HOST=zenbook-duo`, or sudo.
Exit: 0 stopped by user · 1 no device / nothing readable.
"""

import glob
import os
import select
import sys

VID = "0B05"
PID = "1B2C"


def all_hidraw_devices():
    """[(node, hid_id, name), ...] for every hidraw device present."""
    out = []
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        fields = {}
        try:
            with open(uevent) as f:
                for line in f.read().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        fields[k] = v
        except OSError:
            continue
        out.append(("/dev/" + uevent.split("/")[4],
                    fields.get("HID_ID", "?"), fields.get("HID_NAME", "?")))
    return out


def keyboard_hidraw_nodes():
    # USB enumerates as 0003:00000B05:00001B2C, but detached the same keyboard
    # re-enumerates on the Bluetooth bus (0005) with whatever ids/name BT
    # advertises — so match the ASUS vendor id on ANY bus, or the model name.
    nodes = []
    for node, hid_id, name in all_hidraw_devices():
        blob = f"{hid_id} {name}".upper()
        if f":0000{VID}:" in blob or "ZENBOOK DUO" in blob:
            nodes.append(node)
    return nodes


def main():
    nodes = keyboard_hidraw_nodes()
    if not nodes:
        print("fn_probe: Zenbook Duo keyboard not found on hidraw (USB or BT).", file=sys.stderr)
        devs = all_hidraw_devices()
        if devs:
            print("fn_probe: hidraw devices present (share this if the keyboard IS connected):",
                  file=sys.stderr)
            for node, hid_id, name in devs:
                print(f"  {node}  {hid_id}  {name}", file=sys.stderr)
        return 1

    fds = {}
    denied = False
    for n in nodes:
        try:
            fds[os.open(n, os.O_RDONLY | os.O_NONBLOCK)] = n
        except PermissionError:
            denied = True
        except OSError:
            pass
    if not fds:
        msg = "fn_probe: could not open any hidraw node"
        if denied:
            msg += " (permission denied — run 'sudo make system HOST=zenbook-duo' for the udev rule, or use sudo)"
        print(msg, file=sys.stderr)
        return 1

    print(f"fn_probe: reading {', '.join(sorted(fds.values()))}", file=sys.stderr)
    print("fn_probe: press ONE media/Fn key at a time; note key -> line. Ctrl-C to stop.\n", file=sys.stderr)
    try:
        while True:
            ready, _, _ = select.select(list(fds), [], [], None)
            for fd in ready:
                try:
                    data = os.read(fd, 64)
                except OSError:
                    continue
                if data:
                    hexs = " ".join(f"{b:02x}" for b in data)
                    print(f"{os.path.basename(fds[fd])}: {hexs}", flush=True)
    except KeyboardInterrupt:
        print("\nfn_probe: stopped", file=sys.stderr)
        return 0
    finally:
        for fd in fds:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
