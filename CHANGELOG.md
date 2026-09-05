# Changelog

## 0.9.0 — 2026-09-05

Extracted from [JowiAoun/dome](https://github.com/JowiAoun/dome) after six
weeks of daily use, with the history of every Duo file carried over.

New since the dotfiles era:

- `./install.sh` / `./uninstall.sh`: a standalone install with no Nix and no
  `user-config.nix`, `--dry-run`, `--dev`, feature flags for every system
  piece; distro detection for apt, dnf and pacman
- `~/.config/zenduo/zenduo.conf` and `duo config`, `duo features`,
  `duo enable`, `duo disable`, `duo report`, `duo version`
- `duo speaker-dsp`: the EasyEffects chain as one Python definition used by
  both the Nix module and the plain install; the committed preset is generated
  from it and tested against it
- `DOCK_POLICY` and `KB_BACKLIGHT_RESTORE` knobs
- a Nix flake: `packages.zenduo` (runs with `nix run`) and
  `homeManagerModules.default` with `package`, `repoPath`, `dockPolicy`,
  `kbBacklightRestore`, `writeConfig` options
- `duo doctor` reports the model, kernel ≥ 6.11, PyGObject, amp state and
  the install state; the layout maths no longer needs PyGObject to import
- tests (bash + python) and CI (shellcheck, dry runs, unit tests with and
  without PyGObject, `nix flake check`, gitleaks)
- documentation: README, the A–Z plan, HARDWARE, FEATURES, DESIGN, the
  dual-boot install guide

Unchanged, and still the point: the dock policy, the keyboard handshake and
media keys, the backlight, the battery limit, the touchpad quirk, the PSR fix,
the amp reporter — all as verified on hardware in July 2026.
