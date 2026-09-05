#!/usr/bin/env bash
# 45-udev.sh — udev rules so the duo tooling can run unprivileged:
#   - hidraw access (uaccess ACL for the logged-in user) to the detachable
#     keyboard — USB 0b05:1b2c AND Bluetooth 0b05:1b2d (same keyboard,
#     different product id per transport) — used by kb-backlight/kb-init/fn-*
#   - group-writable native kbd-backlight LED node, if/when the kernel grows
#     one for this device (see docs/HARDWARE.md, V8)
#
# Note: these are permission-only rules. Display toggling deliberately does
# NOT react to udev add/remove events (event-storm hazard, V14) — the watcher
# polls sysfs instead.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

RULES_DST=/etc/udev/rules.d/70-zenduo.rules
read -r -d '' RULES <<'EOF_RULES' || true
# zenduo — permissions for the ASUS Zenbook Duo detachable keyboard.
# hidraw nodes: allow the active seat user to read reports / send HID feature
# reports (kb-backlight, kb-init, fn-probe/fn-map) without root.
# Match the parent HID device's kernel name (BUS:VID:PID.instance), which works
# for both transports — USB attributes like idVendor don't exist on Bluetooth.
#   USB:       0003:0B05:1B2C.*   Bluetooth: 0005:0B05:1B2D.*
SUBSYSTEM=="hidraw", KERNELS=="0003:0B05:1B2C.*", TAG+="uaccess"
SUBSYSTEM=="hidraw", KERNELS=="0005:0B05:1B2D.*", TAG+="uaccess"
# Native keyboard-backlight LED (absent on current kernels; harmless if unmatched).
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="asus::kbd_backlight", RUN+="/bin/chmod 0666 /sys%p/brightness"
EOF_RULES

if install_conf "$RULES_DST" "$RULES"; then
  if [ "$DRY_RUN" != 1 ]; then
    udevadm control --reload
    udevadm trigger --subsystem-match=hidraw || true
  fi
fi
