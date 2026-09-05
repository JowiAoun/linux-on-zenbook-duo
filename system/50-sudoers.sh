#!/usr/bin/env bash
# 50-sudoers.sh — installs the zenduo root helper and its sudoers rule.
#
# The helper ($PREFIX/sbin/zenduo-helper) is the ONLY thing granted NOPASSWD,
# and it validates its input to two verbs:
#   backlight <device> <0-100>   write a backlight percentage
#   batlimit <20-100>            set the battery charge-limit threshold
# This is deliberately narrower than a "NOPASSWD /usr/bin/env" rule: the
# helper's source is 50 lines and every byte of input is checked.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

HELPER_SRC="$ZENDUO_SRC/helper/zenduo-helper"
HELPER_DST=/usr/local/sbin/zenduo-helper   # fixed: bin/duo and the sudoers rule name this path
[ -f "$HELPER_SRC" ] || die "missing $HELPER_SRC — repo incomplete?"

if cmp -s "$HELPER_SRC" "$HELPER_DST" 2>/dev/null; then
  log "helper up to date: $HELPER_DST"
else
  log "installing $HELPER_DST"
  run install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"
fi

# Grant the helper to the configured user only (not the whole sudo group).
DUO_USER="$(target_user)" || die "cannot determine the target user — run via sudo from your own account, or pass --user NAME"
id "$DUO_USER" >/dev/null 2>&1 || die "user '$DUO_USER' does not exist on this machine"

SUDOERS_DST=/etc/sudoers.d/zenduo
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$DUO_USER ALL=(root) NOPASSWD: $HELPER_DST" > "$tmp"

visudo -c -f "$tmp" >/dev/null || die "generated sudoers rule failed validation — not installing"

if cmp -s "$tmp" "$SUDOERS_DST" 2>/dev/null; then
  log "sudoers rule up to date: $SUDOERS_DST"
else
  log "installing $SUDOERS_DST (for $DUO_USER)"
  run install -o root -g root -m 0440 "$tmp" "$SUDOERS_DST"
fi
