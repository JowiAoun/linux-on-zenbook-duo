#!/usr/bin/env bash
# 45-udev.sh — udev rules so the duo tooling can run unprivileged:
#   - hidraw access (uaccess ACL for the logged-in user) to the detachable
#     keyboard's vendor interface over USB (0b05:1b2c), and with --bluetooth-fn
#     to its Bluetooth node (0b05:1b2d) — used by kb-backlight/kb-init/fn-*
#   - uaccess on /dev/uinput, so watch-fn can press the brightness keys GNOME
#     49+ only handles as real key events (lib/uinput_keys.py). Same reach as
#     the hidraw grant: the user at the seat, while they are at it
#   - a world-writable native kbd-backlight LED node (any local account can
#     set the level), if/when the kernel grows one (see docs/HARDWARE.md, V8)
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
# hidraw: let the active seat user send the hotkey handshake and the backlight
# report, and read the Fn keys (kb-backlight, kb-init, watch-fn, fn-map).
# Over USB that is interface 4 only, the one with the ASUS vendor collection
# (usage page 0xff31, report 0x5a). Interface 0 is the keyboard itself and
# carries every key typed, so it stays root's (measured 2026-10-31: of the six
# interfaces only :1.4 declares report 0x5a, and :1.0 is the boot keyboard).
SUBSYSTEM=="hidraw", DEVPATH=="*:1.4/0003:0B05:1B2C.*", TAG+="uaccess"
# uinput: watch-fn presses KEY_BRIGHTNESSUP/DOWN on a virtual keyboard so GNOME
# 49+ handles the brightness keys itself (slider + OSD; see lib/uinput_keys.py).
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
# Native keyboard-backlight LED (absent on current kernels; harmless if unmatched).
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="asus::kbd_backlight", RUN+="/bin/chmod 0666 /sys%p/brightness"
EOF_RULES

# Over Bluetooth (0005:0B05:1B2D) every collection shares one hidraw node, so
# the Fn keys cannot be read without also reading everything typed. That is
# opt-in: --bluetooth-fn.
if feature_on BLUETOOTH_FN 0; then
  RULES+=$'\n'"# --bluetooth-fn: the Bluetooth keyboard's only node, typing included."
  RULES+=$'\n''SUBSYSTEM=="hidraw", KERNELS=="0005:0B05:1B2D.*", TAG+="uaccess"'
  log "Bluetooth Fn keys on: programs you run can read what is typed on the keyboard while it is on Bluetooth, by you or by another account after a user switch"
else
  log "Bluetooth Fn keys off: they work docked; --bluetooth-fn turns them on over Bluetooth too"
fi

if install_conf "$RULES_DST" "$RULES"; then
  if [ "$DRY_RUN" != 1 ]; then
    udevadm control --reload
    udevadm trigger --subsystem-match=hidraw || true
    udevadm trigger --subsystem-match=misc --sysname-match=uinput || true
    # An older rule tagged every node of the keyboard, and an ACL that is
    # already set stays until the node goes away. Clear it on every node the
    # rule no longer covers.
    udevadm settle || true
    for node in /dev/hidraw*; do
      [ -c "$node" ] || continue
      tags="$(udevadm info --query=property --property=CURRENT_TAGS --value "$node" 2>/dev/null || true)"
      case "$(readlink -f "/sys/class/hidraw/${node#/dev/}/device")" in
        */0003:0B05:1B2C.*|*/0005:0B05:1B2D.*) ;;
        *) continue ;;
      esac
      case "$tags" in *:uaccess:*) continue ;; esac
      setfacl -b "$node" 2>/dev/null && log "cleared the session's access to $node (not the vendor interface)" || true
    done
  fi
fi
