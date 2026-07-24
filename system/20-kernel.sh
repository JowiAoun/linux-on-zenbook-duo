#!/usr/bin/env bash
# 20-kernel.sh — kernel policy (PLAN.md D7):
#   - HWE stack (7.0 on 24.04.4) as the daily kernel
#   - GA kernel kept installed forever as the GRUB escape hatch, because this
#     machine's second panel has been broken by kernel regressions before
#     (i915 6.9-line, PLAN.md V9).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

# The HWE metapackage is named for the release it backports INTO, so it changes
# with the distro: linux-generic-hwe-24.04 on noble, linux-generic-hwe-26.04 on
# resolute. Derived rather than hardcoded — noble's name is still published on
# resolute, so hardcoding it would keep "working" while quietly tracking the
# wrong release's kernel series.
. /etc/os-release
HWE="linux-generic-hwe-${VERSION_ID:-24.04}"

# A brand-new LTS has no HWE stack at all: the metapackage first appears with
# the .1 point release, and until then the GA kernel IS the newest one. Check
# before installing, because ensure_pkg would let apt's "no such package" abort
# the entire system layer over a package that is only ever an optimisation.
#
# `Candidate: [^([:space:]]` and not just "is it listed": apt-cache policy also
# prints a stanza for virtual and dropped packages, with `Candidate: (none)`.
if apt-cache policy "$HWE" 2>/dev/null | grep -qE '^[[:space:]]+Candidate: [^([:space:]]'; then
  ensure_pkg "$HWE"
else
  warn "$HWE is not published — no HWE stack for Ubuntu ${VERSION_ID:-unknown} yet"
  warn "  staying on the GA kernel, which on a fresh LTS is the newest one anyway"
  warn "  re-run 'sudo make system' after the first point release to pick it up"
fi

ensure_pkg linux-generic

log "kernels ensured: HWE (daily) + GA (fallback via GRUB > Advanced options)"
