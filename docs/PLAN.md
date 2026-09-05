# The plan, A to Z

**Goal.** Give the ASUS Zenbook Duo (2024) the functionality it has under
Windows, on Linux, as one installable project that anyone can put on their
machine and customise feature by feature — and keep the author's dotfiles
repo ([dome](https://github.com/JowiAoun/dome)) clean by having it consume
this project instead of carrying it.

**How to read this.** Part 1 (A–L) is the extraction and the standalone
install; it is what the 0.9.0 release is. Part 2 (M–Z) is the roadmap to 1.0
and beyond, in rough priority order. ⛔ marks a gate; **VERIFY-ON-HW** marks a
claim that must be tested on the machine before it is relied on. Checkboxes
are the state on 2026-09-05.

Standing rules, inherited from the first six weeks:

1. *Never take a step that cannot be undone.* Every system change is an
   idempotent script with a `--dry-run`, and every feature has an off switch.
2. *Prove it, don't assume it.* A feature graduates only after the test
   protocol in [DESIGN.md](DESIGN.md) — 10× attach/detach, suspend/resume,
   reboot, session restart, no journal errors.
3. *Native first.* Every capability probes the kernel first and falls back to
   userspace, so newer kernels automatically shrink this project.
4. *Firmware is out of scope, forever.* No EC, keyboard-MCU or panel firmware
   flashing from Linux. BIOS via MyASUS or EZ-Flash.

---

## Part 1 — the split (0.9.0)

### A. Inventory what is Duo-specific

Everything in dome that only makes sense on this hardware, and nothing else:

- [x] `duo/` — the CLI, daemons, root helper, unit templates
- [x] `system/40,45,46,50,55` — deps, udev, amp reporter, sudoers, touchpad quirk;
      the Duo half of `system/30-grub-params.sh` (`i915.enable_psr=0`); the
      kernel policy in `20-kernel.sh`, which exists because of this machine
- [x] `modules/zenbook-duo/` — the home-manager module (units, touchpad, audio)
- [x] `hosts/zenbook-duo/default.nix` — the host profile
- [x] `docs/PLAN.md`, `CHECKLIST.md`, `INSTALL-LOG.md`, the hardware research

Deliberately left in dome, because they are Ubuntu/GNOME preferences rather
than Duo hardware support: memory/zram tuning, boot-service pruning, the
login-PIN extension, Brave/Flatpak/Docker, the app grid, the dash.

### B. Create the repository with its history

- [x] `git filter-repo` over dome, keeping only the paths above and renaming
      them into a standalone layout — 53 commits of provenance survive, every
      "MEASURED 2026-07-25" comment keeps its commit
- [x] MIT license, `VERSION`, `.gitignore`

### C. A self-contained root layer

- [x] `system/lib.sh` without dome's `user-config.nix` bridge: feature switches
      arrive as `ZENDUO_<NAME>=0/1`, the target user comes from `--user` or
      `SUDO_USER`, distro and package manager are detected (apt / dnf / pacman)
- [x] one script per concern, each idempotent and `--dry-run`-able, each with
      an off switch: packages, kernel (Ubuntu), GRUB PSR, the CLI, udev,
      speaker-amp reporter, sudoers + helper, touchpad quirk
- [x] `system/run.sh` orchestrator with a read-only preflight that refuses to
      run on non-Duo hardware (unless `--force`) or a live USB

### D. A config file and a feature model

- [x] `~/.config/zenduo/zenduo.conf`: `KEY=value`, parsed not sourced, values
      whitelisted so a config file can never run code
- [x] knobs: `APPLY_METHOD`, `BATTERY_LIMIT`, `BACKLIGHT_SOURCE/TARGET`,
      `KB_BACKLIGHT_RESTORE`, `DOCK_POLICY`; the daemons read them through
      `duo` as environment, so the home-manager units can set the same values
- [x] features = systemd user units; `duo features`, `duo enable`, `duo disable`,
      `duo config`; system features = installer flags

### E. One-command install, and its inverse

- [x] `./install.sh`: root half via sudo, user half as you; `--dry-run`;
      `--dev` links the install to the checkout for live editing; `--prefix`
- [x] `./uninstall.sh` with `--purge` and `--revert-grub`
- [x] `Makefile` targets for the humans who prefer them

### F. Nix flake and home-manager module

- [x] `packages.x86_64-linux.zenduo`: the CLI wrapped with a PyGObject python
      and the tools it calls on PATH (`nix run github:… -- doctor` works)
- [x] `homeManagerModules.default`: the same options as before, plus
      `package`, `repoPath` (live checkout), `dockPolicy`,
      `kbBacklightRestore`, `writeConfig`
- [x] `nix flake check` builds the package and evaluates the module with every
      feature on

### G. One definition of the speaker chain

- [x] `lib/speaker_dsp.py` holds the chain once; the EasyEffects 8 db files
      (integer enums) and the preset JSON (label enums) are both generated from
      it, and a test asserts the committed preset matches
- [x] the seeder reproduces the db this machine runs byte for byte (verified
      against the live `~/.config/easyeffects/db/`)
- [x] both install paths call it: the home-manager unit's `ExecStartPre` and
      `duo speaker-dsp install`

### H. Documentation

- [x] README (install, customise, commands, troubleshooting), this plan,
      HARDWARE, FEATURES, DESIGN, the install guide, CONTRIBUTING, CHANGELOG,
      CLAUDE.md for agents; research archive with the original master plan

### I. Tests and CI

- [x] `tests/test-lib.sh`: the pipefail/SIGPIPE regression, feature switches,
      GRUB param add/remove, `install_conf`, the config reader
- [x] python unit tests: layout maths without a Mutter (every case a real
      rejection or failure once), the speaker chain, the override marker, the
      HID ioctl numbers and descriptor parser
- [x] CI: bash syntax, shellcheck, tests under sudo, dry runs on a non-Duo
      runner, unit tests with and without PyGObject, `nix flake check`, gitleaks

### J. dome consumes this repo

- [x] `flake.nix` gets the `zenbook-duo` input; the host profile imports the
      module and sets `repoPath` to the checkout
- [x] `system/40-zenbook-duo.sh` clones the repo if missing and runs
      `install.sh --system --dev`; the five Duo scripts, `duo/`,
      `modules/zenbook-duo/` and the Duo docs are deleted from dome
- [x] README, CLAUDE.md, CI and the orchestrator lose their Duo sections

### K. ⛔ Verify on hardware

- [x] the packaged CLI reaches Mutter over D-Bus (`duo top --dry-run`)
- [x] `duo doctor`, `duo features`, `duo speaker-dsp status` from the checkout
      agree with the live machine
- [x] `sudo ./install.sh --system --dev` on the author's machine repoints
      `/usr/local/bin/duo` (done 2026-09-05: `/usr/local/lib/zenduo` is the checkout)
- [ ] `home-manager switch` in dome regenerates the units against the checkout;
      `systemctl --user restart duo-*`; dock/undock, brightness keys,
      second-screen key, resume — the graduation protocol, once more

### L. Publish

- [x] github.com/JowiAoun/linux-on-zenbook-duo, public
- [ ] CI green (the first runs failed on shellcheck, then on the SIGPIPE
      demonstration under a runner that ignores SIGPIPE — both fixed 2026-09-05)
- [ ] tag `v0.9.0` once K is complete

---

## Part 2 — the roadmap

Priority is roughly the order below; each phase has a gate that says what
"done" means. Nothing here is promised on a date.

### M. Distro matrix

Ubuntu is the only tested distro. The installer already knows Fedora and Arch
package names; the rest of the path (GRUB regeneration, sudoers, udev) is
standard. *Gate:* a fresh install of each on a Duo with `duo doctor` clean and
the graduation protocol passed. Wanted: Fedora Workstation, Arch (+ an AUR
package, phase V), Debian 13, Ubuntu 26.04.

### N. Desktop matrix

The display features talk to Mutter's D-Bus API. Abstract `displayctl` behind a
backend (`mutter`, `kscreen-doctor` for KDE, `wlr-randr` for wlroots, `xrandr`
for X11 as a fallback) and make `watch-displays` pick one. Touch mapping is
GNOME-only today (dconf); KDE has its own. *Gate:* the dock policy passes the
protocol on KDE Plasma 6 Wayland. Fmstrat's KDE fork is a behavioural
reference (GPL: no code).

### O. Rotation

`watch-rotation` logs orientation and applies nothing. The policy to write:
tent and book modes (one panel each, rotated), portrait (both panels rotated,
stacked side by side), and "which panel is up". Must compose with the dock
policy — the keyboard cannot be docked in tent mode, so the bottom panel is
free. *Gate:* rotate through all four orientations with a pen on both panels
and touch landing on the right one.

### P. Touch and pen

`set-tablet-mapping` writes the GNOME 46 dconf keys per digitizer. Verify with
a pen on both panels, add `toggle-bottom-touch` for palm resting while
drawing, and re-apply the mapping automatically when Mutter's monitor serials
change. *Gate:* acceptance tests I-10..I-12 from the original plan.

### Q. The rest of the Fn row

Working: brightness, second-screen, keyboard backlight, volume/mute (native);
mic-mute (`5a 7c` → `wpctl`) and emoji (`5a 7e` → `ibus emoji`) since
2026-09-05, mapped from their hid-asus codes and still to be confirmed on the
keycaps. Captured but unmapped: Fn-lock (`5a 4e`), display-switch,
camera-toggle, MyASUS — `5a 3d` and `5a 9c` are in the journal unattributed.
Map them to GNOME actions (display-switch to a `duo layout` cycle). Fn-lock
needs the layer swap to be *performed*, not just seen. *Gate:* every key in
`duo fn-map` does something, on USB and Bluetooth.

### R. Upstream kernel watch

`hid-asus` has no entry for `0b05:1b2c` / `1b2d`. Work-in-progress patches
exist (Luke Jones, Josh Leivenzon). When one lands: `duo doctor` already
reports a native backlight LED, and `watch-fn` should defer to the kernel's
key events for anything the kernel now handles. Consider contributing the
17-byte USB feature-report finding upstream. *Gate:* on a kernel with the
entry, `duo kb-init` is a no-op and the keys still work.

### S. Audio

- EasyEffects 7 (the Ubuntu apt package) keeps settings in GSettings, not the
  db; `duo speaker-dsp install` ships the preset and says how to load it.
  Add the autoload entry for the speaker device so it is automatic there too.
- A corrective EQ measured with a calibrated mic rather than the internal
  DMIC — the current response curve is a shape, not a calibration.
- Microphone chain (noise suppression) for calls.
*Gate:* the chain is active after a reboot on apt EE 7, Flatpak EE 8 and Nix
EE 8, with `duo speaker-dsp status` agreeing.

### T. Power

- `duo profile quiet|balanced|performance` over `platform_profile` (present,
  not yet wired), with a key or a Quick Settings toggle.
- Measure s2idle drain overnight and through a lid-closed 30 min; document
  the numbers and the wakeup sources worth disabling.
- Battery limit already sticks; expose the "charge to 100 % once" escape.
*Gate:* numbers in HARDWARE.md, a profile switch that shows in `duo status`.

### U. Windows-parity conveniences (ScreenXpert-like)

The things people miss from Windows that are not hardware: an on-screen
keyboard on the bottom panel when the keyboard is detached (GNOME's OSK
appears already — make it land on the bottom panel), a launcher/dock on the
bottom panel, "throw this window to the other panel" shortcuts, a `duo layout`
cycle bound to the display-switch key (both / top / bottom / external only).
*Gate:* each one demonstrably works without touching a mouse.

### V. Packaging

A `.deb` (the install is a copy plus config files), an AUR package, the
Flathub question (no: it needs udev and sudoers), and a nixpkgs submission
once 1.0 is out. *Gate:* `apt install ./linux-on-zenbook-duo_*.deb` on a
clean Ubuntu equals `./install.sh --system`.

### W. A settings surface

`duo features` and the config file are enough for a terminal. A GNOME Shell
extension or a small GTK window with the same toggles would make it usable
by people who never open one. *Gate:* every feature and knob is reachable from
it, and it does nothing the CLI cannot.

### X. Diagnostics

`duo report` bundles doctor, status, journals and HID descriptors. Add a
privacy pass (no serials by default), a `--since` window, and an issue
template that asks for it. Consider `duo doctor --json` for a hardware
matrix people can contribute to. *Gate:* a bug report from a stranger is
diagnosable without a second round trip.

### Y. Testing

Hardware cannot be simulated, but the layout maths, the HID parsing and the
config plumbing can. Grow the unit tests toward `watch_displays.converge` with
a fake Mutter (record real `GetCurrentState` payloads as fixtures), and keep a
hardware test checklist that a release must pass on at least two machines.
*Gate:* every bug fixed after 0.9.0 comes with a test that failed before it.

### Z. 1.0

1.0 means: two or more Duos have run it through the protocol; Ubuntu 24.04
and 26.04 plus one non-Ubuntu distro pass `duo doctor` clean; the Fn row is
complete; rotation and touch are verified; the audio chain is automatic on
every EasyEffects packaging; the interfaces (`duo` subcommands, config keys,
home-manager options) have not changed for a release cycle. Then the
interfaces are frozen and semantic versioning starts to mean something.

---

## What is deliberately out of scope

- IR face unlock (Howdy on new Intel IR stacks is unreliable — revisit after 1.0)
- The NPU (works with a firmware blob; no daily-driver need)
- Hibernation (s2idle machine; encrypted-swap complexity not worth it)
- ScreenXpert's six-finger virtual keyboard gesture layer (no Linux equivalent;
  phase U covers the useful part)
- Any EC / keyboard-MCU / panel firmware flashing from Linux — never
