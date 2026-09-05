#!/usr/bin/env bash
# shellcheck disable=SC2034  # GRUB_CHANGED/CHANGES are read by sourcing scripts
# system/lib.sh — shared helpers for the zenduo root layer.
# Sourced by every system/*.sh script; not executable on its own.
#
# Conventions:
#   - Every script is idempotent: a second run reports "no changes".
#   - DRY_RUN=1 prints what would change without changing anything.
#   - Feature switches arrive as ZENDUO_<NAME>=0/1 in the environment; install.sh
#     and system/run.sh set them from their flags. Read them with feature_on.
#
# Never write `cmd | grep -q` in these scripts. pipefail is on, and `grep -q`
# exits at the FIRST match, which SIGPIPEs a writer that still has output to
# produce — the pipeline then returns 141 and a successful match is reported as
# a failure. Capture first, then match with out_matches (below).

set -euo pipefail

ZENDUO_SRC="${ZENDUO_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ZENDUO_PREFIX="${ZENDUO_PREFIX:-/usr/local}"
DRY_RUN="${DRY_RUN:-0}"
GRUB_FILE="${GRUB_FILE:-/etc/default/grub}"
GRUB_CHANGED=0
CHANGES=0

log()  { printf '\033[1;34m[zenduo]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[zenduo:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[zenduo:fail]\033[0m %s\n' "$*" >&2; exit 1; }

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
  [ "$(id -u)" = 0 ] || die "must run as root (use: sudo ./install.sh --system)"
}

# ── feature switches ─────────────────────────────────────────────────────────
# feature_on NAME DEFAULT: true iff ZENDUO_<NAME> is 1 (or unset and DEFAULT=1).
# Anything that is not exactly 1 reads as off, so a typo disables a feature
# rather than enabling it.
feature_on() { # <NAME> <default 0|1>
  local var="ZENDUO_$1" val
  val="${!var:-$2}"
  [ "$val" = 1 ]
}

# ── hardware / distro ────────────────────────────────────────────────────────
dmi_product() { cat "${ZENDUO_DMI_PRODUCT:-/sys/class/dmi/id/product_name}" 2>/dev/null || true; }

# True on a Zenbook Duo (2024) UX8406MA. Later variants (UX8406CA, Arrow Lake)
# share the chassis but not every quirk; they are matched too, with doctor
# reporting the exact model, because most of this tooling is chassis-level.
is_duo_hardware() { case "$(dmi_product)" in *UX8406*) return 0 ;; *) return 1 ;; esac; }

distro_id() { ( . /etc/os-release 2>/dev/null && echo "${ID:-unknown}" ) || echo unknown; }
distro_version() { ( . /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}" ) || true; }
distro_like() { ( . /etc/os-release 2>/dev/null && echo "${ID:-} ${ID_LIKE:-}" ) || echo unknown; }

# apt | dnf | pacman | none — decided from ID/ID_LIKE, not from which binaries
# exist (a Fedora box with a stray apt binary is still a dnf machine).
pkg_manager() {
  local like
  like="$(distro_like)"
  case " $like " in
    *" ubuntu "*|*" debian "*) echo apt ;;
    *" fedora "*|*" rhel "*|*" centos "*) echo dnf ;;
    *" arch "*|*" manjaro "*) echo pacman ;;
    *) echo none ;;
  esac
}

# ── users ────────────────────────────────────────────────────────────────────
# The human user the tooling belongs to: ZENDUO_TARGET_USER > the user who
# invoked sudo > failure. Root-level pieces (the sudoers rule, the amp-check
# notifier) are bound to exactly one account on purpose.
target_user() {
  local u="${ZENDUO_TARGET_USER:-}"
  if [ -z "$u" ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    u="$SUDO_USER"
  fi
  [ -n "$u" ] || return 1
  echo "$u"
}

target_home() { getent passwd "$1" | cut -d: -f6; }

# ── packages ─────────────────────────────────────────────────────────────────
# True iff the package is in dpkg state "install ok installed".
# NOT `dpkg -s`: that exits 0 for any package dpkg still knows about, including
# "deinstall ok config-files" (removed but not purged), which would then be
# reported present forever and never reinstalled.
pkg_installed() {
  case "$(pkg_manager)" in
    apt)    [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = installed ] ;;
    dnf)    rpm -q "$1" >/dev/null 2>&1 ;;
    pacman) pacman -Qq "$1" >/dev/null 2>&1 ;;
    *)      return 1 ;;
  esac
}

# Install only the packages that are missing, with the native package manager.
ensure_pkg() {
  local missing=() p mgr
  mgr="$(pkg_manager)"
  for p in "$@"; do
    pkg_installed "$p" || missing+=("$p")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    log "packages already present: $*"
    return 0
  fi
  log "installing: ${missing[*]}"
  case "$mgr" in
    apt)    run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}" ;;
    dnf)    run dnf install -y "${missing[@]}" ;;
    pacman) run pacman -S --needed --noconfirm "${missing[@]}" ;;
    *)      warn "no supported package manager — install by hand: ${missing[*]}" ;;
  esac
}

# apt-get update, hiding routine per-mirror chatter. If at least one repository
# refreshed the lists are usable; only when nothing could be reached are the
# reasons shown. No-op on non-apt systems (dnf/pacman refresh on install).
apt_update() {
  [ "$(pkg_manager)" = apt ] || return 0
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

# ── matching / files ─────────────────────────────────────────────────────────
# True iff <text> contains a line matching the grep expression that follows.
#
#   out_matches "$out" -E '^(Hit|Get):'
#   out_matches "$groups" -x docker
#
# Use this instead of `cmd | grep -q ...` — see the header. A herestring is
# backed by a temp file, so there is no writer left for grep to hang up on.
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
#   if install_conf "$path" "$body"; then udevadm control --reload; fi
#
# ALWAYS call it in a conditional context — a bare call returning 1 would abort
# the script under `set -e`. Parent directories are created; mode is 0644
# root:root.
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

# ── GRUB ─────────────────────────────────────────────────────────────────────
# Add a kernel parameter to GRUB_CMDLINE_LINUX_DEFAULT iff absent.
# Sets GRUB_CHANGED=1; the caller decides when to regenerate grub.cfg (once).
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

# Remove a kernel parameter from GRUB_CMDLINE_LINUX_DEFAULT iff present.
remove_grub_param() {
  local param="$1" current
  current="$(sed -nE 's/^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"/\1/p' "$GRUB_FILE" | head -n1)"
  case " $current " in
    *" $param "*) ;;
    *) log "GRUB param already absent: $param"; return 0 ;;
  esac
  log "removing GRUB param: $param"
  if [ "$DRY_RUN" != 1 ]; then
    # Rebuild the value word by word: a greedy regex over the quoted string
    # leaves a stray space behind, and a param can be a prefix of another.
    local rest="" w
    for w in $current; do
      [ "$w" = "$param" ] || rest="$rest${rest:+ }$w"
    done
    rest="$(printf '%s' "$rest" | sed -e 's/[&|\\]/\\&/g')"
    sed -i -E "s|^GRUB_CMDLINE_LINUX_DEFAULT=\".*\"|GRUB_CMDLINE_LINUX_DEFAULT=\"${rest}\"|" "$GRUB_FILE"
  fi
  GRUB_CHANGED=1
  mark_change
}

# Regenerate grub.cfg with whatever this distro calls the tool.
grub_regenerate() {
  if command -v update-grub >/dev/null 2>&1; then
    run update-grub
  elif command -v grub2-mkconfig >/dev/null 2>&1; then
    run grub2-mkconfig -o /boot/grub2/grub.cfg
  elif command -v grub-mkconfig >/dev/null 2>&1; then
    run grub-mkconfig -o /boot/grub/grub.cfg
  else
    warn "no update-grub/grub-mkconfig found — regenerate your bootloader config by hand"
  fi
}
