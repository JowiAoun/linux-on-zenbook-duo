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
# "Published" takes two signals, not one:
#   - pkg_installed: a kernel the machine may be booted on RIGHT NOW is
#     self-evidently published — never warn that it "isn't available".
#   - apt-cache policy Candidate: matched as `[^([:space:]]`, not mere presence,
#     because apt prints a stanza for virtual/dropped packages too, with
#     `Candidate: (none)`.
# apt-cache policy ALSO reads (none) when the package lists are stale or a mirror
# was unreachable during 10-apt-base's `apt-get update` — which is how a
# published (even the running) kernel gets misreported as "not published yet".
# So if the first look comes up empty, refresh the lists once and look again
# before concluding the stack is genuinely absent.
#
# The policy output is captured into a variable rather than piped into
# `grep -q`. lib.sh sets pipefail, and `grep -q` exits at the first match — which
# SIGPIPEs apt-cache while it still has the version table to write, so the
# pipeline returns 141 and a published kernel reads as absent. It has never
# fired here only because pkg_installed short-circuits on a machine that already
# has the HWE stack; on a fresh one it would silently leave you on GA.
hwe_available() {
  if pkg_installed "$HWE"; then
    return 0
  fi
  local policy
  policy="$(apt-cache policy "$HWE" 2>/dev/null || true)"
  grep -qE '^[[:space:]]+Candidate: [^([:space:]]' <<<"$policy"
}

if ! hwe_available; then apt_update; fi

if hwe_available; then
  ensure_pkg "$HWE"
else
  warn "$HWE is not published — no HWE stack for Ubuntu ${VERSION_ID:-unknown} yet"
  warn "  (if a mirror was unreachable above, the lists may simply be stale)"
  warn "  staying on the GA kernel, which on a fresh LTS is the newest one anyway"
  warn "  re-run 'sudo make system' after the first point release to pick it up"
fi

ensure_pkg linux-generic

log "kernels ensured: HWE (daily) + GA (fallback via GRUB > Advanced options)"
