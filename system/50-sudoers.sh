#!/usr/bin/env bash
# 50-duo-sudoers.sh — [zenbook-duo hosts only] installs the zenduo root
# helper and its sudoers rule.
#
# The helper (/usr/local/sbin/zenduo-helper) is the ONLY thing granted
# NOPASSWD, and it validates its input to two verbs:
#   backlight <device> <0-100>   write a backlight percentage
#   batlimit <20-100>            set the battery charge-limit threshold
# This is deliberately narrower than upstream's "NOPASSWD /usr/bin/env"
# approach (PLAN.md §9).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

HELPER_SRC="$DOME_ROOT/duo/helper/zenduo-helper"
HELPER_DST=/usr/local/sbin/zenduo-helper
[ -f "$HELPER_SRC" ] || die "missing $HELPER_SRC — repo incomplete?"

if cmp -s "$HELPER_SRC" "$HELPER_DST" 2>/dev/null; then
  log "helper up to date: $HELPER_DST"
else
  log "installing $HELPER_DST"
  run install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"
fi

# Grant the helper to the configured user only (not the whole sudo group).
DUO_USER="$(target_user)" || die "cannot determine the target user — set environment.username in user-config.nix or run via sudo from your own account"
id "$DUO_USER" >/dev/null 2>&1 || die "user '$DUO_USER' does not exist on this machine"

SUDOERS_DST=/etc/sudoers.d/zenduo
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$DUO_USER ALL=(root) NOPASSWD: /usr/local/sbin/zenduo-helper" > "$tmp"

visudo -c -f "$tmp" >/dev/null || die "generated sudoers rule failed validation — not installing"

if cmp -s "$tmp" "$SUDOERS_DST" 2>/dev/null; then
  log "sudoers rule up to date: $SUDOERS_DST"
else
  log "installing $SUDOERS_DST"
  run install -o root -g root -m 0440 "$tmp" "$SUDOERS_DST"
fi
