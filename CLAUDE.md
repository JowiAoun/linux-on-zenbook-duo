# CLAUDE.md — agent guide for linux-on-zenbook-duo

Read [docs/DESIGN.md](docs/DESIGN.md) first: the rules there are not style,
they are the shape of bugs that already shipped. The short version, with the
ones that are easiest to reintroduce:

## Never write `cmd | grep -q` in a script

`system/lib.sh` sets `pipefail`, and `grep -q` exits at the **first match**,
which SIGPIPEs a writer that still has output to produce. The pipeline then
returns 141 and a successful match is reported as a failure. It is a race
against the writer's buffering, not a size threshold. Capture, then match:

```bash
out_matches "$(lsblk -no TYPE --inverse "$src")" -x crypt     # not: lsblk … | grep -qx crypt
```

`tests/test-lib.sh` proves the hazard is real on the machine it runs on.

## Never subtract a systemd `*TimestampMonotonic` from `/proc/uptime`

This laptop suspends. `/proc/uptime` is `CLOCK_BOOTTIME` (counts suspend);
`ActiveEnterTimestampMonotonic` is `CLOCK_MONOTONIC` (does not). Their
difference is an age plus every second ever spent asleep. `lib/watch_fn.py`
uses exactly this gap *on purpose* to detect a resume — that is the only
legitimate use. For an age, use wall time on both sides.

## EasyEffects enums are integers in the db and labels in the preset

Seed a label into `~/.config/easyeffects/db/*rc` and EasyEffects silently
keeps the plugin default — for Filter a *low-pass*. `lib/speaker_dsp.py` is
the one definition; change numbers there, run `make preset`, and the test
that compares the committed preset will tell you if you forgot.

## A HID write that "succeeds" proves nothing

Several of the keyboard's six interfaces accept feature reports and drop
them. `lib/kb_init.py` addresses the vendor collection structurally and reads
the handshake back. Do not "simplify" it into "try nodes until one works" —
that is how the media keys were dead while the log said they worked.

## Do not flash firmware, ever

No EC, keyboard-MCU or panel firmware from Linux. No `--no-sandbox`, no
`chmod 4755` shortcuts either; the project's answer to a permission problem
is the udev rule and the 50-line helper.

## Layout and how to check your work

```
bin/duo            CLI, bash. Subcommands dispatch to lib/*.py or do sysfs work inline.
lib/*.py           daemons + helpers. stdlib only, except displayctl/watch_displays (PyGObject,
                   run with $DUO_PYGI = /usr/bin/python3 on Ubuntu because a Nix/pyenv python has no gi).
lib/conf.sh        the config reader, sourced by bin/duo (parsed, never sourced).
system/*.sh        root half. Each: source lib.sh; require_root; feature_on NAME default; idempotent; DRY_RUN.
systemd/user/      unit templates install.sh copies; nix/home-manager.nix generates its own.
nix/               flake + package + module. `nix flake check` builds and evaluates everything.
tests/             make test. Add a test with every fix in a testable layer.
docs/              PLAN (A–Z) · HARDWARE (facts + how established) · FEATURES (parity) · DESIGN · install/
```

- `make test && make lint` before committing; `nix flake check` if `nix/` changed.
- `./install.sh --dry-run` must run clean on a machine that is not a Duo
  (CI does this); `./install.sh --system` must refuse one without `--force`.
- Every comment that states hardware behaviour says how it was established:
  measured (date), read from a named source file, or **VERIFY-ON-HW**.
- Commits: `type(scope): imperative summary`, body says why.
- Prior art: alesya-h (BSD-2, adapt with attribution) and Fmstrat (GPL-3,
  read only, never copy).
