# Contributing

Bug reports from other Duos are the most valuable thing you can send.

## Reporting

```bash
duo report > zenduo-report.txt      # doctor + status + features + journals + HID descriptors
```

Attach it to the issue with: what you did, what you expected, what happened,
and whether the keyboard was docked or on Bluetooth. For a media-key problem,
also `duo fn-probe` output for the key. For a display problem, `duo log`
around the moment it went wrong. Serial numbers in the report are the panel
EDID serials; redact them if you like.

## Developing

```bash
./install.sh --dev              # /usr/local/lib/zenduo -> this checkout; edits are live
systemctl --user restart duo-watch-displays duo-watch-fn   # a running daemon has its code loaded
make test                       # bash + python unit tests (sudo make test for the root-only cases)
make lint                       # bash -n, shellcheck, py_compile
nix flake check                 # if you touch nix/
```

Conventions, in order of how much they have cost:

- **Never `cmd | grep -q`** in a script with `pipefail`. Use `out_matches`
  ([DESIGN.md](docs/DESIGN.md#traps-that-already-bit-do-not-repeat)).
- Every system script is idempotent and honours `DRY_RUN=1`. A second run
  must say "up to date".
- Every behavioural claim in a comment says how it was established: measured
  (date), read from source (which file), or **VERIFY-ON-HW**.
- A feature is ✅ in FEATURES.md only after the graduation protocol in
  DESIGN.md, on real hardware.
- A bug fix comes with the test that failed before it, where the layer is
  testable (layout maths, HID parsing, config, the speaker chain). Hardware
  behaviour goes in HARDWARE.md instead.
- Commit messages: `type(scope): imperative summary`, with a body that says
  why. `feat` and `fix` only for user-visible behaviour.

## Licensing

MIT. Do not copy code from Fmstrat/zenbook-duo-linux (GPL-3.0). Adapting from
alesya-h/zenbook-duo-2024-ux8406ma-linux (BSD-2-Clause) is fine with its
attribution notice in the file. Kernel constants are facts.
