#!/usr/bin/env bash
# system/run.sh — the root half of the install, in order. Normally invoked by
# ./install.sh; run directly for a re-apply or a preview:
#
#   sudo bash system/run.sh                 # apply (idempotent)
#   sudo bash system/run.sh --dry-run       # preview only, changes nothing
#   sudo bash system/run.sh --no-psr-fix    # any install.sh feature flag works here
#
# Use the FLAGS, not `DRY_RUN=1 sudo ...`: sudo's default env_reset strips
# environment variables set in front of it, so the variable never reaches this
# script and a "preview" would really modify the system.
#
# Order: 00 preflight (read-only) → 10 packages → 20 kernel → 30 GRUB →
#        40 the duo CLI → 45 udev → 46 speaker-amp check → 50 root helper +
#        sudoers → 55 touchpad quirk.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

usage_text() {
  cat <<'USAGE'
usage: run.sh [--dry-run] [--force] [--dev] [--prefix DIR] [--user NAME]
              [--hwe-kernel|--no-hwe-kernel] [--no-psr-fix] [--no-palm-rejection]
              [--no-amp-check]
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)           DRY_RUN=1 ;;
    --force)             ZENDUO_FORCE=1 ;;
    --dev)               ZENDUO_DEV=1 ;;
    --prefix)            [ $# -ge 2 ] || die "--prefix needs a directory"; ZENDUO_PREFIX="$2"; shift ;;
    --user)              [ $# -ge 2 ] || die "--user needs a username"; ZENDUO_TARGET_USER="$2"; shift ;;
    --hwe-kernel)        ZENDUO_HWE_KERNEL=1 ;;
    --no-hwe-kernel)     ZENDUO_HWE_KERNEL=0 ;;
    --psr-fix)           ZENDUO_PSR_FIX=1 ;;
    --no-psr-fix)        ZENDUO_PSR_FIX=0 ;;
    --palm-rejection)    ZENDUO_PALM_REJECTION=1 ;;
    --no-palm-rejection) ZENDUO_PALM_REJECTION=0 ;;
    --amp-check)         ZENDUO_AMP_CHECK=1 ;;
    --no-amp-check)      ZENDUO_AMP_CHECK=0 ;;
    -h|--help)           usage_text; exit 0 ;;
    *) die "unknown argument: $1 ($(usage_text))" ;;
  esac
  shift
done

export DRY_RUN ZENDUO_SRC ZENDUO_PREFIX
export ZENDUO_FORCE="${ZENDUO_FORCE:-0}" ZENDUO_DEV="${ZENDUO_DEV:-0}"
export ZENDUO_TARGET_USER="${ZENDUO_TARGET_USER:-}"
export ZENDUO_HWE_KERNEL="${ZENDUO_HWE_KERNEL:-}" ZENDUO_PSR_FIX="${ZENDUO_PSR_FIX:-}"
export ZENDUO_PALM_REJECTION="${ZENDUO_PALM_REJECTION:-}" ZENDUO_AMP_CHECK="${ZENDUO_AMP_CHECK:-}"

require_root
log "zenduo $(cat "$ZENDUO_SRC/VERSION" 2>/dev/null || echo dev) — system layer   dry run: $DRY_RUN   prefix: $ZENDUO_PREFIX"

for script in 00-preflight.sh 10-packages.sh 20-kernel.sh 30-grub.sh 40-cli.sh 45-udev.sh 46-speaker-amp.sh 50-sudoers.sh 55-touchpad.sh; do
  log "── $script"
  bash "./$script"
done

log "system layer complete. If GRUB or the kernel changed, reboot to apply."
