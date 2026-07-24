#!/usr/bin/env bash
# 46-duo-speaker-amp.sh — [zenbook-duo hosts only] recover the Cirrus CS35L41
# smart amplifiers when they lose the power-up handshake at boot.
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
# and nothing in userspace can paper over it; EasyEffects, PulseAudio volumes
# and the SOF topology are all downstream of the damage.
#
# Re-binding the SPI devices re-runs the whole init — firmware load and
# calibration included — so the recovery is to watch the kernel log for that
# message and re-bind when it shows up. The watcher also checks the log once at
# startup, because the usual case is that the failure has already happened by
# the time anything gets a chance to run.
#
# Deliberately conservative: a cooldown and a per-boot cap, because if a re-bind
# does not take then the next one will not either, and a watcher that reacts to
# the messages its own re-bind produces would spin forever.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

HEAL_DST=/usr/local/sbin/duo-cs35l41-heal
UNIT_DST=/etc/systemd/system/duo-cs35l41-heal.service

tmp_heal="$(mktemp)"
tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_heal" "$tmp_unit"' EXIT

cat > "$tmp_heal" <<'HEAL'
#!/usr/bin/env bash
# duo-cs35l41-heal — re-bind the Zenbook Duo's CS35L41 speaker amplifiers after
# a failed power-up. Installed by dome's system/46-duo-speaker-amp.sh.
#
#   duo-cs35l41-heal            re-bind once, now
#   duo-cs35l41-heal --watch    follow the kernel log and re-bind on failure
set -euo pipefail

DRV=/sys/bus/spi/drivers/cs35l41-hda
PATTERN='Failed waiting for CS35L41_PUP_DONE_MASK'
STAMP=/run/duo-cs35l41-heal.stamp
COUNT=/run/duo-cs35l41-heal.count
COOLDOWN=120     # seconds between re-binds
MAX_PER_BOOT=3   # after this many, stop and leave the evidence alone

log() { printf 'duo-cs35l41-heal: %s\n' "$*"; }

# The driver directory also holds bind/unbind/module/uevent, so match on the
# device naming rather than listing everything in it.
devices() {
  local p
  for p in "$DRV"/*cs35l41-hda.*; do
    [ -e "$p" ] || continue
    basename "$p"
  done
}

rebind() {
  local force="${1:-}" now last count devs=()

  [ -d "$DRV" ] || { log "driver not loaded ($DRV missing) — nothing to do"; return 0; }

  # Names must be collected BEFORE unbinding: the symlinks vanish from the
  # driver directory the moment a device is unbound, and then there is nothing
  # left to name in the bind step.
  mapfile -t devs < <(devices)
  if [ ${#devs[@]} -eq 0 ]; then
    log "no CS35L41 devices bound to the driver — nothing to do"
    return 0
  fi

  now="$(date +%s)"
  if [ "$force" != --force ]; then
    last="$(cat "$STAMP" 2>/dev/null || echo 0)"
    if [ $((now - last)) -lt "$COOLDOWN" ]; then
      log "re-bound $((now - last))s ago, inside the ${COOLDOWN}s cooldown — skipping"
      return 0
    fi
    count="$(cat "$COUNT" 2>/dev/null || echo 0)"
    if [ "$count" -ge "$MAX_PER_BOOT" ]; then
      log "already re-bound ${count}x this boot and it is still failing — giving up"
      log "the amps need a power cycle (full shutdown, not a warm reboot)"
      return 0
    fi
  fi

  count="$(cat "$COUNT" 2>/dev/null || echo 0)"
  printf '%s\n' "$now" > "$STAMP"
  printf '%s\n' "$((count + 1))" > "$COUNT"

  log "re-binding: ${devs[*]}"
  local d
  for d in "${devs[@]}"; do
    printf '%s\n' "$d" > "$DRV/unbind" 2>/dev/null || log "unbind $d failed"
  done
  sleep 1
  for d in "${devs[@]}"; do
    printf '%s\n' "$d" > "$DRV/bind" 2>/dev/null || log "bind $d failed"
  done
  log "re-bind issued (attempt $((count + 1))/${MAX_PER_BOOT}) — check for a fresh"
  log "'Firmware Loaded' / 'CS35L41 Bound' pair in dmesg"
}

watch_journal() {
  # The failure normally happens during boot, well before this unit is up, so
  # the backlog matters more than the live stream.
  if journalctl -k -b --no-pager 2>/dev/null | grep -q "$PATTERN"; then
    log "this boot already logged a power-up failure"
    rebind
  else
    log "no power-up failure in this boot's log — watching"
  fi

  journalctl -k -f -n0 -o cat 2>/dev/null | while IFS= read -r line; do
    case "$line" in
      *"$PATTERN"*)
        log "kernel reported a power-up failure"
        rebind
        ;;
    esac
  done
}

case "${1:-}" in
  --watch) watch_journal ;;
  --force) rebind --force ;;
  "")      rebind ;;
  *)       echo "usage: duo-cs35l41-heal [--watch|--force]" >&2; exit 2 ;;
esac
HEAL

cat > "$tmp_unit" <<'UNIT'
[Unit]
Description=Recover the Zenbook Duo CS35L41 speaker amps after a failed power-up
Documentation=https://github.com/JowiAoun/dome
After=sound.target
Wants=sound.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/duo-cs35l41-heal --watch
# The watcher is a journalctl pipe; if that ever dies, resume watching rather
# than leaving the machine one bad boot away from unprotected speakers.
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

changed=0

if cmp -s "$tmp_heal" "$HEAL_DST" 2>/dev/null; then
  log "healer up to date: $HEAL_DST"
else
  log "installing $HEAL_DST"
  run install -o root -g root -m 0755 "$tmp_heal" "$HEAL_DST"
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
  log "DRY RUN: would enable duo-cs35l41-heal.service"
elif [ "$changed" = 1 ]; then
  systemctl daemon-reload
  systemctl enable --now duo-cs35l41-heal.service
  log "duo-cs35l41-heal.service enabled"
else
  systemctl enable --now duo-cs35l41-heal.service >/dev/null 2>&1 || true
  log "duo-cs35l41-heal.service already installed"
fi
