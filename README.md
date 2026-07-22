# zenduo (`duo/`)

Hardware tooling for the **ASUS Zenbook Duo (2024) UX8406MA** on Ubuntu 24.04
(GNOME/Wayland). Self-contained: nothing here imports from the rest of `dome`,
so it can graduate to its own repository once proven on hardware
(see [`../docs/PLAN.md`](../docs/PLAN.md) §11, roadmap v1.0).

## Commands

```
duo doctor                 full read-only hardware probe — safe anywhere, incl. a live USB;
                           it is the Phase C install gate in PLAN.md
duo status                 quick glance: panels, keyboard, backlight, battery limit
duo top|bottom|both        enable that panel set (refuses to disable everything)
duo toggle                 bottom panel on <-> off
duo watch-displays         daemon: keyboard docked -> top only; undocked -> both panels
duo sync-backlight         copy the top panel's backlight percentage to the bottom panel
duo watch-backlight        daemon: keep the bottom backlight synced
duo kb-init                send the ASUS handshake to enable Fn/media-key reporting
duo kb-backlight 0..3      keyboard backlight — native LED if the kernel has it, else HID
duo bat-limit 20..100      battery charge-limit threshold (sysfs / root helper)
duo set-tablet-mapping     pin each ELAN touchscreen to its own panel (GNOME 46+)
duo watch-rotation         EXPERIMENTAL: log accelerometer orientation events
duo fn-probe               inventory what the Fn keys actually emit (raw hex)
duo fn-map                 guided wizard: HOLD Fn, press each key -> build a key->report map
duo fn-map --show          print the saved key->report map without re-capturing
duo watch-input            (root) decode key events from the keyboard + Asus WMI hotkeys
duo log                    follow zenduo journal messages
```

## Design rules

1. **Fail-safe:** `displayctl` refuses any configuration with zero enabled
   panels; display changes use Mutter's *temporary* apply method so a broken
   layout never survives a session restart.
2. **Native-first:** every capability probes the kernel interface before using
   a userspace fallback, so newer kernels automatically shrink this tool.
3. **Poll, don't storm:** keyboard presence is polled from sysfs at 1 Hz with
   a 2-sample debounce — no udev triggers on the pogo-pin device forest.
4. **Mutter D-Bus, not xrandr / gnome-monitor-config:** display control goes
   through `org.gnome.Mutter.DisplayConfig`, the same API GNOME Settings uses.
5. **Minimal privilege:** the only root path is `/usr/local/sbin/zenduo-helper`
   (installed by `system/50-duo-sudoers.sh`), which accepts exactly two
   validated verbs. The HID backlight fallback runs unprivileged via a udev
   uaccess rule on `/dev/hidraw*`.

## Layout

```
bin/duo               CLI entry point (bash)
lib/displayctl.py     Mutter DisplayConfig client (python3-gi)
lib/kb_backlight.py   HID feature-report backlight fallback (hidraw ioctl, no pyusb)
helper/zenduo-helper  the root helper — the only privileged code
systemd/*.service     reference unit templates (the Nix module generates the real ones)
```

## System dependencies

Installed by `sudo make system HOST=zenbook-duo` (see `system/40-duo-deps.sh`):
`usbutils`, `inotify-tools`, `iio-sensor-proxy`, `python3-gi`,
plus the udev rules (`45`) and sudoers rule (`50`). No pyusb — the HID
fallback talks straight to `/dev/hidraw*`.

## Hardware facts baked in

| Thing | Value |
|-------|-------|
| Keyboard (USB pogo + BT) | `0b05:1b2c` |
| Keyboard BT pairing mode | Detached + switch on + **hold `F10` 4–5 s** until the LED flashes blue rapidly (switch alone does not advertise) |
| Top digitizer | ELAN9008 `04f3:4259` → `eDP-1` |
| Bottom digitizer | ELAN9009 `04f3:42ec` → `eDP-2` |
| kb-backlight HID feature report | `{0x5a, 0xba, 0xc5, 0xc4, level}` (from mainline `hid-asus.c`) |
| Battery limit | `/sys/class/power_supply/BAT*/charge_control_end_threshold` |

## Prior art & licensing

zenduo is an original implementation, MIT-licensed (see `LICENSE`). It owes its
feature list to two projects worth crediting:

- [alesya-h/zenbook-duo-2024-ux8406ma-linux](https://github.com/alesya-h/zenbook-duo-2024-ux8406ma-linux)
  (BSD-2-Clause) — the original `duo` script; our command names stay
  deliberately compatible with it. No code is currently copied; if a snippet
  is ever adapted, its file gets the BSD-2 attribution notice.
- [Fmstrat/zenbook-duo-linux](https://github.com/Fmstrat/zenbook-duo-linux)
  (GPL-3.0) — behavioral reference only; **no code from this repo may be
  copied here** (license incompatibility with MIT).

Kernel-derived constants (USB IDs, HID report bytes) are facts, not code.
