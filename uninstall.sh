#!/usr/bin/env bash
# uninstall.sh — take linux-on-zenbook-duo back off a machine.
#
#   ./uninstall.sh              both halves (asks for sudo)
#   ./uninstall.sh --user       stop + remove the duo-* user units only
#   ./uninstall.sh --system     (sudo) the command, helper, sudoers, udev, quirk, amp reporter
#   --purge                     also delete ~/.config/zenduo and the speaker preset
#   --revert-grub               also remove i915.enable_psr=0 (expect OLED flicker)
#   --prefix DIR                where it was installed (default /usr/local)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

log()  { printf '\033[1;34m[zenduo]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[zenduo:warn]\033[0m %s\n' "$*" >&2; }
# shellcheck source=lib/conf.sh
source lib/conf.sh   # nix_managed

DO_SYSTEM=1 DO_USER=1 PURGE=0 REVERT_GRUB=0 PREFIX=/usr/local
while [ $# -gt 0 ]; do
  case "$1" in
    --system) DO_SYSTEM=1; DO_USER=0 ;;
    --user) DO_USER=1; DO_SYSTEM=0 ;;
    --purge) PURGE=1 ;;
    --revert-grub) REVERT_GRUB=1 ;;
    --prefix) [ $# -ge 2 ] || { echo "--prefix needs a directory" >&2; exit 64; }; PREFIX="$2"; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
  shift
done

user_half() {
  local d="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user" f
  if systemctl --user show-environment >/dev/null 2>&1; then
    for f in watch-displays watch-fn watch-backlight watch-rotation bat-limit; do
      systemctl --user disable --now "duo-$f.service" 2>/dev/null || true
    done
  fi
  for f in "$d"/duo-*.service; do
    [ -e "$f" ] || continue
    if nix_managed "$f"; then
      warn "$(basename "$f") is managed by home-manager — remove it there"
      continue
    fi
    rm -f "$f"; log "removed $f"
  done
  systemctl --user daemon-reload 2>/dev/null || true
  if [ "$PURGE" = 1 ]; then
    python3 lib/speaker_dsp.py uninstall || true
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/zenduo" "${XDG_STATE_HOME:-$HOME/.local/state}/zenduo"
    log "removed ~/.config/zenduo and ~/.local/state/zenduo"
  else
    log "kept ~/.config/zenduo (use --purge to remove it)"
  fi
}

system_half() {
  export ZENDUO_PREFIX="$PREFIX"
  # shellcheck source=system/lib.sh
  source system/lib.sh
  require_root
  systemctl disable --now duo-cs35l41-check.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/duo-cs35l41-check.service /usr/local/sbin/duo-cs35l41-check
  systemctl daemon-reload
  # The login screen's copy of the layout memory (duo layout login). Restore
  # the greeter's own file if it had one; remove ours if it did not.
  gdm_home="$(getent passwd gdm 2>/dev/null | cut -d: -f6 || true)"
  if [ -n "$gdm_home" ]; then
    if [ -e "$gdm_home/.config/monitors.xml.zenduo-backup" ]; then
      mv -f "$gdm_home/.config/monitors.xml.zenduo-backup" "$gdm_home/.config/monitors.xml"
      rm -f "$gdm_home/.config/monitors.xml.zenduo-installed"
      log "restored the login screen's own monitors.xml"
    elif [ -e "$gdm_home/.config/monitors.xml.zenduo-installed" ]; then
      rm -f "$gdm_home/.config/monitors.xml" "$gdm_home/.config/monitors.xml.zenduo-installed"
      log "removed the login screen layout this project installed"
    fi
  fi
  rm -f /etc/sudoers.d/zenduo /usr/local/sbin/zenduo-helper
  if [ -e /etc/udev/rules.d/70-zenduo.rules ]; then
    rm -f /etc/udev/rules.d/70-zenduo.rules
    udevadm control --reload || true
  fi
  if [ -e /etc/libinput/local-overrides.quirks ] && grep -qE '^# (zenduo|dome) — palm rejection for the ASUS Zenbook Duo' /etc/libinput/local-overrides.quirks; then
    rm -f /etc/libinput/local-overrides.quirks
  fi
  rm -f "$PREFIX/bin/duo"
  rm -rf "$PREFIX/lib/zenduo"
  log "removed the command, helper, sudoers rule, udev rule, touchpad quirk and amp reporter"
  if [ "$REVERT_GRUB" = 1 ] && [ -f "$GRUB_FILE" ]; then
    remove_grub_param "i915.enable_psr=0"
    [ "$GRUB_CHANGED" = 1 ] && grub_regenerate
  else
    log "kept i915.enable_psr=0 on the kernel command line (--revert-grub removes it)"
  fi
  log "packages (python3-gi, iio-sensor-proxy, ...) were left installed"
}

if [ "$DO_USER" = 1 ] && [ "$(id -u)" != 0 ]; then user_half; fi
if [ "$DO_SYSTEM" = 1 ]; then
  if [ "$(id -u)" = 0 ]; then
    system_half
  else
    args=(--system --prefix "$PREFIX")
    [ "$REVERT_GRUB" = 1 ] && args+=(--revert-grub)
    sudo bash "$0" "${args[@]}"
  fi
fi
if [ "$DO_USER" = 1 ] && [ "$(id -u)" = 0 ]; then
  warn "run ./uninstall.sh --user as yourself to remove the user units"
fi
log "done"
