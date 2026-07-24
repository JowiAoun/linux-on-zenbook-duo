#!/usr/bin/env bash
# shellcheck disable=SC2034  # GRUB_CHANGED/CHANGES are read by sourcing scripts
# system/lib.sh — shared helpers for the dome system layer.
# Sourced by every system/*.sh script; not executable on its own.
#
# Conventions:
#   - Every script is idempotent: a second run reports "no changes".
#   - DRY_RUN=1 prints what would change without changing anything.
#   - HOST env (or user-config.nix's hostProfile) selects the host profile.

set -euo pipefail

DOME_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"
GRUB_FILE="${GRUB_FILE:-/etc/default/grub}"
GRUB_CHANGED=0
CHANGES=0

log()  { printf '\033[1;34m[dome]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dome:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[dome:fail]\033[0m %s\n' "$*" >&2; exit 1; }

mark_change() { CHANGES=$((CHANGES + 1)); }

# Run a state-changing command, honoring DRY_RUN=1.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN: $*"
  else
    "$@"
  fi
  mark_change
}

require_root() {
  [ "$(id -u)" = 0 ] || die "must run as root (use: sudo make system)"
}

# Host profile resolution: HOST env > user-config.nix hostProfile > generic.
host_profile() {
  if [ -n "${HOST:-}" ]; then
    echo "$HOST"
    return
  fi
  if [ -f "$DOME_ROOT/user-config.nix" ]; then
    local p
    p="$(sed -nE 's/.*hostProfile *= *"([^"]+)".*/\1/p' "$DOME_ROOT/user-config.nix" | head -n1)"
    if [ -n "$p" ]; then
      echo "$p"
      return
    fi
  fi
  echo generic
}

is_duo_host() { [ "$(host_profile)" = zenbook-duo ]; }

# True iff user-config.nix sets `<key> = true;`. The bridge from the Nix-side
# config to the root layer, for switches the system layer has to honor
# (dockerEngine, dockerDesktop). Missing file or missing key => false, so an
# older user-config.nix never trips a new toggle.
#
# Read from the file rather than from the environment: `FOO=1 sudo make system`
# silently loses FOO to sudo's env_reset, so an env-var-only switch would be a
# preview-that-modifies trap all over again.
config_flag() {
  [ -f "$DOME_ROOT/user-config.nix" ] || return 1
  local v
  v="$(sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*(true|false);.*/\1/p" \
        "$DOME_ROOT/user-config.nix" | head -n1)"
  [ "$v" = true ]
}

# The value of a quoted string field in user-config.nix, or empty. Same
# read-the-file-not-the-environment reasoning as config_flag.
config_str() {
  [ -f "$DOME_ROOT/user-config.nix" ] || return 0
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"([^\"]*)\";.*/\1/p" \
    "$DOME_ROOT/user-config.nix" | head -n1
}

# The human user the duo tooling belongs to:
# user-config.nix username > the user who invoked sudo > failure.
target_user() {
  local u=""
  if [ -f "$DOME_ROOT/user-config.nix" ]; then
    u="$(sed -nE 's/.*username *= *"([^"]+)".*/\1/p' "$DOME_ROOT/user-config.nix" | head -n1)"
  fi
  if [ -z "$u" ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    u="$SUDO_USER"
  fi
  [ -n "$u" ] || return 1
  echo "$u"
}

# True iff the package is in dpkg state "install ok installed".
# NOT `dpkg -s`: that exits 0 for any package dpkg still knows about, including
# "deinstall ok config-files" (removed but not purged — where `apt remove` leaves
# anything with conffiles). Such a package would be reported present forever and
# never reinstalled, quietly breaking the self-healing idempotency contract.
pkg_installed() {
  [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = installed ]
}

# apt install, only for packages not already installed.
ensure_pkg() {
  local missing=()
  local p
  for p in "$@"; do
    pkg_installed "$p" || missing+=("$p")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    log "packages already present: $*"
  else
    log "installing: ${missing[*]}"
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  fi
}

# apt-get update, hiding routine per-mirror chatter (the Ign/Hit/Err/W lines for
# a single unreachable mirror). Rationale: if AT LEAST ONE repository refreshed,
# the cached package lists are usable and the other mirrors' failures are noise.
# Only when NOTHING could be reached (a real connectivity problem) do we surface
# the reasons. Missing packages that truly can't be fetched still fail loudly in
# ensure_pkg's install step, so genuine errors are never hidden.
apt_update() {
  if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN: apt-get update"
    return 0
  fi
  local out
  out="$(apt-get update 2>&1)" || true
  if out_matches "$out" -E '^(Hit|Get):'; then
    log "apt package lists refreshed"
  else
    warn "apt-get update could not reach any repository:"
    printf '%s\n' "$out" | grep -E '^(Err|E:|W:)' | sed 's/^/    /' >&2 || true
  fi
}

# True iff <text> contains a line matching the grep expression that follows.
#
#   out_matches "$out" -E '^(Hit|Get):'
#   out_matches "$groups" -x docker
#   out_matches "$state" -i 'SecureBoot enabled'
#
# Use this instead of `cmd | grep -q ...`. This file sets `pipefail`, and
# `grep -q` exits at the FIRST match — which can SIGPIPE a writer that still has
# output to produce, so the pipeline returns 141 and a SUCCESSFUL match is
# reported as a failure. It is a race against the writer's buffering, not a size
# threshold: `apt-cache policy <pkg>` prints six lines and still loses it, which
# is how a published package came to read as "not published here" in both
# 25-memory.sh and 20-kernel.sh. Measured:
#
#   $ bash -c 'set -euo pipefail; dpkg -l | grep -q "^ii"'; echo $?
#   141
#
# Capturing first and matching here is immune: bash backs a herestring with a
# temp file, so there is no writer left for grep to hang up on.
out_matches() { # <text> <grep-arg...>
  local text="$1"
  shift
  grep -q "$@" <<<"$text"
}

# Install a generated config file iff its content differs.
#
# Returns 0 ("true") when it wrote, 1 when the file was already correct, so a
# caller can pay for a reload only when one is needed:
#
#   if install_conf "$path" "$body"; then systemctl daemon-reload; fi
#
# ALWAYS call it in a conditional context — a bare call returning 1 would abort
# the script under `set -e`. Parent directories are created; mode is 0644
# root:root. Anything wanting different ownership, a validation step before the
# file lands, or a "did dome write this?" marker check should still hand-roll it
# (see 85-apparmor-userns.sh and 55-touchpad-quirks.sh).
install_conf() { # <path> <content>
  local path="$1" body="$2" tmp
  if [ -f "$path" ] && [ "$(cat "$path")" = "$body" ]; then
    log "up to date: $path"
    return 1
  fi
  if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN: would write $path"
    mark_change
    return 0
  fi
  log "writing $path"
  install -d -o root -g root -m 0755 "$(dirname "$path")"
  tmp="$(mktemp)"
  printf '%s\n' "$body" > "$tmp"
  install -o root -g root -m 0644 "$tmp" "$path"
  rm -f "$tmp"
  mark_change
  return 0
}

# Append a line to a file iff it isn't there verbatim.
ensure_line() {
  local file="$1" line="$2"
  if [ -f "$file" ] && grep -qxF "$line" "$file"; then
    log "already in $file: $line"
  else
    log "adding to $file: $line"
    if [ "$DRY_RUN" = 1 ]; then
      log "DRY RUN: would append"
    else
      printf '%s\n' "$line" >> "$file"
    fi
    mark_change
  fi
}

# Add a kernel parameter to GRUB_CMDLINE_LINUX_DEFAULT iff absent.
# Sets GRUB_CHANGED=1; the caller decides when to run update-grub (once).
ensure_grub_param() {
  local param="$1" current
  current="$(sed -nE 's/^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"/\1/p' "$GRUB_FILE" | head -n1)"
  case " $current " in
    *" $param "*)
      log "GRUB param already present: $param"
      return 0
      ;;
  esac
  log "adding GRUB param: $param"
  if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN: would edit GRUB_CMDLINE_LINUX_DEFAULT in $GRUB_FILE"
  else
    sed -i -E "s/^(GRUB_CMDLINE_LINUX_DEFAULT=\")(.*)(\")/\1\2 ${param}\3/" "$GRUB_FILE"
    sed -i -E 's/^(GRUB_CMDLINE_LINUX_DEFAULT=)" /\1"/' "$GRUB_FILE"
  fi
  GRUB_CHANGED=1
  mark_change
}

# Set (or uncomment+set) a KEY=value entry in /etc/default/grub iff needed.
ensure_grub_kv() {
  local key="$1" value="$2"
  if grep -qE "^${key}=${value}\$" "$GRUB_FILE"; then
    log "already set: ${key}=${value}"
    return 0
  fi
  log "setting ${key}=${value}"
  if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN: would set ${key}=${value} in $GRUB_FILE"
  else
    if grep -qE "^#?${key}=" "$GRUB_FILE"; then
      sed -i -E "s|^#?${key}=.*|${key}=${value}|" "$GRUB_FILE"
    else
      printf '%s=%s\n' "$key" "$value" >> "$GRUB_FILE"
    fi
  fi
  GRUB_CHANGED=1
  mark_change
}
