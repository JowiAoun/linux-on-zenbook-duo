#!/usr/bin/env bash
# install.sh — one-command setup of linux-on-zenbook-duo.
#
#   git clone https://github.com/JowiAoun/linux-on-zenbook-duo ~/linux-on-zenbook-duo
#   cd ~/linux-on-zenbook-duo
#   ./install.sh                       # asks for sudo once; idempotent, re-run any time
#
# Two halves, both run by default:
#   --system   root: packages, kernel policy (Ubuntu), GRUB PSR fix, the `duo`
#              command, udev rules, the root helper + sudoers rule, the
#              touchpad quirk, the speaker-amp reporter.   (system/run.sh)
#   --user     you: ~/.config/zenduo/zenduo.conf, the duo-* systemd user units,
#              and the features you asked for, started now.
#
# Feature flags (see `duo features` afterwards; every one can be changed later):
#   --no-hwe-kernel        Ubuntu only: don't manage the HWE/GA kernel pair
#   --no-psr-fix           don't add i915.enable_psr=0 (OLED flicker fix)
#   --no-palm-rejection    don't install the libinput touchpad quirk
#   --no-amp-check         don't install the CS35L41 speaker-amp reporter
#   --no-watch-displays    don't run the dock policy daemon
#   --no-watch-fn          don't run the keyboard hotkey daemon
#   --watch-backlight      also run the bottom-panel backlight sync daemon
#   --watch-rotation       also run the (experimental) rotation logger
#   --battery-limit N      set BATTERY_LIMIT=N (20-100) and enable duo-bat-limit
#   --apply-method M       temporary (default) | persistent — read the config's warning first
#   --speaker-dsp          install the EasyEffects speaker voicing chain
#
# Other:
#   --dev                  link the system install to THIS checkout instead of
#                          copying it, so edits are live (developers)
#   --prefix DIR           install under DIR instead of /usr/local
#   --dry-run              print what would change, change nothing
#   --force                proceed on hardware that is not a Zenbook Duo
#   --user NAME            (when run as root) the account the tooling is for
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
SRC="$PWD"

log()  { printf '\033[1;34m[zenduo]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[zenduo:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[zenduo:fail]\033[0m %s\n' "$*" >&2; exit 1; }
banner() { printf '\n\033[1;36m========== %s ==========\033[0m\n' "$*"; }

DO_SYSTEM=1 DO_USER=1 DRY_RUN=0 FORCE=0
PREFIX=/usr/local
TARGET_USER=""
SYSTEM_FLAGS=()   # forwarded to system/run.sh
USER_FLAGS=()     # forwarded to the user half when it re-runs under runuser (see below)
WATCH_DISPLAYS=1 WATCH_FN=1 WATCH_BACKLIGHT=0 WATCH_ROTATION=0
BATTERY_LIMIT="" APPLY_METHOD="" SPEAKER_DSP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --system)            DO_SYSTEM=1; DO_USER=0 ;;
    --user)
      if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then TARGET_USER="$2"; shift
      else DO_USER=1; DO_SYSTEM=0; fi ;;
    --dev)               SYSTEM_FLAGS+=(--dev) ;;   # the user half has no dev/copy distinction
    --dry-run|-n)        DRY_RUN=1; SYSTEM_FLAGS+=(--dry-run); USER_FLAGS+=(--dry-run) ;;
    --force)             FORCE=1; SYSTEM_FLAGS+=(--force) ;;
    --prefix)            [ $# -ge 2 ] || die "--prefix needs a directory"; PREFIX="$2"; SYSTEM_FLAGS+=(--prefix "$2"); USER_FLAGS+=(--prefix "$2"); shift ;;
    --hwe-kernel|--no-hwe-kernel|--psr-fix|--no-psr-fix|--palm-rejection|--no-palm-rejection|--amp-check|--no-amp-check)
                         SYSTEM_FLAGS+=("$1") ;;
    --watch-displays)    WATCH_DISPLAYS=1; USER_FLAGS+=("$1") ;;
    --no-watch-displays) WATCH_DISPLAYS=0; USER_FLAGS+=("$1") ;;
    --watch-fn)          WATCH_FN=1; USER_FLAGS+=("$1") ;;
    --no-watch-fn)       WATCH_FN=0; USER_FLAGS+=("$1") ;;
    --watch-backlight)   WATCH_BACKLIGHT=1; USER_FLAGS+=("$1") ;;
    --no-watch-backlight) WATCH_BACKLIGHT=0; USER_FLAGS+=("$1") ;;
    --watch-rotation)    WATCH_ROTATION=1; USER_FLAGS+=("$1") ;;
    --no-watch-rotation) WATCH_ROTATION=0; USER_FLAGS+=("$1") ;;
    --battery-limit)     [ $# -ge 2 ] || die "--battery-limit needs a number (20-100)"; BATTERY_LIMIT="$2"; USER_FLAGS+=(--battery-limit "$2"); shift ;;
    --apply-method)      [ $# -ge 2 ] || die "--apply-method needs temporary|persistent"; APPLY_METHOD="$2"; USER_FLAGS+=(--apply-method "$2"); shift ;;
    --speaker-dsp)       SPEAKER_DSP=1; USER_FLAGS+=("$1") ;;
    --no-speaker-dsp)    SPEAKER_DSP=0; USER_FLAGS+=("$1") ;;
    -h|--help)           sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
  shift
done

if [ -n "$BATTERY_LIMIT" ]; then
  if ! [[ "$BATTERY_LIMIT" =~ ^[0-9]+$ ]] || [ "$BATTERY_LIMIT" -lt 20 ] || [ "$BATTERY_LIMIT" -gt 100 ]; then
    die "--battery-limit must be 20-100"
  fi
fi
case "${APPLY_METHOD:-temporary}" in temporary|persistent) ;; *) die "--apply-method must be temporary or persistent" ;; esac

# Test seam (tests/test-lib.sh): print what was parsed and what would be
# forwarded, then stop before anything is touched.
if [ "${ZENDUO_INSTALL_PLAN:-0}" = 1 ]; then
  for v in DO_SYSTEM DO_USER DRY_RUN FORCE PREFIX TARGET_USER WATCH_DISPLAYS WATCH_FN \
           WATCH_BACKLIGHT WATCH_ROTATION BATTERY_LIMIT APPLY_METHOD SPEAKER_DSP; do
    printf '%s=%s\n' "$v" "${!v}"
  done
  printf 'SYSTEM_FLAGS=%s\n' "${SYSTEM_FLAGS[*]}"
  printf 'USER_FLAGS=%s\n' "${USER_FLAGS[*]}"
  exit 0
fi

# ── the user half, as a function so it can run under runuser ─────────────────
user_phase() {
  local duo units_src f name body cur
  if [ "$DRY_RUN" = 1 ]; then run() { log "DRY RUN: $*"; }; else run() { "$@"; }; fi

  # shellcheck source=lib/conf.sh
  source "$SRC/lib/conf.sh"
  export ZENDUO_CONF_EXAMPLE="$SRC/config/zenduo.conf.example"

  # Which `duo` the units run. The system half puts it at $PREFIX/bin/duo;
  # without the system half (or before it) fall back to this checkout.
  if [ -x "$PREFIX/bin/duo" ]; then duo="$PREFIX/bin/duo"; else duo="$SRC/bin/duo"; fi
  log "units will run: $duo"

  # home-manager owns the user half on some machines (the author's): the
  # config and the units are read-only symlinks into the Nix store. Then this
  # script must not write beside them — a unit it drops in for a feature the
  # module has off today is "a file in the way" of the next home-manager
  # switch that turns it on — and every flag it was given belongs in the
  # zenduo.* options instead. Report, and touch nothing.
  local hm=0 conf units_dst
  conf="$(conf_path)"
  units_dst="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  if nix_managed "$conf"; then hm=1; fi
  for f in "$units_dst"/duo-*.service; do
    if nix_managed "$f"; then hm=1; fi
  done
  if [ "$hm" = 1 ]; then
    log "home-manager manages the user half here ($conf and/or $units_dst/duo-*.service are Nix store symlinks)"
    log "nothing to do: set zenduo.batteryLimit / watchFn / speakerDsp ... in your home-manager config and switch"
    [ -z "$BATTERY_LIMIT$APPLY_METHOD" ] && [ "$SPEAKER_DSP" = 0 ] \
      || warn "ignoring --battery-limit / --apply-method / --speaker-dsp: they belong in the home-manager options"
    echo
    "$duo" status || true
    return 0
  fi

  # 1. config
  if [ ! -e "$conf" ]; then
    log "creating $conf from config/zenduo.conf.example"
    if [ "$DRY_RUN" != 1 ]; then
      mkdir -p "$(dirname "$conf")"
      cp "$ZENDUO_CONF_EXAMPLE" "$conf"
    fi
  else
    log "config present: $conf"
  fi
  if [ -n "$BATTERY_LIMIT" ]; then
    if [ "$DRY_RUN" = 1 ]; then log "DRY RUN: would set BATTERY_LIMIT=$BATTERY_LIMIT"; else conf_set BATTERY_LIMIT "$BATTERY_LIMIT"; fi
  fi
  if [ -n "$APPLY_METHOD" ]; then
    if [ "$DRY_RUN" = 1 ]; then log "DRY RUN: would set APPLY_METHOD=$APPLY_METHOD"; else conf_set APPLY_METHOD "$APPLY_METHOD"; fi
  fi

  # 2. units
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    warn "no systemd user session reachable — units not installed (log in graphically and re-run: ./install.sh --user)"
    return 0
  fi
  units_src="$SRC/systemd/user"
  run mkdir -p "$units_dst"
  local changed=0
  for f in "$units_src"/duo-*.service; do
    name="$(basename "$f")"
    body="$(sed "s|^ExecStart=/usr/local/bin/duo|ExecStart=$duo|" "$f")"
    cur="$(cat "$units_dst/$name" 2>/dev/null || true)"
    if [ "$cur" = "$body" ]; then
      log "unit up to date: $name"
    else
      log "installing unit: $name"
      [ "$DRY_RUN" = 1 ] || printf '%s\n' "$body" > "$units_dst/$name"
      changed=1
    fi
  done
  if [ "$changed" = 1 ]; then run systemctl --user daemon-reload; fi

  # 3. enable what was asked for (and stop what was explicitly turned off, so a
  #    re-run with different flags converges instead of only ever adding).
  set_feature() { # <feature> <0|1> [oneshot]
    local unit="duo-$1.service"
    if [ "$2" = 1 ]; then
      # A oneshot is "inactive" the moment it has run, so for one, enabled is
      # the whole test — asking for is-active too re-enabled bat-limit on
      # every run and logged "enabled" as if something had changed.
      if systemctl --user is-enabled --quiet "$unit" 2>/dev/null \
         && { [ "${3:-}" = oneshot ] || systemctl --user is-active --quiet "$unit" 2>/dev/null; }; then
        log "$1: already enabled${3:+ (runs at login)}"
      else
        run systemctl --user enable --now "$unit"
        log "$1: enabled"
      fi
    else
      if systemctl --user is-enabled --quiet "$unit" 2>/dev/null || systemctl --user is-active --quiet "$unit" 2>/dev/null; then
        run systemctl --user disable --now "$unit"
        log "$1: disabled"
      else
        log "$1: off"
      fi
    fi
  }
  set_feature watch-displays "$WATCH_DISPLAYS"
  set_feature watch-fn "$WATCH_FN"
  set_feature watch-backlight "$WATCH_BACKLIGHT"
  set_feature watch-rotation "$WATCH_ROTATION"
  if [ -n "$(conf_get BATTERY_LIMIT)" ]; then
    set_feature bat-limit 1 oneshot
    # A limit given on this command line should hold now, not at the next login.
    if [ -n "$BATTERY_LIMIT" ]; then run systemctl --user start duo-bat-limit.service; log "bat-limit: applied $BATTERY_LIMIT% now"; fi
  else
    set_feature bat-limit 0
  fi

  # 4. speaker chain (opt-in)
  if [ "$SPEAKER_DSP" = 1 ]; then
    if [ "$DRY_RUN" = 1 ]; then
      python3 "$SRC/lib/speaker_dsp.py" install --dry-run
    else
      python3 "$SRC/lib/speaker_dsp.py" install
    fi
  fi

  # 5. one more thing the dock daemon cannot do for you on a fresh machine
  if [ "$DRY_RUN" != 1 ] && command -v dconf >/dev/null 2>&1 && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    # GNOME's own disable-while-typing switch (the quirk gives it something to act on).
    dconf write /org/gnome/desktop/peripherals/touchpad/disable-while-typing true 2>/dev/null || true
  fi

  echo
  "$duo" status || true
  return 0
}

# ── run ──────────────────────────────────────────────────────────────────────
log "linux-on-zenbook-duo $(cat VERSION 2>/dev/null || echo dev)   system: $DO_SYSTEM   user: $DO_USER   dry run: $DRY_RUN"

if [ "$(id -u)" = 0 ]; then
  # Invoked with sudo (or as root). The system half runs directly; the user
  # half must run as the real account, with its own systemd/D-Bus reachable.
  [ -n "$TARGET_USER" ] || TARGET_USER="${SUDO_USER:-}"
  if [ "$DO_SYSTEM" = 1 ]; then
    banner "system layer"
    [ -n "$TARGET_USER" ] && SYSTEM_FLAGS+=(--user "$TARGET_USER")
    bash system/run.sh "${SYSTEM_FLAGS[@]}"
  fi
  if [ "$DO_USER" = 1 ]; then
    if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = root ]; then
      warn "running as root with no invoking user — skipping the user half. Run as yourself: ./install.sh --user"
    else
      banner "user layer (as $TARGET_USER)"
      uid="$(id -u "$TARGET_USER")"
      # The flags go as ARGUMENTS. The child is this script again and its
      # parser starts from the defaults, so anything exported here is reset
      # before it is read — that is how `sudo ./install.sh --dry-run` ran the
      # user half for real, and dropped --battery-limit, --speaker-dsp and
      # --prefix on the floor (reproduced 2026-09-05).
      runuser -u "$TARGET_USER" -- env "XDG_RUNTIME_DIR=/run/user/$uid" "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus" \
        HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)" bash "$0" "${USER_FLAGS[@]}" --user \
        || warn "user half failed — re-run as $TARGET_USER: ./install.sh --user ${USER_FLAGS[*]}"
    fi
  fi
else
  if [ "$DO_SYSTEM" = 1 ]; then
    banner "system layer (needs root — you will be asked for your password)"
    if [ "$FORCE" != 1 ]; then
      case "$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)" in
        *UX8406*) ;;
        *) die "this is not a Zenbook Duo ($(cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'unknown model')). Use --force if you know better." ;;
      esac
    fi
    sudo -v || die "sudo is required for the system layer (or run ./install.sh --user for the user half only)"
    sudo bash system/run.sh "${SYSTEM_FLAGS[@]}" --user "$USER"
  fi
  if [ "$DO_USER" = 1 ]; then
    banner "user layer"
    user_phase
  fi
fi

banner "done"
if [ "$DRY_RUN" = 1 ]; then
  log "dry run — nothing was changed"
else
  log "next: 'duo doctor' for a full probe, 'duo features' to see what is on, 'duo config' for the knobs"
  log "      if the kernel or GRUB changed above, reboot to apply"
fi
