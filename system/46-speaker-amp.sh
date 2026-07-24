#!/usr/bin/env bash
# 46-duo-speaker-amp.sh — [zenbook-duo hosts only] detect the Cirrus CS35L41
# smart amplifiers losing their power-up handshake, and say so loudly.
#
# The Duo's speakers are not driven by the ALC294 codec alone: two CS35L41
# amplifiers sit behind it (…-cs35l41-hda.0 = left, .1 = right) running ASUS's
# spk-prot firmware, which carries this unit's speaker calibration and the
# protection DSP. The kernel binds them and loads that firmware early in boot:
#
#   cs35l41-hda …-cs35l41-hda.0: DSP1: cirrus/cs35l41-dsp1-spk-prot-10431c43.wmfw
#   cs35l41-hda …-cs35l41-hda.0: Calibration applied: R0=10223
#   cs35l41-hda …-cs35l41-hda.0: CS35L41 Bound — … CH: L, FW EN: 1
#
# …and then, a couple of seconds later, the power-up handshake sometimes times
# out on both amps at once:
#
#   cs35l41-hda …-cs35l41-hda.0: Failed waiting for CS35L41_PUP_DONE_MASK: -110
#
# The speakers still play when that happens — they just play without the amp
# DSP, which sounds harsh, crackly and distorted — and they stay that way for
# the rest of the boot, failing again on every subsequent playback. It is a
# race, not a misconfiguration: measured 2026-07-23, eight failures on one boot
# with the four boots before it completely clean. Nothing in userspace causes it
# and nothing in userspace can compensate: EasyEffects, the PipeWire volumes and
# the SOF topology are all downstream of the damage, which is why toggling any
# of them makes no audible difference.
#
# ── The actual cause, and the actual fix ──────────────────────────────────────
# This machine dual-boots: nvme0n1p3 is a BitLocker Windows install, with the
# ASUS RECOVERY and MYASUS partitions and \EFI\Microsoft on the ESP. That is the
# known trigger for PUP_DONE timeouts on CS35L41 laptops. Windows Fast Startup
# does not really power the machine down — "Shut down" hibernates the kernel
# session — so the amps are left initialised by the Windows driver and Linux
# inherits hardware it cannot cleanly bring up. It fits the observed pattern
# exactly: boots that follow a clean Linux shutdown come up fine, boots that
# follow Windows do not.
#
# THE FIX IS ON THE WINDOWS SIDE and cannot be applied from here — the system
# partition is BitLocker-encrypted, so the HiberbootEnabled registry key is not
# reachable from Linux. In an Administrator command prompt on Windows:
#
#     powercfg /h off
#
# which disables hibernation and Fast Startup with it. After that, use "Shut
# down" rather than "Restart" when crossing between the two systems.
#
# Kernel-side there is nothing left to configure: the ASUS SSID quirks for
# CSC3551 landed upstream in 6.7 and this machine runs 7.0, so the SSDT/ACPI
# patching that older guides describe is obsolete here — the amps bind with the
# right BST/CH/SPKID and load the right firmware, as the log above shows.
#
# ── Why this does not try to repair the amps (VERIFIED THE HARD WAY) ──────────
# The tempting repair is to re-bind the SPI devices so the driver re-runs init.
# DO NOT. The driver does not tear its ALSA controls down on unbind, so the
# re-bind collides with the ones still registered (tried 2026-07-23, on the very
# boot described above):
#
#   cs35l41-hda …hda.0: Failed to add KControl L0 DSP1 Firmware Type = -16
#   snd_hda_codec_alc269 ehdaudio0D0: failed to bind …hda.0 …: -16
#   snd_hda_codec_alc269 ehdaudio0D0: adev bind failed: -16
#   cs35l41-hda …hda.1: error -EBUSY: Register component failed
#   cs35l41-hda …hda.1: probe with driver cs35l41-hda failed with error -16
#   cs35l41-hda …hda.1: IRQ sync failed to resume: -13   (repeating)
#
# That is strictly worse than the fault it was meant to fix: the left amp came
# back but failed to attach to the codec, and the right one did not probe at
# all. Reloading the modules is no better — the documented advice is to reload
# only when the bus is clean, which is exactly what it is not once this has
# happened. A cold power-off is the only reliable recovery.
#
# So this component does not claim to fix anything. It names the fault the
# moment it happens, so a bad boot is thirty seconds of "power off properly"
# instead of an evening of wondering why music sounds wrong today.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

CHECK_DST=/usr/local/sbin/duo-cs35l41-check
UNIT_DST=/etc/systemd/system/duo-cs35l41-check.service

# An earlier revision of this script shipped a re-binding "healer" under a
# different name. Remove it rather than leave a working copy of a command that
# breaks the sound card.
OLD_HEAL=/usr/local/sbin/duo-cs35l41-heal
OLD_UNIT=/etc/systemd/system/duo-cs35l41-heal.service
if [ -e "$OLD_UNIT" ] || [ -e "$OLD_HEAL" ]; then
  log "removing the superseded re-binding healer"
  if [ "$DRY_RUN" != 1 ]; then
    systemctl disable --now duo-cs35l41-heal.service >/dev/null 2>&1 || true
    rm -f "$OLD_UNIT" "$OLD_HEAL"
    systemctl daemon-reload
  fi
fi

DUO_USER="$(target_user)" || die "cannot determine the target user — set environment.username in user-config.nix or run via sudo from your own account"
id "$DUO_USER" >/dev/null 2>&1 || die "user '$DUO_USER' does not exist on this machine"

tmp_check="$(mktemp)"
tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_check" "$tmp_unit"' EXIT

cat > "$tmp_check" <<'CHECK'
#!/usr/bin/env bash
# duo-cs35l41-check — report when the Zenbook Duo's CS35L41 speaker amplifiers
# fail their power-up handshake, leaving the speakers running without the amp
# DSP (harsh and distorted for the rest of the boot).
#
# Installed by dome's system/46-duo-speaker-amp.sh. See that file for why this
# only reports: re-binding the driver to repair it makes the sound card worse.
#
#   duo-cs35l41-check            report on this boot; exit 1 if affected
#   duo-cs35l41-check --watch    report now, then keep watching the kernel log
set -euo pipefail

PATTERN='Failed waiting for CS35L41_PUP_DONE_MASK'
NOTIFIED=/run/duo-cs35l41-check.notified
DUO_USER='@TARGET_USER@'

log() { printf 'duo-cs35l41-check: %s\n' "$*"; }

# `grep -q` would exit at the first match, SIGPIPE journalctl, and — under
# `set -o pipefail` — make the whole pipeline report failure on the one input
# that should return success. Count instead, so the reader drains its input.
affected() {
  local hits
  hits="$(journalctl -k -b --no-pager 2>/dev/null | grep -c "$PATTERN" || true)"
  [ "${hits:-0}" -gt 0 ]
}

# One desktop notification per boot. Best effort throughout: a missing
# notify-send or a session that is not up yet must never take the unit down,
# since the journal message below is the real output.
notify_once() {
  [ -e "$NOTIFIED" ] && return 0
  # 2>/dev/null FIRST: redirections are applied left to right, so with the
  # order reversed the shell's own "Permission denied" for the failed open
  # escapes before stderr has been silenced.
  : 2>/dev/null > "$NOTIFIED" || true

  local uid bus
  uid="$(id -u "$DUO_USER" 2>/dev/null)" || return 0
  bus="/run/user/$uid/bus"
  [ -S "$bus" ] || return 0
  command -v notify-send >/dev/null 2>&1 || return 0

  runuser -u "$DUO_USER" -- env "DBUS_SESSION_BUS_ADDRESS=unix:path=$bus" \
    notify-send -u critical -a "Speaker amplifiers" \
      "Speakers are running unprotected" \
      "The CS35L41 amplifiers failed to power up this boot, so audio will sound harsh and distorted. Fix: shut down fully (not a reboot). To stop it recurring, run 'powercfg /h off' as Administrator in Windows to disable Fast Startup." \
    >/dev/null 2>&1 || true
}

report() {
  log "the CS35L41 amplifiers failed their power-up handshake this boot"
  log "speakers are playing WITHOUT the amp DSP — expect harsh, distorted sound"
  log ""
  log "recover now:  a full power-off (shutdown -h now), NOT a warm reboot —"
  log "              the amps hold state across a warm one"
  log "stop it recurring:  this machine dual-boots, and Windows Fast Startup"
  log "              leaves the amps in a state Linux cannot initialise. In an"
  log "              Administrator prompt on Windows:  powercfg /h off"
  log "              then use Shut down rather than Restart between systems."
  log ""
  log "do NOT re-bind or reload the driver to fix this: it leaves the codec"
  log "unable to attach and the right amp unprobed. See system/46-duo-speaker-amp.sh"
  notify_once
}

watch_journal() {
  # The failure normally happens during boot, well before this unit is up, so
  # the backlog matters more than the live stream.
  if affected; then
    report
  else
    log "amplifiers powered up cleanly this boot — watching"
  fi

  journalctl -k -f -n0 -o cat 2>/dev/null | while IFS= read -r line; do
    case "$line" in
      *"$PATTERN"*) report ;;
    esac
  done
}

case "${1:-}" in
  --watch) watch_journal ;;
  "")
    if affected; then
      report
      exit 1
    fi
    log "amplifiers powered up cleanly this boot"
    ;;
  *) echo "usage: duo-cs35l41-check [--watch]" >&2; exit 2 ;;
esac
CHECK

# The username is fixed at install time, the same way 50-duo-sudoers.sh binds
# its rule to one account rather than resolving one at runtime.
sed -i "s|@TARGET_USER@|$DUO_USER|" "$tmp_check"

cat > "$tmp_unit" <<'UNIT'
[Unit]
Description=Report Zenbook Duo CS35L41 speaker amplifier power-up failures
Documentation=https://github.com/JowiAoun/dome
After=sound.target
Wants=sound.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/duo-cs35l41-check --watch
# The watcher is a journalctl pipe; if that ever dies, resume watching rather
# than silently going blind to the next bad boot.
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

changed=0

if cmp -s "$tmp_check" "$CHECK_DST" 2>/dev/null; then
  log "checker up to date: $CHECK_DST"
else
  log "installing $CHECK_DST"
  run install -o root -g root -m 0755 "$tmp_check" "$CHECK_DST"
  changed=1
fi

if cmp -s "$tmp_unit" "$UNIT_DST" 2>/dev/null; then
  log "unit up to date: $UNIT_DST"
else
  log "installing $UNIT_DST"
  run install -o root -g root -m 0644 "$tmp_unit" "$UNIT_DST"
  changed=1
fi

if [ "$DRY_RUN" = 1 ]; then
  log "DRY RUN: would enable duo-cs35l41-check.service"
elif [ "$changed" = 1 ]; then
  systemctl daemon-reload
  systemctl enable --now duo-cs35l41-check.service
  log "duo-cs35l41-check.service enabled"
else
  systemctl enable --now duo-cs35l41-check.service >/dev/null 2>&1 || true
  log "duo-cs35l41-check.service already installed"
fi
