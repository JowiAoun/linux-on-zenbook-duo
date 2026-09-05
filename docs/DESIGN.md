# Design

## Architecture

Two halves, one CLI.

- **Root half** (`system/`): idempotent bash scripts, one per concern, run by
  `install.sh` through `system/run.sh`. They install files and rules; they
  never run daemons. Every script honours `DRY_RUN=1`, reads its feature
  switch from `ZENDUO_<NAME>`, and reports "up to date" on a second run.
- **User half**: `duo` and the python daemons under `lib/`, run as your user
  from systemd user units. Knobs come from `~/.config/zenduo/zenduo.conf`,
  handed to the daemons as environment by `duo`, so the home-manager module
  can set exactly the same values on its units.
- **The only privileged code** is `helper/zenduo-helper`: two verbs, every
  byte of input validated, granted by a sudoers rule scoped to that one path
  for one account. The HID work runs unprivileged through a udev `uaccess`
  ACL on the keyboard's hidraw nodes.

Features are systemd user units; `duo features` reads their state and
`duo enable/disable` changes it. System features are installer flags. The
home-manager module generates the same units declaratively and marks them
`[hm]` in `duo features`.

## Rules

1. **Fail-safe.** `displayctl` refuses any configuration with zero enabled
   panels; display changes use Mutter's *temporary* apply so a broken layout
   never survives a session restart. There is a second reason for temporary,
   verified on hardware 2026-07-23: a persistent `ApplyMonitorsConfig` makes
   gnome-shell raise "Keep display settings?" every time, which a daemon that
   applies on every dock, undock and resume cannot live with.
2. **Native first.** Every capability probes the kernel interface before using
   a userspace fallback (`/sys/class/leds/asus::kbd_backlight` before the HID
   report), so newer kernels automatically shrink this project.
3. **Poll, don't storm.** Keyboard presence is polled from sysfs at 1 Hz with
   a 2-sample debounce; no udev triggers on the pogo-pin device forest.
4. **Mutter's D-Bus, not xrandr or gnome-monitor-config.** The same API GNOME
   Settings uses.
5. **Converge, don't toggle.** `watch-displays` compares the layout the
   machine *should* have with the one it *has* on every wake-up (poll,
   `MonitorsChanged`, resume) rather than acting only on dock/undock edges,
   because resume makes Mutter re-read `monitors.xml` while the keyboard
   never moves. A deliberate `duo top/bottom/both/toggle` outranks the policy
   until the next dock or undock.
6. **Govern one panel, not the layout.** The daemon decides exactly one thing:
   whether the bottom panel is on. Top panel, externals, their positions,
   scales and primary stay the user's. The bottom-off rule is continuous; the
   bottom-on rule fires once, at the undock edge. Mirrored layouts are left
   alone.
7. **The bottom panel follows the top one.** Undocking brings it back only
   when the laptop's own display is in use; on external-only it stays dark.
8. **Prove it, don't assume it.** A hidraw write that returns success proves
   only that *some* interface accepted *some* bytes. `kb-init` reads the
   handshake back before reporting success, and addresses the vendor
   collection structurally rather than by trying nodes until one stops
   erroring. Believing the first "success" is what left the media keys dead
   while every log line claimed the init had worked.
9. **Minimal privilege.** See above.
10. **Everything observable.** Every state transition goes to the journal
    (`duo log`); a key that silently did nothing is indistinguishable from a
    key that never arrived, so spawned commands' stderr is captured and
    reported.

## Traps that already bit, do not repeat

- `cmd | grep -q` under `pipefail` returns 141 on a writer with more output
  than grep read — a successful match reported as failure. Capture first,
  match with `out_matches`. Shipped twice before it was understood.
- `/proc/uptime` counts suspend; `*TimestampMonotonic` does not. Their
  difference on this laptop is an age plus every second ever spent asleep.
  Use wall time on both sides.
- EasyEffects: the db stores enums as **integers**, the preset as labels. Seed
  a label into the db and EE silently keeps the plugin default — for Filter a
  *low-pass*. `filter.slope` unset is a no-op that measures flat. `gainBoost`
  on the limiter defaults on and turns a −1 dB ceiling into 0 dBFS.
- home-manager writes a bare Nix integer to dconf as int32; a `u` key then
  silently falls back to the schema default. Wrap with `mkUint32`.
- `sudo VAR=1 ./script` loses `VAR` to `env_reset`. Flags, not variables, for
  anything that must reach a root script.

## Graduation protocol

A feature is ✅ only after, on real hardware: 10× attach/detach cycles ·
survives suspend/resume · survives reboot · survives a session restart (log
out/in) · no errors in `duo log`. Record the date in FEATURES.md.

## Licensing

MIT. Fmstrat/zenbook-duo-linux is GPL-3.0: read for behaviour, never copy.
alesya-h/zenbook-duo-2024-ux8406ma-linux is BSD-2-Clause: adapting a snippet
is allowed with the attribution block in that file; the default is an original
implementation. Kernel constants are facts.
