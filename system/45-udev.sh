#!/usr/bin/env bash
# 45-duo-udev.sh — [zenbook-duo hosts only] udev rules so the zenduo
# tooling can run unprivileged:
#   - hidraw access (uaccess ACL for the logged-in user) to the detachable
#     keyboard 0b05:1b2c — used by the kb-backlight HID fallback
#   - group-writable native kbd-backlight LED node, if/when the kernel
#     grows one for this device (PLAN.md V8)
#
# Note: these are permission-only rules. Display toggling deliberately does
# NOT react to udev add/remove events (event-storm hazard, PLAN.md V14) —
# the watcher polls sysfs instead.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

RULES_DST=/etc/udev/rules.d/70-zenduo.rules
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<'EOF'
# zenduo (dome) — permissions for the ASUS Zenbook Duo detachable keyboard.
# hidraw node: allow the active seat user to send HID feature reports
# (keyboard backlight fallback) without root.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0b05", ATTRS{idProduct}=="1b2c", TAG+="uaccess"
# Native keyboard-backlight LED (absent on current kernels; harmless if unmatched).
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="asus::kbd_backlight", RUN+="/bin/chmod 0666 /sys%p/brightness"
EOF

if cmp -s "$tmp" "$RULES_DST" 2>/dev/null; then
  log "udev rules up to date: $RULES_DST"
else
  log "installing $RULES_DST"
  run install -o root -g root -m 0644 "$tmp" "$RULES_DST"
  if [ "$DRY_RUN" != 1 ]; then
    udevadm control --reload
    udevadm trigger --subsystem-match=hidraw || true
  fi
fi
