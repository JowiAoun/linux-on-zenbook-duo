#!/usr/bin/env bash
# 00-preflight.sh — read-only sanity checks before anything is changed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

model="$(dmi_product)"
if is_duo_hardware; then
  log "hardware: ASUS ${model}"
else
  if [ "${ZENDUO_FORCE:-0}" = 1 ]; then
    warn "this is not a Zenbook Duo (DMI: '${model:-unknown}') — continuing because --force was given"
  else
    die "this is not a Zenbook Duo (DMI product: '${model:-unknown}'). The udev, sudoers and GRUB pieces are for that hardware only. Re-run with --force if you know better."
  fi
fi

log "distro: $(distro_id) $(distro_version)   package manager: $(pkg_manager)   kernel: $(uname -r)"
case "$(pkg_manager)" in
  none) warn "no supported package manager — packages will be listed, not installed" ;;
esac

# A live-USB session has an overlay root: nothing done here would persist.
# Use `duo doctor` from the live session instead — it is read-only.
if grep -qE 'casper|/cow |/rofs ' /proc/mounts; then
  die "live-USB session detected — install on the installed OS only ('duo doctor' works here and is read-only)"
fi

if [ ! -d /sys/firmware/efi ]; then
  warn "not booted via UEFI — unexpected on this machine"
fi

if command -v fuser >/dev/null 2>&1 && fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
  die "another package manager holds the apt/dpkg lock — retry after it finishes"
fi

# Sanity-check the source tree we are about to install from.
for f in bin/duo helper/zenduo-helper lib/displayctl.py lib/watch_displays.py lib/watch_fn.py; do
  [ -f "$ZENDUO_SRC/$f" ] || die "missing $ZENDUO_SRC/$f — incomplete checkout?"
done

log "preflight OK"
