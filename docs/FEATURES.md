# Windows parity

What the machine does under Windows, whether it does it here, and how.
✅ verified on hardware · 🧪 implemented, not yet verified or partial ·
📝 planned (with the plan phase) · ✖ out of scope.

## Displays

| Windows | Here | Status |
|---|---|---|
| Bottom screen off when the keyboard is docked, on when lifted | `duo watch-displays` — converges the layout on keyboard poll, Mutter `MonitorsChanged` and logind resume | ✅ |
| Win+P: laptop only, external only, duplicate, extend | GNOME's own Super+P, or `duo layout laptop\|external\|mirror\|extend\|cycle`; the daemon governs the bottom panel only, so either survives | ✅ |
| The layout comes back per monitor set: same screens, positions, scales and primary as last time those monitors were connected | Recorded into GNOME's own `~/.config/monitors.xml` by `duo watch-displays`, restored by Mutter before anything is drawn (`REMEMBER_LAYOUT=1`) | 🧪 2026-09-12 |
| The lock screen appears on the monitor you were using | Same memory: Mutter restores the layout before the shield is drawn | 🧪 2026-09-12 |
| The sign-in screen appears there too | `duo layout login` (automatic after a change) installs the same layouts for GDM, via the root helper | 🧪 2026-09-12 |
| Second-screen key toggles the bottom panel | `5a 6a` → `duo toggle`; ignored while docked (the panel is under the keyboard) | ✅ |
| Brightness keys drive both panels | GNOME's own StepUp/StepDown (with OSD) then the bottom panel is synced | ✅ |
| Auto-rotate: tent, book, portrait | `duo watch-rotation` logs orientation | 🧪 → phase O |
| Touch and pen land on the right panel | `duo set-tablet-mapping` (GNOME 46 dconf) | 🧪 → phase P |
| No OLED flicker | `i915.enable_psr=0` | ✅ |
| ScreenXpert app launcher / window-throw between panels | — | 📝 phase U |
| Six-finger virtual keyboard gesture | GNOME's on-screen keyboard appears when no keyboard is present | ✖ (phase U covers the useful part) |

## Keyboard

| Windows | Here | Status |
|---|---|---|
| Typing over USB (docked) and Bluetooth (detached) | kernel | ✅ |
| Fn-row: brightness down/up | `watch-fn` | ✅ USB + BT |
| Fn-row: keyboard backlight cycle | `watch-fn` → `duo kb-backlight` | ✅ |
| Fn-row: volume, mute | native consumer-page usages | ✅ |
| Fn-row: Fn-lock (Fn+Esc) | captured (`5a 4e`), swap not performed | 🧪 → phase Q |
| Fn-row: mic mute, emoji | `watch-fn` → `wpctl set-mute … toggle`, `ibus emoji` (codes `5a 7c`/`5a 7e`, per hid-asus) | 🧪 2026-09-05 → verify which keycaps |
| Fn-row: display switch, camera, MyASUS | captured by `fn-map`, unmapped (`5a 3d`, `5a 9c` seen, unattributed) | 📝 phase Q |
| Keyboard backlight level remembered across dock/undock/sleep | state file + restore on re-init | ✅ |
| Wi-Fi keeps working when the keyboard comes off | kernel ≥ 6.11 | ✅ |
| Palm rejection while typing | libinput quirk + disable-while-typing | ✅ |
| Bluetooth pairing | F10 long-press recipe (documented; nothing to automate) | ✅ |

## Audio

| Windows | Here | Status |
|---|---|---|
| Speaker voicing (harman/kardon APO) | `duo speaker-dsp`: EasyEffects chain | ✅ Nix EE 8; 🧪 apt EE 7 (preset ships, autoload manual) → phase S |
| Amps always initialised | reporter + power-off recovery; root cause is Windows Fast Startup | ✅ (as good as it can be from Linux) |
| Microphone processing | — | 📝 phase S |

## Power

| Windows | Here | Status |
|---|---|---|
| Battery charge limit (MyASUS) | `duo bat-limit`, re-applied at login | ✅ |
| Performance / balanced / quiet profiles | `platform_profile` exists; no `duo` verb yet | 📝 phase T |
| Standby drain comparable to Windows | s2idle; unmeasured | 📝 phase T |
| Hibernate | — | ✖ |

## Everything else

| Windows | Here | Status |
|---|---|---|
| Windows Hello (IR face) | — | ✖ (Howdy unreliable; revisit after 1.0) |
| NPU | — | ✖ |
| BIOS updates | MyASUS or EZ-Flash from USB; never from Linux | ✖ by design |
| A settings app | `duo features` / `duo config` | 📝 phase W |
