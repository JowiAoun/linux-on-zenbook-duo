#!/usr/bin/env python3
"""Speaker voicing for the Duo's tiny built-in speakers, as an EasyEffects chain.

ONE definition of the chain (CHAIN below) feeds both things EasyEffects can
read, because they disagree with each other and only one of them works:

  * the db files under ~/.config/easyeffects/db/ — EasyEffects 8 (the Qt
    rewrite) restores its running chain from these on every start. Seeding
    them is the mechanism that works on a fresh machine AND an established
    one; `--load-preset` on the daemon's own argv is a silent no-op when the
    db has never seen the preset. Enums are INTEGERS here.
  * the preset JSON under ~/.config/easyeffects/output/ — what the GUI lists
    and what `easyeffects -l <name>` loads into a running daemon. Enums are
    LABELS here. On EasyEffects 7 (GTK, e.g. the Ubuntu apt package) this is
    the only usable form: its settings live in GSettings, not the db.

Why the chain exists, in one paragraph. Two Cirrus CS35L41 amps run ASUS's
protection firmware — excursion and thermal limiting, not voicing. On Windows
the tonal work happens above the driver in an APO: high-pass, bass
psychoacoustics, corrective EQ, limiter. Linux has no equivalent, so out of the
box the speakers play the raw stream and sound worse than under Windows. The
measured response (third-octave pink noise, internal DMIC) puts the useful
band from ~300 Hz up, with everything below 200 Hz more than 18 dB down: that
content is inaudible but still costs cone excursion, which drags the
protection DSP in and pulls the WHOLE signal down. Removing it is the single
largest available quality win. The full measurements, and the story of the
compressor that made the speakers quieter, are in nix/audio.nix and the git
history of this file's ancestor.

Chain order matters: high-pass FIRST so the dynamics never spend their range
on sub-bass the drivers cannot reproduce; the bass enhancer sits behind it so
it synthesises harmonics of the fundamentals just removed; the compressor is
staged so its net gain is positive at every level; the limiter brickwalls.

Usage (normally via `duo speaker-dsp ...`):
  speaker_dsp.py preset                 print the preset JSON
  speaker_dsp.py seed [--dir D] [-n]    write the db files (EasyEffects 8)
  speaker_dsp.py install [-n]           preset + db, for every EasyEffects found
  speaker_dsp.py status
  speaker_dsp.py uninstall [-n]
Exit: 0 ok · 1 nothing to do / failure · 64 usage.
"""

import json
import os
import shutil
import subprocess
import sys

PRESET_NAME = "duo-speakers"

# EasyEffects 8 rc file names, read back off a real clean exit rather than
# guessed: EE writes `bassEnhancerrc`, not `bass_enhancerrc`.
#
# INTEGER enums in `db`, LABEL enums in `preset`. Filter's own type list is
#   0 Low-pass  1 High-pass  2 Low-shelf  3 High-shelf  4 Band-pass
#   5 Ladder-rejection  6 All-pass
# and slope is 0 = x1 (a NO-OP that measures flat) .. 3 = x4. The db is what
# is verified on hardware; the preset's "x3" label for slope is derived from
# LSP's enum and is the one label here that has not been read back off a real
# EasyEffects save — if it is wrong EE drops the key silently and the preset
# loads with a flat filter, which is what it did before the key was added.
CHAIN = [
    {
        "id": "filter#0",
        "rc": "filterrc",
        "group": "[soe][Filter#0]",
        # 1. High-pass at 120 Hz. Everything below is excursion the drivers spend
        #    for nothing. `slope` is not optional: leave it out and the filter
        #    is a no-op that measures FLAT.
        "db": {"type": 1, "frequency": 120, "slope": 2},
        "preset": {"type": "High-pass", "frequency": 120.0, "slope": "x3"},
    },
    {
        "id": "bass_enhancer#0",
        "rc": "bassEnhancerrc",
        "group": "[soe][BassEnhancer#0]",
        # 2. Bass psychoacoustics, AFTER the high-pass on purpose. `scope` is
        #    the band it works on, `floor` stops it chasing rumble.
        "db": {"amount": 6, "scope": 200, "floor": 40, "floorActive": True},
        "preset": {"amount": 6.0, "scope": 200.0, "floor": 40.0, "floor-active": True},
    },
    {
        "id": "compressor#0",
        "rc": "compressorrc",
        "group": "[soe][Compressor#0]",
        # 3. Downward compressor staged so the net gain is positive EVERYWHERE:
        #    makeup (9) >= the worst-case reduction on real material (7 dB at
        #    -6 dBFS RMS in). 4:1 with 8 dB makeup was the revision that made
        #    the speakers QUIETER on anything louder than -13 dBFS.
        #    releaseThreshold -80 is the plugin's floor, i.e. off.
        "db": {"attack": 10, "release": 150, "threshold": -20, "ratio": 2,
               "knee": -6, "makeup": 9, "releaseThreshold": -80},
        "preset": {"mode": "Downward", "attack": 10.0, "release": 150.0,
                   "release-threshold": -80.0, "threshold": -20.0, "ratio": 2.0,
                   "knee": -6.0, "makeup": 9.0, "boost-threshold": -72.0,
                   "boost-amount": 6.0, "stereo-split": False},
    },
    {
        "id": "limiter#0",
        "rc": "limiterrc",
        "group": "[soe][Limiter#0]",
        # 4. Brickwall at -1 dBFS. gainBoost MUST be off: LSP's gain boost adds
        #    back exactly the amount the threshold was lowered by, so with it on
        #    a -1 threshold is a 0 dBFS ceiling with no true-peak headroom
        #    (measured: peak 0.000 dBFS, max sample 0.999999).
        "db": {"threshold": -1, "gainBoost": False, "lookahead": 5, "attack": 5,
               "release": 50},
        "preset": {"threshold": -1.0, "gain-boost": False, "lookahead": 5.0,
                   "attack": 5.0, "release": 50.0},
    },
]

PLUGINS_LINE = ",".join(p["id"] for p in CHAIN)

FLATPAK_APP = "com.github.wwmm.easyeffects"


def log(msg):
    print(f"speaker-dsp: {msg}", flush=True)


# ── rendering ────────────────────────────────────────────────────────────────

def render_value(v):
    """Booleans as true/false, never 1/0 — a number in a bool slot is ignored."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def render_rc(plugin):
    lines = [plugin["group"]]
    for k in sorted(plugin["db"]):
        lines.append(f"{k}={render_value(plugin['db'][k])}")
    return "\n".join(lines) + "\n"


def db_files():
    """rc file name -> content, for every plugin in the chain."""
    return {p["rc"]: render_rc(p) for p in CHAIN}


def preset_document():
    out = {"blocklist": [], "plugins_order": [p["id"] for p in CHAIN]}
    for p in CHAIN:
        entry = {"bypass": False, "input-gain": 0.0, "output-gain": 0.0}
        entry.update(p["preset"])
        out[p["id"]] = entry
    return {"output": out}


def preset_json():
    return json.dumps(preset_document(), indent=2, sort_keys=True) + "\n"


def merge_easyeffectsrc(text):
    """Assert plugins= under [StreamOutputs], leaving every other line alone.

    easyeffectsrc also holds the input/output device EE picked and its preset
    bookkeeping — runtime state we have no business overwriting.
    """
    lines = text.splitlines()
    out = []
    in_outputs = False
    seen_section = False
    wrote = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_outputs and not wrote:
                out.append(f"plugins={PLUGINS_LINE}")
                wrote = True
            in_outputs = stripped == "[StreamOutputs]"
            seen_section = seen_section or in_outputs
            out.append(line)
            continue
        if in_outputs and stripped.startswith("plugins="):
            if not wrote:
                out.append(f"plugins={PLUGINS_LINE}")
                wrote = True
            continue  # drop a duplicate
        out.append(line)
    if in_outputs and not wrote:
        out.append(f"plugins={PLUGINS_LINE}")
        wrote = True
    if not seen_section:
        if out and out[-1] != "":
            out.append("")
        out.append("[StreamOutputs]")
        out.append(f"plugins={PLUGINS_LINE}")
    return "\n".join(out) + "\n"


# ── locations ────────────────────────────────────────────────────────────────

def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def native_dir():
    return os.path.join(config_home(), "easyeffects")


def flatpak_dir():
    return os.path.expanduser(f"~/.var/app/{FLATPAK_APP}/config/easyeffects")


def installs():
    """[(label, easyeffects config dir)] for every EasyEffects this user has.

    The native dir is always included: on a fresh machine EasyEffects has not
    started yet and the whole point of seeding is to be there BEFORE it does.
    The Flatpak dir is included only if that app has ever run.
    """
    found = [("native", native_dir())]
    if os.path.isdir(os.path.dirname(flatpak_dir())):
        found.append(("flatpak", flatpak_dir()))
    return found


def native_binary():
    exe = shutil.which("easyeffects")
    if not exe:
        return None, None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return exe, (out.split()[-1] if out else "?")


# ── operations ───────────────────────────────────────────────────────────────

def write_if_changed(path, content, dry_run):
    try:
        with open(path) as f:
            if f.read() == content:
                return False
    except OSError:
        pass
    if dry_run:
        log(f"would write {path}")
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)
    log(f"wrote {path}")
    return True


def seed_dir(cfg_dir, dry_run=False):
    """Seed the EasyEffects 8 db under <cfg_dir>/db. Returns True if changed."""
    db = os.path.join(cfg_dir, "db")
    changed = False
    for name, content in db_files().items():
        changed |= write_if_changed(os.path.join(db, name), content, dry_run)
    rc = os.path.join(db, "easyeffectsrc")
    try:
        with open(rc) as f:
            current = f.read()
    except OSError:
        current = ""
    merged = merge_easyeffectsrc(current) if current else f"[StreamOutputs]\nplugins={PLUGINS_LINE}\n"
    changed |= write_if_changed(rc, merged, dry_run)
    return changed


def install_preset(cfg_dir, dry_run=False):
    path = os.path.join(cfg_dir, "output", f"{PRESET_NAME}.json")
    return write_if_changed(path, preset_json(), dry_run)


def db_seeded(cfg_dir):
    db = os.path.join(cfg_dir, "db")
    for name, content in db_files().items():
        try:
            with open(os.path.join(db, name)) as f:
                if f.read() != content:
                    return False
        except OSError:
            return False
    try:
        with open(os.path.join(db, "easyeffectsrc")) as f:
            return f"plugins={PLUGINS_LINE}" in f.read().splitlines()
    except OSError:
        return False


def chain_live():
    """True if the ee_soe_* filter nodes exist in PipeWire right now.

    Only meaningful while audio is PLAYING: EasyEffects creates the nodes on
    demand a second after a stream connects and tears them down again ~8 s
    after the graph goes idle. Absent nodes on a silent machine prove nothing.
    """
    if not shutil.which("pw-dump"):
        return None
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "ee_soe_filter" in out


def cmd_status():
    exe, ver = native_binary()
    if exe:
        log(f"easyeffects binary: {exe} (version {ver})")
    else:
        log("no `easyeffects` on PATH (apt: easyeffects; flatpak: com.github.wwmm.easyeffects)")
    for label, d in installs():
        preset = os.path.join(d, "output", f"{PRESET_NAME}.json")
        log(f"{label}: {d}")
        log(f"  preset {PRESET_NAME}: {'present' if os.path.exists(preset) else 'absent'}")
        log(f"  db seeded (EasyEffects 8): {'yes' if db_seeded(d) else 'no'}")
    live = chain_live()
    if live is None:
        log("PipeWire filter nodes: pw-dump unavailable")
    else:
        log(f"PipeWire filter nodes (only meaningful while audio plays): {'present' if live else 'absent'}")
    return 0


def cmd_install(dry_run):
    changed = False
    for label, d in installs():
        log(f"{label}: {d}")
        changed |= install_preset(d, dry_run)
        changed |= seed_dir(d, dry_run)
    exe, ver = native_binary()
    if exe and ver.startswith("7"):
        log(f"EasyEffects {ver} keeps its settings in GSettings, not the db: load the preset once with")
        log(f"  easyeffects -l {PRESET_NAME}    (daemon running), or pick it in Presets in the GUI,")
        log("  and set it to autoload for the speaker device there.")
    else:
        log("restart EasyEffects to pick the chain up: systemctl --user restart easyeffects  (or quit and reopen it)")
    if not changed:
        log("already installed — nothing changed")
    return 0


def cmd_seed(cfg_dir, dry_run):
    targets = [cfg_dir] if cfg_dir else [d for _l, d in installs()]
    changed = False
    for d in targets:
        changed |= seed_dir(d, dry_run)
    if not changed:
        log("db already up to date")
    return 0


def cmd_uninstall(dry_run):
    for label, d in installs():
        preset = os.path.join(d, "output", f"{PRESET_NAME}.json")
        if os.path.exists(preset):
            if dry_run:
                log(f"would remove {preset}")
            else:
                os.unlink(preset)
                log(f"removed {preset}")
        db = os.path.join(d, "db")
        for name in db_files():
            p = os.path.join(db, name)
            if os.path.exists(p):
                if dry_run:
                    log(f"would remove {p}")
                else:
                    os.unlink(p)
                    log(f"removed {p}")
        rc = os.path.join(db, "easyeffectsrc")
        try:
            with open(rc) as f:
                text = f.read()
        except OSError:
            continue
        new = "\n".join("plugins=" if line.strip() == f"plugins={PLUGINS_LINE}" else line
                        for line in text.splitlines()) + "\n"
        write_if_changed(rc, new, dry_run)
    log("EasyEffects now runs passthrough on its next start; remove the app itself if you no longer want it")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__, file=sys.stderr)
        return 64
    cmd, args = argv[0], argv[1:]
    dry_run = "-n" in args or "--dry-run" in args
    args = [a for a in args if a not in ("-n", "--dry-run")]
    if cmd == "preset":
        sys.stdout.write(preset_json())
        return 0
    if cmd == "seed":
        cfg_dir = None
        if args[:1] == ["--dir"] and len(args) >= 2:
            cfg_dir = args[1]
        elif args:
            print(__doc__, file=sys.stderr)
            return 64
        return cmd_seed(cfg_dir, dry_run)
    if cmd == "install":
        return cmd_install(dry_run)
    if cmd == "status":
        return cmd_status()
    if cmd == "uninstall":
        return cmd_uninstall(dry_run)
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
