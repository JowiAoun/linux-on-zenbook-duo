#!/usr/bin/env bash
# 55-touchpad.sh — libinput palm-rejection quirk for the detachable touchpad.
#
# The Duo's touchpad and keyboard are ONE external USB combo device. libinput's
# disable-while-typing normally applies only to INTERNAL touchpads, so an
# external combo touchpad stays live while you type — a resting palm then
# clicks/selects/deletes by accident. Declaring the combo layout (touchpad below
# the keyboard) makes libinput treat it like an internal one, so
# disable-while-typing applies. Quirk from alesya-h/zenbook-duo-2024-ux8406ma-linux.
#
# The other half is the desktop's own DWT switch (on by default in GNOME;
# `gsettings set org.gnome.desktop.peripherals.touchpad disable-while-typing true`).
# Switch: --no-palm-rejection (ZENDUO_PALM_REJECTION=0). Default on.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

QUIRKS_DST=/etc/libinput/local-overrides.quirks
# Both markers are ours: "dome" is what the file was called before this repo
# was split out of JowiAoun/dome, and machines provisioned then still carry it.
MARKER_RE='^# (zenduo|dome) — palm rejection for the ASUS Zenbook Duo'

read -r -d '' QUIRKS <<'EOF_QUIRKS' || true
# zenduo — palm rejection for the ASUS Zenbook Duo detachable touchpad.
#
# The touchpad and keyboard are one external USB combo device; libinput's
# disable-while-typing only covers internal touchpads unless a quirk says the
# touchpad sits below the keyboard. With this, DWT applies and a resting palm
# can't click/select while typing. Source: alesya-h/zenbook-duo-2024-ux8406ma-linux.
[ASUS Zenbook Duo Keyboard Touchpad]
MatchUdevType=touchpad
MatchVendor=0x0B05
MatchName=*ASUS Zenbook Duo Keyboard Touchpad
AttrTPKComboLayout=below
EOF_QUIRKS

if ! feature_on PALM_REJECTION 1; then
  if [ -e "$QUIRKS_DST" ] && grep -qE "$MARKER_RE" "$QUIRKS_DST"; then
    log "palm rejection disabled — removing $QUIRKS_DST"
    run rm -f "$QUIRKS_DST"
  else
    log "palm rejection disabled (--no-palm-rejection)"
  fi
  exit 0
fi

# libinput reads exactly ONE local-override file. Don't clobber a pre-existing
# one that we didn't write — the user may keep their own quirks there.
if [ -e "$QUIRKS_DST" ] && ! grep -qE "$MARKER_RE" "$QUIRKS_DST"; then
  warn "$QUIRKS_DST exists and isn't zenduo-managed — leaving it. Add this by hand:"
  printf '%s\n' "$QUIRKS" | sed 's/^/    /' >&2
  exit 0
fi

if install_conf "$QUIRKS_DST" "$QUIRKS"; then
  log "re-plug the keyboard (or reboot) for libinput to re-read the quirk"
fi
