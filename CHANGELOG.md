# Changelog

## Unreleased

- `duo status`, `duo doctor` and `watch-fn` report a docked keyboard whose USB
  link enumerated but failed to configure (`can't set config #1, error -71`;
  seen 2026-09-05) and say to re-seat it; `watch-fn` no longer goes silent
  when the keyboard vanishes
- `watch-fn`: mic-mute (`5a 7c`, via `wpctl`) and emoji (`5a 7e`, via
  `ibus emoji`), mapped from their hid-asus codes — keycaps to be verified
- `duo log` now shows the daemons: every unit logs under the `zenduo`
  identifier and nothing is logged twice (units from before this need a
  re-install or `home-manager switch`; `duo log` follows the old identifier too)
- `sudo ./install.sh --dry-run` no longer runs the user half for real, and
  `--battery-limit`, `--speaker-dsp`, `--prefix` and the `--watch-*` switches
  reach it
- `./install.sh --user` stands down on a home-manager machine instead of
  writing units beside the module's; `bat-limit` is no longer re-enabled on
  every run
- `./uninstall.sh --prefix` without a value is a usage error
- CI: the SIGPIPE demonstration accepts exit 1 (GitHub's runners ignore
  SIGPIPE), so the workflow can pass; `actions/checkout@v5`

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
