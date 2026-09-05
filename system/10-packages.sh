#!/usr/bin/env bash
# 10-packages.sh — runtime dependencies for the duo tooling:
#   usbutils          lsusb, used by humans debugging attach/detach
#   inotify-tools     inotifywait for event-driven waits (watch-backlight)
#   iio-sensor-proxy  monitor-sensor / D-Bus accelerometer for rotation
#   python3 + gi      GObject introspection — the Mutter DisplayConfig D-Bus client
#   evtest            watch decoded evdev key events (Fn/media-key mapping)
#   pciutils          lspci, for `duo doctor`
# No pyusb: the keyboard-backlight fallback talks to /dev/hidraw* directly
# (lib/kb_backlight.py), which never detaches the kernel driver.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

case "$(pkg_manager)" in
  apt)
    apt_update
    ensure_pkg usbutils inotify-tools iio-sensor-proxy python3 python3-gi evtest pciutils
    ;;
  dnf)
    ensure_pkg usbutils inotify-tools iio-sensor-proxy python3 python3-gobject evtest pciutils
    ;;
  pacman)
    ensure_pkg usbutils inotify-tools iio-sensor-proxy python python-gobject evtest pciutils
    ;;
  *)
    warn "unknown distro — make sure these are installed: usbutils inotify-tools iio-sensor-proxy python3 python3-gi (PyGObject) evtest pciutils"
    ;;
esac

# The one dependency that cannot be papered over: without PyGObject there is no
# display control at all. Check the SYSTEM interpreter, which is the one `duo`
# pins for its gi-using scripts (a Nix/pyenv python on PATH is not it).
PYGI="${DUO_PYGI:-/usr/bin/python3}"
if [ -x "$PYGI" ] && "$PYGI" -c 'import gi' >/dev/null 2>&1; then
  log "PyGObject available to $PYGI"
else
  warn "PyGObject (python3-gi) is not importable by $PYGI — display commands will not work until it is"
fi
