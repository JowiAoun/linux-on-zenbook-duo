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


def hidiocgfeature(length):
    # _IOC(_IOC_READ | _IOC_WRITE, 'H', 0x07, length)
    ioc_write, ioc_read = 1, 2
    return ((ioc_read | ioc_write) << 30) | (length << 16) | (ord("H") << 8) | 0x07


def declared_feature_size(node, report_id):
    """Total bytes (id included) of a declared FEATURE report, or None.

    Walks the interface's HID report descriptor. Only the global items that
    matter here are tracked — report id, size and count — which is enough to
    size a feature report without pulling in a full HID parser.
    """
    path = f"/sys/class/hidraw/{os.path.basename(node)}/device/report_descriptor"
    try:
        with open(path, "rb") as f:
            desc = f.read()
    except OSError:
        return None
    i = rid = rsize = rcount = 0
    while i < len(desc):
        prefix = desc[i]
        size = prefix & 3
        size = 4 if size == 3 else size
        tag, typ = prefix >> 4, (prefix >> 2) & 3
        value = int.from_bytes(desc[i + 1:i + 1 + size], "little") if size else 0
        if typ == 1 and tag == 8:      # Global: Report ID
            rid = value
        elif typ == 1 and tag == 7:    # Global: Report Size
            rsize = value
        elif typ == 1 and tag == 9:    # Global: Report Count
            rcount = value
        elif typ == 0 and tag == 11 and rid == report_id:   # Main: Feature
            return 1 + rsize * rcount // 8
        i += 1 + size
    return None


def vendor_nodes():
    """(node, declared size) for interfaces owning the ASUS vendor collection.

    The keyboard exposes six hidraw interfaces and several of them will happily
    ACCEPT a feature write that does nothing at all — so "the first node that
    didn't return an error" is not a way to find the right one. Only the vendor
    interface declares feature report 0x5a, which makes that a deterministic
    test, and unlike the node names it does not change when the device
    re-enumerates. (Docking twice renumbers /dev/hidrawN, and those names sort
    as strings — hidraw16 before hidraw5 — so picking by order silently moved
    to a different interface on nearly every dock.)

    Empty over transports whose descriptor does not declare it; callers should
    fall back to trying every interface there.
    """
    for node in keyboard_hidraw_nodes():
        size = declared_feature_size(node, REPORT_IDS[0])
        if size:
            yield node, size


def candidate_sizes(node):
    """Report lengths to try for 0x5a, best guess first.

    The declared size is the principled answer, but this keyboard's USB vendor
    interface declares 16 and then STALLs a 16-byte SET_FEATURE while accepting
    17 — so the descriptor is a starting point, not the last word. 16 is
    mainline hid-asus's size and stays in the list for the Bluetooth transport,
    where it is what works. Nothing larger: 64 bytes makes the device time out
    for seconds, which would stall the whole daemon.
    """
    sizes = []
    declared = declared_feature_size(node, REPORT_IDS[0])
    for n in (declared, 17, 16):
        if n and n not in sizes:
            sizes.append(n)
    return sizes


def hotkey_mode_confirmed(fd, size):
    """True when the device echoes the handshake back on report 0x5a.

    This is the only trustworthy signal that the ASUS init actually landed.
    Without it `send_handshake` could only report "some interface accepted some
    bytes", which on this keyboard is routinely true of interfaces that have
    nothing to do with the media layer — the exact reason the Fn keys could be
    dead while the log claimed success.
    """
    buf = bytearray(size)
    buf[0] = REPORT_IDS[0]
    try:
        fcntl.ioctl(fd, hidiocgfeature(size), buf)
    except OSError:
        return False
    return buf[0] == REPORT_IDS[0] and bytes(buf[1:len(HANDSHAKE_TAIL) + 1]) == bytes(HANDSHAKE_TAIL)


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


def send_handshake(hint=True):
    nodes = list(keyboard_hidraw_nodes())
    if not nodes:
        print("kb_init: keyboard 0b05:1b2c not found on hidraw (docked?)", file=sys.stderr)
        return 1

    # Send the handshake to EVERY interface, not just the first that accepts it.
    # hid-asus targets the interface that carries the ASUS vendor collection
    # (on this keyboard that is a later hidraw node, not the main keyboard one),
    # so we must not stop early or the media layer never switches on.
    denied = False
    confirmed = []
    for node in nodes:
        try:
            fd = os.open(node, os.O_RDWR)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        try:
            size = None
            for candidate in candidate_sizes(node):
                report = bytearray(candidate)
                report[0] = REPORT_IDS[0]
                report[1:len(HANDSHAKE_TAIL) + 1] = bytes(HANDSHAKE_TAIL)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(candidate), bytes(report))
                except OSError:
                    continue  # wrong length for this interface — try the next
                if hotkey_mode_confirmed(fd, candidate):
                    size = candidate
                    break
            if size is None:
                continue  # not the vendor interface, or it never took the init
            # Only now, on the interface that demonstrably owns the ASUS vendor
            # collection, is it worth sending the rest — padded to the length
            # this interface just proved it wants.
            for report_id in REPORT_IDS[1:]:
                report = bytearray(size)
                report[0] = report_id
                report[1:len(HANDSHAKE_TAIL) + 1] = bytes(HANDSHAKE_TAIL)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(size), bytes(report))
                except OSError:
                    pass  # this interface doesn't own this report id — expected
            oobe_ok = 0
            for seq in OOBE_SEQUENCE:
                report = bytearray(size)
                report[:len(seq)] = bytes(seq)
                try:
                    fcntl.ioctl(fd, hidiocsfeature(size), bytes(report))
                    oobe_ok += 1
                except OSError:
                    pass
            confirmed.append(node)
            print(f"kb_init: {node}: hotkey mode CONFIRMED (report 0x5a, {size} bytes); "
                  f"oobe-disable {oobe_ok}/{len(OOBE_SEQUENCE)}")
        finally:
            os.close(fd)

    if confirmed:
        if hint:
            print("kb_init: the keyboard echoed the handshake back — the media layer is on. "
                  "Press Fn+F5 etc. and watch `duo fn-probe` / `duo watch-input`.")
        return 0
    if denied:
        print("kb_init: permission denied on hidraw — run with sudo, or install the "
              "udev rule (sudo make system HOST=zenbook-duo).", file=sys.stderr)
        return 13
    # Deliberately a failure even though other interfaces may have swallowed the
    # bytes happily: "some interface accepted something" is what let the media
    # layer stay dead while every log line claimed success.
    print("kb_init: no interface confirmed hotkey mode — the media keys will not work. "
          "Re-run attached over USB, or share `duo doctor` output.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(send_handshake())
