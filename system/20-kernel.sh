#!/usr/bin/env bash
# 20-kernel.sh — kernel policy on Ubuntu LTS (skipped elsewhere):
#   - the HWE stack as the daily kernel (a Duo needs >= 6.11: below that,
#     detaching the keyboard sends a spurious rfkill press that kills Wi-Fi,
#     and the second panel has been broken by i915 regressions before)
#   - the GA kernel kept installed as the GRUB escape hatch, because this
#     machine's second panel HAS been broken by kernel regressions before.
# Switch: --no-hwe-kernel (ZENDUO_HWE_KERNEL=0). Default on for Ubuntu.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

# Running-kernel advice applies to every distro, so do it before the gate.
kver="$(uname -r | cut -d- -f1)"
kmaj="${kver%%.*}"; krest="${kver#*.}"; kmin="${krest%%.*}"
if [ "${kmaj:-0}" -lt 6 ] || { [ "${kmaj:-0}" -eq 6 ] && [ "${kmin:-0}" -lt 11 ]; }; then
  warn "running kernel $kver is older than 6.11 — keyboard detach will drop Wi-Fi (asus-wmi quirk landed in 6.11). Move to a newer kernel."
fi

if [ "$(distro_id)" != ubuntu ]; then
  log "not Ubuntu — kernel policy is yours (needs >= 6.11; newer is better for this hardware)"
  exit 0
fi
if ! feature_on HWE_KERNEL 1; then
  log "HWE kernel policy disabled (--no-hwe-kernel)"
  exit 0
fi

# The HWE metapackage is named for the release it backports INTO, so it is
# derived from the running release rather than hardcoded.
. /etc/os-release
HWE="linux-generic-hwe-${VERSION_ID:-24.04}"

# "Published" takes two signals: an installed metapackage is self-evidently
# published, and otherwise apt's Candidate must be a real version (apt prints a
# stanza for dropped packages too, with `Candidate: (none)`). The policy output
# is captured, not piped into grep -q — see lib.sh.
hwe_available() {
  if pkg_installed "$HWE"; then
    return 0
  fi
  local policy
  policy="$(apt-cache policy "$HWE" 2>/dev/null || true)"
  out_matches "$policy" -E '^[[:space:]]+Candidate: [^([:space:]]'
}

if ! hwe_available; then apt_update; fi

if hwe_available; then
  ensure_pkg "$HWE"
else
  warn "$HWE is not published — no HWE stack for Ubuntu ${VERSION_ID:-unknown} yet (a fresh LTS ships its newest kernel as GA)"
  warn "  re-run the installer after the first point release to pick it up"
fi

ensure_pkg linux-generic

log "kernels ensured: HWE (daily) + GA (fallback via GRUB > Advanced options)"
