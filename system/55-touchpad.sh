#!/usr/bin/env bash
# 55-touchpad-quirks.sh — [zenbook-duo hosts only] libinput palm-rejection quirk
# for the detachable touchpad.
#
# The Duo's touchpad and keyboard are ONE external USB combo device. libinput's
# disable-while-typing normally applies only to INTERNAL touchpads, so an
# external combo touchpad stays live while you type — a resting palm then
# clicks/selects/deletes by accident. Declaring the combo layout (touchpad below
# the keyboard) makes libinput treat it like an internal one, so
# disable-while-typing applies. Quirk from alesya-h/zenbook-duo-2024-ux8406ma-linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

QUIRKS_DST=/etc/libinput/local-overrides.quirks
MARKER="# dome — palm rejection for the ASUS Zenbook Duo"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<'EOF'
# dome — palm rejection for the ASUS Zenbook Duo detachable touchpad.
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
EOF

# libinput reads exactly ONE local-override file. Don't clobber a pre-existing
# one that dome didn't write — the user may keep their own quirks there.
if [ -e "$QUIRKS_DST" ] && ! grep -qF "$MARKER" "$QUIRKS_DST"; then
  warn "$QUIRKS_DST exists and isn't dome-managed — leaving it. Add this by hand:"
  sed 's/^/    /' "$tmp" >&2
  exit 0
fi

if cmp -s "$tmp" "$QUIRKS_DST" 2>/dev/null; then
  log "libinput quirks up to date: $QUIRKS_DST"
else
  log "installing $QUIRKS_DST"
  run install -D -o root -g root -m 0644 "$tmp" "$QUIRKS_DST"
  log "re-plug the keyboard (or reboot) for libinput to re-read the quirk"
fi
