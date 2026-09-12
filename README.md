# Linux on the ASUS Zenbook Duo (2024)

Everything Windows does on the Zenbook Duo UX8406MA that Linux does not do
out of the box, as one installable, customisable project: the bottom screen
switches off when the keyboard is docked on it and back on when you lift it,
the detachable keyboard's Fn/media row and backlight work over USB and
Bluetooth, the speakers get the voicing they have under Windows, the battery
charge limit sticks, the touchpad rejects your palm while you type, and the
OLED flicker is gone.

[![ci](https://github.com/JowiAoun/linux-on-zenbook-duo/actions/workflows/ci.yml/badge.svg)](https://github.com/JowiAoun/linux-on-zenbook-duo/actions/workflows/ci.yml)

> **Status:** in daily use since July 2026 on Ubuntu 24.04 (GNOME, Wayland),
> extracted from a personal dotfiles repo in September 2026. Pre-1.0: the
> interfaces may still move, and only one machine has run it so far. If you
> have a Duo, please try it and open an issue with `duo report` attached —
> the goal is to support as many Duos, distros and desktops as possible.
> See [docs/PLAN.md](docs/PLAN.md) for where this is going.

## What works

| Feature | Windows | Here | Verified |
|---|---|---|---|
| Bottom panel off while the keyboard is docked, on when lifted; survives suspend, hotplug, lock, GNOME Settings changes | ScreenXpert | `duo watch-displays` | ✅ on hardware, daily since 2026-07-23 |
| Manual panel control that never blanks the machine; Win+P layouts (external only, mirror) are respected | Win+P | `duo top/bottom/both/toggle` | ✅ |
| Fn/media keys: brightness (with GNOME's OSD, both panels), second-screen key, keyboard-backlight key; volume/mute are native | ASUS driver | `duo watch-fn` (sends the same handshake the kernel driver would) | ✅ USB and Bluetooth |
| Keyboard backlight 0–3, remembered and restored after dock/undock/resume | ASUS driver | `duo kb-backlight` | ✅ |
| Bottom panel brightness follows the top panel | ASUS driver | brightness keys, `duo sync-backlight`, optional `duo watch-backlight` | ✅ |
| Battery charge limit (e.g. 80 %) re-applied at every login | MyASUS | `duo bat-limit`, `BATTERY_LIMIT` in the config | ✅ |
| Speaker voicing: high-pass, bass psychoacoustics, staged compressor, limiter | harman/kardon APO | `duo speaker-dsp` (EasyEffects chain, one definition for Nix and non-Nix) | ✅ measured, see [nix/audio.nix](nix/audio.nix) |
| Loud notice when the speaker amps come up unprotected after a Windows Fast-Startup boot | — | `duo-cs35l41-check` system service | ✅ |
| Palm rejection on the detachable touchpad while typing | ASUS driver | libinput quirk + GNOME's disable-while-typing | ✅ |
| No OLED flicker | ASUS driver | `i915.enable_psr=0` on the kernel command line | ✅ |
| Touch/pen mapped to the right panel | Windows | `duo set-tablet-mapping` (GNOME 46+) | 🧪 written, not yet verified with a pen |
| Auto-rotation (tent, book, portrait) | ScreenXpert | `duo watch-rotation` | 🧪 logs orientation only |
| Read-only hardware probe, safe on a live USB — the install gate | — | `duo doctor` | ✅ |

The full Windows-parity matrix, including what is deliberately out of scope,
is in [docs/FEATURES.md](docs/FEATURES.md).

## Requirements

- **ASUS Zenbook Duo (2024) UX8406MA.** Later variants (UX8406CA) share the
  chassis and most of this should apply; report what does not.
- **A kernel ≥ 6.11.** Below that, detaching the keyboard sends a spurious
  rfkill press that kills Wi-Fi. Ubuntu 24.04.4 and 26.04 ship 7.0.
- **GNOME on Wayland** for the display features (they talk to Mutter's
  `org.gnome.Mutter.DisplayConfig`, the same API GNOME Settings uses; GNOME 46
  or newer for touch mapping). Keyboard, backlight, battery and audio work on
  any desktop. Other compositors are on the roadmap (docs/PLAN.md, phase N).
- **Tested on Ubuntu 24.04.4 LTS.** The installer also knows Fedora and Arch
  package names, untested — see [docs/PLAN.md](docs/PLAN.md) phase M.

## Install

```bash
sudo apt install -y git            # the one prerequisite on Ubuntu
git clone https://github.com/JowiAoun/linux-on-zenbook-duo ~/linux-on-zenbook-duo
cd ~/linux-on-zenbook-duo
./install.sh                       # asks for your password once; safe to re-run
```

That does two things, both idempotent (a second run reports "up to date"):

1. **Root half** (`sudo`, [system/](system/)): installs the few packages the
   tooling needs (`python3-gi`, `iio-sensor-proxy`, `inotify-tools`, …), on
   Ubuntu keeps the HWE kernel plus the GA kernel as a fallback, adds
   `i915.enable_psr=0` to GRUB, puts `duo` at `/usr/local/bin/duo`, installs
   the udev rules that let the keyboard tooling run unprivileged, a 50-line
   root helper with a sudoers rule scoped to that one binary, the libinput
   palm-rejection quirk, and the speaker-amp reporter.
2. **User half** (you, no root): writes `~/.config/zenduo/zenduo.conf`,
   installs the `duo-*` systemd user units, and starts the default features
   (`watch-displays`, `watch-fn`).

Preview everything without changing anything: `./install.sh --dry-run`.
Every flag: `./install.sh --help`. Reboot if the kernel or GRUB changed.

**Before installing on a fresh machine**, or from a live USB, run the
read-only probe — it is the gate the whole project was installed behind:

```bash
bin/duo doctor        # no dependencies beyond bash; safe anywhere
```

Installing Ubuntu next to Windows on this machine has its own traps (five
factory partitions, BitLocker, a shrink wall at `$MFT`, an installer that
cannot use a pre-made LUKS container). They are written up in
[docs/install/](docs/install/README.md).

## Customise

Everything is a feature you can turn on or off, or a knob you can set.

```bash
duo features                       # what is installed, enabled, running
duo enable watch-backlight         # start a feature now and at every login
duo disable watch-fn
duo config                         # the effective knobs
duo config set BATTERY_LIMIT 80    # then: duo enable bat-limit
```

Knobs live in `~/.config/zenduo/zenduo.conf` ([annotated example](config/zenduo.conf.example)):

| Key | Default | What |
|---|---|---|
| `APPLY_METHOD` | `temporary` | How layouts are handed to Mutter. `persistent` was verified on hardware and rejected as a daemon default: GNOME asks "Keep display settings?" on every dock, undock and resume |
| `BATTERY_LIMIT` | empty | Charge-limit percentage (20–100) the `bat-limit` feature applies at login |
| `BACKLIGHT_SOURCE` / `BACKLIGHT_TARGET` | `intel_backlight` / auto | Which backlight brightness is copied from and to |
| `KB_BACKLIGHT_RESTORE` | `1` | Restore the keyboard backlight level after the keyboard re-enumerates |
| `DOCK_POLICY` | `1` | `0` keeps `watch-displays` running but makes it watch without acting |
| `REMEMBER_LAYOUT` | `1` | Remember the display layout per set of connected monitors and let GNOME restore it (see below) |
| `LOGIN_SCREEN_LAYOUT` | `1` | Give the GDM greeter the same layouts, so the password prompt is on the monitor you were using |

System-level features are flags on the installer, so they can be switched
later with the same command that installed them:

```bash
sudo ./install.sh --system --no-psr-fix          # keep Panel Self Refresh on
sudo ./install.sh --system --no-palm-rejection
sudo ./install.sh --system --no-amp-check
sudo ./install.sh --system --no-hwe-kernel        # Ubuntu: leave the kernel alone
```

The speaker chain is opt-in — the numbers are measured on one unit and
documented, but taste is yours:

```bash
./install.sh --user --speaker-dsp     # or: duo speaker-dsp install
duo speaker-dsp status
```

## The layout comes back, like it does on Windows

Windows keeps a display configuration for each *set* of connected monitors and
restores it when that set comes back. GNOME has the same database and restores
it just as early — but it only ever wrote it when you went through Settings and
clicked "Keep changes". A layout chosen with Super+P was forgotten the moment
the connectors were re-probed, so opening the lid on an external-monitor setup
came back to GNOME's fallback (every screen on, laptop panel primary) and the
password prompt appeared on the laptop screen.

So `duo watch-displays` records it. Whatever is on screen when things settle
becomes the layout for the monitors that are connected, written into GNOME's
own `~/.config/monitors.xml` — no re-apply, so no flicker and no "Keep display
settings?" countdown, and GNOME restores it before anything is drawn. Plug the
monitor back in tomorrow and you get the same screens, positions, scales and
primary. Unplug it and you get the layout you use without it.

```bash
duo layout                  # what is on screen, what comes back, the login screen
duo layout external         # the four Win+P layouts, remembered as you pick them
duo layout cycle            # step through them, Windows' order
duo layout forget           # stop remembering this particular monitor set
```

The greeter runs its own session with its own copy of that file, which is why
the sign-in prompt used to sit on the laptop panel regardless. After a layout
changes, the same layouts are installed for it (`LOGIN_SCREEN_LAYOUT=1`, via
the root helper — the greeter's own file is kept as
`monitors.xml.zenduo-backup` and `./uninstall.sh --system` puts it back).

Two things are deliberately not remembered: a layout you nudged with
`duo top/bottom/both/toggle` or the second-screen key, because those lapse at
the next dock change by design, and anything applied while the daemon is
backing off from a layout fight. `REMEMBER_LAYOUT=0` turns the whole thing off
and leaves `monitors.xml` alone.

## Commands

```
duo doctor                 full read-only hardware probe — safe anywhere, incl. a live USB
duo status                 quick glance: panels, keyboard, backlight, battery limit
duo features               every feature with its installed/enabled/running state
duo enable|disable <f>     turn a feature on/off (and start/stop it now)
duo config [get K|set K V] the knobs in ~/.config/zenduo/zenduo.conf
duo top|bottom|both        enable that panel set (refuses to disable everything);
                           pauses the dock policy until the keyboard docks/undocks
duo toggle                 bottom panel on <-> off, leaving every other output alone
duo layout [show]          what is on screen, what comes back, and where the login screen is
duo layout laptop|external|extend|mirror     the four Win+P layouts, remembered
duo layout cycle           step through those four in Windows' order
duo layout remember|forget record what is on screen / drop it for these monitors
duo layout login           give the login screen the same layouts (needs the root helper)
duo watch-displays         daemon: bottom panel off while docked, back on when lifted
duo apply-displays         enforce that policy once, now (drops any manual override)
duo sync-backlight         copy the top panel's backlight percentage to the bottom panel
duo watch-backlight        daemon: keep the bottom backlight synced
duo kb-init                send the ASUS handshake that enables Fn/media-key reporting;
                           only reports success if the keyboard echoes it back
duo watch-fn               daemon: re-init the keyboard on connect/resume + act on media keys
duo kb-backlight 0..3      keyboard backlight — native LED if the kernel has it, else HID
duo kb-backlight --show    print the remembered level
duo bat-limit [20..100]    battery charge-limit threshold (no value = the config's)
duo speaker-dsp <cmd>      install | status | uninstall | seed | preset
duo set-tablet-mapping     pin each ELAN touchscreen to its own panel (GNOME 46+)
duo watch-rotation         EXPERIMENTAL: log accelerometer orientation events
duo fn-probe               inventory what the Fn keys actually emit (raw hex)
duo fn-map [--show]        guided wizard: press each key -> key->report map
duo watch-input            (root) decode key events from the keyboard + Asus WMI hotkeys
duo report                 doctor + status + journals, for a bug report
duo log                    follow the zenduo journal
```

## Nix and home-manager

The repo is a flake. The package runs on any machine with Nix:

```bash
nix run github:JowiAoun/linux-on-zenbook-duo -- doctor
```

The home-manager module generates the same user units and config
declaratively (the root half is still `sudo ./install.sh --system` once from
a checkout — home-manager cannot write udev rules):

```nix
# flake.nix
inputs.zenbook-duo = {
  url = "github:JowiAoun/linux-on-zenbook-duo";
  inputs.nixpkgs.follows = "nixpkgs";
};
# a home-manager module
{ inputs, ... }: {
  imports = [ inputs.zenbook-duo.homeManagerModules.default ];
  zenduo = {
    enable = true;
    batteryLimit = 80;
    speakerDsp = true;      # also installs EasyEffects from nixpkgs
    # repoPath = "/home/me/linux-on-zenbook-duo";   # run the daemons from a live checkout
  };
}
```

All options: [nix/home-manager.nix](nix/home-manager.nix). A full host example:
[nix/examples/host.nix](nix/examples/host.nix). This is how the author's
dotfiles ([JowiAoun/dome](https://github.com/JowiAoun/dome)) consume it.

## Troubleshooting

- **The wrong layout comes back after opening the lid, or the password prompt
  is on the wrong screen.** `duo layout` says what is remembered for the
  monitors you have connected. If it says nothing is, choose the layout you
  want once (`duo layout external`, GNOME Settings, or Super+P) and it is
  recorded. If the sign-in screen is still wrong, `duo layout login` installs
  the layouts for the greeter and reports why if it cannot — that needs
  `sudo ./install.sh --system` once, for the root helper.
- **Bottom screen stays lit under the docked keyboard.** `duo status` says
  whether the dock policy is paused by a manual layout (`duo apply-displays`
  resumes it) and whether `duo-watch-displays` is running (`duo features`).
- **Keyboard stops working while docked; `duo status` says its USB link is
  DEAD.** It enumerated but the kernel could not configure it (`journalctl -k`
  shows `can't set config #1, error -71`, usually after a burst of xhci
  resets). Lift it off the pogo pins and re-seat it — nothing in software
  recovers that link. `duo doctor` and `duo log` name the state.
- **Media keys do nothing.** `duo log` while pressing one. "hotkey mode not
  confirmed" means the handshake never landed — re-dock the keyboard; if it
  persists, `duo fn-probe` and attach the output to an issue. `duo toggle`
  saying *python3-gi missing*: your `python3` is a Nix/pyenv one; `duo` pins
  `/usr/bin/python3`, set `DUO_PYGI` if yours lives elsewhere.
- **Sound is harsh and distorted after booting from Windows.** The CS35L41
  amps failed their power-up handshake; you get a desktop notification. Shut
  down fully (not a reboot). To stop it recurring, disable Fast Startup in
  Windows: `powercfg /h off` as Administrator. Details:
  [docs/HARDWARE.md](docs/HARDWARE.md#speakers).
- **Wi-Fi drops when the keyboard is detached.** Kernel < 6.11. `duo doctor`
  warns about it.
- **Pairing the keyboard over Bluetooth.** Detach it, slide the switch on its
  left edge on, then **hold F10 for 4–5 s** until the light flashes blue
  rapidly — the switch alone does not advertise. Remove any stale Windows
  pairing first.
- **Anything else:** `duo report > report.txt` and open an issue with it.

## Repository layout

```
bin/duo                  the CLI (bash); every feature is a subcommand
lib/*.py                 the daemons and helpers (python3, stdlib + PyGObject for Mutter)
lib/conf.sh              the config-file reader
helper/zenduo-helper     the ONLY root code: two validated verbs, 50 lines
system/                  the root half: idempotent scripts + lib.sh, run by install.sh
systemd/user/            the duo-* user units install.sh copies into place
config/                  annotated zenduo.conf example
presets/easyeffects/     the speaker preset, generated from lib/speaker_dsp.py
nix/                     flake package + home-manager module
tests/                   bash + python unit tests (make test)
docs/                    PLAN (A–Z), HARDWARE, FEATURES, DESIGN, install guide, research
```

Design rules — fail-safe, native-first, poll-don't-storm, prove-don't-assume —
are in [docs/DESIGN.md](docs/DESIGN.md); hardware facts (USB ids, HID report
lengths, backlight devices, the amp story) in [docs/HARDWARE.md](docs/HARDWARE.md);
the plan from here to 1.0 and beyond in [docs/PLAN.md](docs/PLAN.md).

## Prior art and licensing

MIT (see [LICENSE](LICENSE)). This is an original implementation that owes
its feature list to two projects worth crediting:

- [alesya-h/zenbook-duo-2024-ux8406ma-linux](https://github.com/alesya-h/zenbook-duo-2024-ux8406ma-linux)
  (BSD-2-Clause) — the original `duo` script; command names stay deliberately
  compatible with it, and the libinput palm-rejection quirk comes from there.
- [Fmstrat/zenbook-duo-linux](https://github.com/Fmstrat/zenbook-duo-linux)
  (GPL-3.0) — behavioural reference only; no code from it is or may be copied
  here (license incompatibility with MIT).

Kernel-derived constants (USB ids, the HID report bytes from `hid-asus.c`)
are facts, not code. History before September 2026 is in
[JowiAoun/dome](https://github.com/JowiAoun/dome), where this was built.
