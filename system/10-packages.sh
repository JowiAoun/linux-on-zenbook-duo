#!/usr/bin/env bash
# 40-duo-deps.sh — [zenbook-duo hosts only] runtime dependencies for the
# zenduo tooling (duo/):
#   usbutils          lsusb, used by humans debugging attach/detach
#   inotify-tools     inotifywait for event-driven waits
#   iio-sensor-proxy  monitor-sensor / D-Bus accelerometer for rotation
#   python3-gi        GObject introspection — Mutter DisplayConfig D-Bus client
#   evtest            watch decoded evdev key events (Fn/media-key mapping;
#                     the standard counterpart to `duo watch-input`)
# (no pyusb: the kb-backlight fallback uses hidraw ioctls, see duo/lib/kb_backlight.py)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

if ! is_duo_host; then
  log "not a zenbook-duo host — skipping"
  exit 0
fi

ensure_pkg \
  usbutils \
  inotify-tools \
  iio-sensor-proxy \
  python3 \
  python3-gi \
  evtest
