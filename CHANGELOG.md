# Changelog

## Unreleased

### `duo` is a screen now; the command line is `duo-cli`

- `duo` opens a curses screen (python3 as Ubuntu ships it, nothing else) with
  six views: an overview of the machine and the daemons, the services with
  their restart counts, exit codes and per-unit errors and the keys to
  enable, disable, restart, start and stop them, the settings edited in
  place, the displays with the layout verbs, the doctor, and the journal live
  with per-unit and errors-only filters plus the kernel's Duo lines. Every
  action is a `duo-cli` or `systemctl --user` command and the screen shows
  what it printed
- the bash CLI is `duo-cli`; `duo <command>` still runs it, so scripts, the
  units and the second-screen key keep working. The units, the installer,
  the Nix package and the home-manager module name `duo-cli` directly
- `duo --snapshot [view] [WxH]` prints one frame as text, which is what CI
  and a bug report use

### Sound survives an app that asks for a tiny buffer

- PipeWire sizes the whole graph, the sound device included, from the smallest
  buffer any one client asks for. Roblox asks for 240 frames, the SOF pipeline
  underruns, and PipeWire 1.0.5 cannot reset it from its recovery path. So the
  device stops producing cycles and every other stream goes silent with it,
  browser video included. Thirteen episodes in one day, the longest 167 minutes
- a floor under the buffer prevents it, on by default
  (`zenduo.audioBufferFloor`, `./install.sh --no-audio-buffer-floor` to skip).
  The floor is PipeWire's own default quantum, so nothing runs with a smaller
  buffer than it already did, and Roblox still gets sound at 21 ms of latency
  instead of the 5 ms it asked for. Turn it off for recording or DAW work
- clearing a wedge that has already happened no longer costs the clients their
  streams: `pw-metadata -n settings 0 clock.min-quantum 1024` re-opens the
  device, where restarting PipeWire takes Wine and FMOD clients down with it

### Fixes

- Bluetooth earbuds no longer drop to mono phone quality for every app when
  Discord or a browser opens the microphone: WirePlumber's headset autoswitch
  is off (`zenduo.bluetoothStereo`, `./install.sh --no-bluetooth-stereo` to
  keep Ubuntu's behaviour). `duo doctor` and the Overview name a device that
  is on the headset profile
- PipeWire keeps its realtime priority when the login beats rtkit: a drop-in
  makes pipewire, pipewire-pulse and wireplumber wait for it
  (`zenduo.audioRealtime`), and `./install.sh --user` grants the priority to
  the loops running now
- `c` in the screen's Logs clears the view: it hides every line showing there
  and under Recent problems, and `C` brings them back. It used to clear the
  filter, which looked like nothing happened. Nothing is deleted; the journal
  belongs to journald and duo only reads it
- the rest of the screen's keys: a box scrolls to its last line (a wrapped
  line takes several rows, so the help and a long failure stopped part way),
  PgUp and PgDn step the list that is really on screen, Overview's problem
  list takes the arrow keys and Enter, `l` there opens the same lines in Logs,
  space edits any setting and not only a 0/1 one, and Services says where a
  system unit's journal is instead of switching to an empty Logs view
- the screen stops asking Mutter for the display state once you leave the
  Displays view, and copying the journal while the follower appends to it can
  no longer raise
- Ctrl-C leaves the screen the way `q` does, instead of printing a traceback
  over the terminal it just restored
- `watch-fn` no longer reports "media keys are dead" while the keyboard is
  re-enumerating: it waits for the node set to hold still before sending the
  handshake, names a set that vanished under it, and only raises the alarm
  from the third failed attempt (the first ones after a dock routinely fail
  until the udev rule lands)
- `watch-displays` pushes the login screen layout to a missing or outdated
  root helper once, then leaves it alone until the helper file changes,
  instead of one journal line and one sudo call per layout change
- `duo-cli doctor` and the amp reporter no longer call the speaker amps
  "clean" when the kernel journal is not readable; doctor's kernel log scan
  now reads the journal when `dmesg` is root-only
- the layout memory no longer logs "remembered" and pushes the login screen
  on every settle when the stored entry carries a `maxbpc` or presentation flag
- `watch-displays` keeps its MonitorsChanged subscription after a D-Bus
  failure made it replace the Mutter proxy
- `duo-cli config set` accepts a value with a slash
- `./install.sh --help` and `./uninstall.sh --help` print the header only
- `duo-cli --help` exits 0; `fn-probe` keeps its copy under
  `~/.local/state/zenduo` instead of a fixed name in `/tmp`

### The display layout is remembered, the way Windows remembers it

- the layout is recorded per set of connected monitors and restored by GNOME
  itself before anything is drawn, so opening the lid comes back to the
  screens, positions, scales and primary you last used with those monitors —
  and the lock screen appears on the right one. It goes into GNOME's own
  `~/.config/monitors.xml` (`lib/monitors_xml.py`), which Mutter wrote only
  for Settings' "Keep changes" before this, so a Super+P layout was forgotten
  as soon as the connectors were re-probed. Nothing is re-applied, so there is
  no flicker and no "Keep display settings?" countdown
- the login screen gets the same layouts, through a new validated root-helper
  verb, so the password prompt is no longer stuck on the laptop panel. The
  greeter's own file is kept as `monitors.xml.zenduo-backup` and restored by
  `./uninstall.sh --system`
- `duo layout [show|laptop|external|extend|mirror|cycle|remember|forget|login]`
  — the four Win+P layouts in Windows' cycle order, and what is remembered
- new knobs `REMEMBER_LAYOUT` and `LOGIN_SCREEN_LAYOUT`, home-manager options
  `rememberLayout` and `loginScreenLayout`, both on by default
- plugging a monitor in or out now retires a manual display override, like
  docking does
- `duo apply-displays` also refreshes what is remembered
- `duo status` and `duo doctor` report the layout memory

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
