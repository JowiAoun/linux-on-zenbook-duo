#!/usr/bin/env bash
# 20-kernel.sh — kernel policy (PLAN.md D7):
#   - HWE stack (6.17 on 24.04.4) as the daily kernel
#   - GA kernel (6.8) kept installed forever as the GRUB escape hatch,
#     because this machine's second panel has been broken by kernel
#     regressions before (i915 6.9-line, PLAN.md V9).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

ensure_pkg linux-generic-hwe-24.04
ensure_pkg linux-generic

log "kernels ensured: HWE (daily) + GA (fallback via GRUB > Advanced options)"
