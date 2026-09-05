#!/usr/bin/env bash
# 30-grub.sh — kernel command line: i915.enable_psr=0.
#
# Panel Self Refresh causes visible flicker on both OLED panels of the Duo (it
# does on Windows too, where the ASUS driver disables it). Turning it off costs
# a little idle power and removes the flicker entirely.
# Switch: --no-psr-fix (ZENDUO_PSR_FIX=0). Default on.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

PARAM="i915.enable_psr=0"

if [ ! -f "$GRUB_FILE" ]; then
  warn "$GRUB_FILE not found (systemd-boot? another loader?) — add '$PARAM' to your kernel command line by hand"
  exit 0
fi

if feature_on PSR_FIX 1; then
  ensure_grub_param "$PARAM"
else
  log "PSR fix disabled (--no-psr-fix) — leaving the kernel command line alone"
  if grep -q "$PARAM" /proc/cmdline 2>/dev/null; then
    log "note: the running kernel still has $PARAM; remove it from $GRUB_FILE yourself if that is intended"
  fi
fi

if [ "$GRUB_CHANGED" = 1 ]; then
  log "GRUB changed — regenerating grub.cfg"
  grub_regenerate
else
  log "GRUB unchanged"
fi
