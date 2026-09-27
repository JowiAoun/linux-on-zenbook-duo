#!/usr/bin/env python3
"""Pin each panel's touchscreen and pen to that panel, in GNOME's settings.

    touch_map.py                write the mapping (what `duo set-tablet-mapping` runs)
    touch_map.py --show         what each digitizer is mapped to now, and what would be written
    touch_map.py --check        one line for `duo doctor`; exit 0 in place, 1 not, 2 no digitizers
    touch_map.py --identify [S] touch the bottom screen for S seconds (default 6); says which
                                controller answered, from its interrupt count; changes nothing
    touch_map.py --reset        back to GNOME's automatic guess

GNOME maps a touchscreen or a pen to a monitor with one setting per device,
`output` in org.gnome.desktop.peripherals.touchscreen (and .tablet for the
pen) at /org/gnome/desktop/peripherals/touchscreens/<vendor>:<product>/.

Left unset, Mutter 46 guesses, and on this machine the guess is wrong for the
bottom panel. Read from mutter 46.2 src/backends/meta-input-mapper.c,
guess_candidates() and match_builtin(), on 2026-09-27: a touchscreen goes to
a monitor of the same physical size, and failing that to "the laptop panel".
The Duo's two panels are the same size, and Mutter calls only eDP-1 the laptop
panel, so both touchscreens land on the top one. Touching the bottom screen
then moves things on the top screen.

The three values the schema documents (vendor, product, serial) cannot fix
it: both panels report SDC / 0x41a0 / 0x00000000 (Mutter's GetCurrentState
and the EDIDs in /sys/class/drm, 2026-09-27), so the first panel wins again.
Mutter 46 reads a fourth value, the connector name, and uses it when two
monitors share the first three (match_config() and monitor_has_twin() in the
same file). This writes all four. Mutter watches the setting, so the mapping
changes the moment it is written and holds across reboots and panel toggles.

Exit: 0 done · 1 Mutter or gsettings failed, or --check found it not in
place · 2 no digitizer found · 64 usage.
"""

import ast
import glob
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import displayctl  # noqa: E402  (imports without gi; only mutter_monitors() needs it)

# Which controller is glued to which panel. Read from alesya-h's duo script
# (BSD-2, github.com/alesya-h/zenbook-duo-2024-ux8406ma-linux): the top panel's
# touch is ELAN9008 on i2c_designware.0, the bottom's ELAN9009 on
# i2c_designware.3. This unit has them on the same buses, and ACPI names them
# I2C0.TPL0 and I2C5.TPLX (2026-09-27). Product ids differ between units
# (425b/425a there, 4259/42ec here), so they are read from sysfs and never
# written down. VERIFY-ON-HW on each new unit with --identify.
PAIRING = {"ELAN9008": displayctl.TOP, "ELAN9009": displayctl.BOTTOM}

# (schema, settings group, what it is): the finger and the pen of one
# controller share its vendor:product, under two different schemas.
SCHEMAS = (
    ("org.gnome.desktop.peripherals.touchscreen", "touchscreens", "touch"),
    ("org.gnome.desktop.peripherals.tablet", "tablets", "pen"),
)

# The HID device under an i2c digitizer: bus:vendor:product.instance
HID_DIR = re.compile(r"^[0-9A-Fa-f]{4}:([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})\.[0-9A-Fa-f]+$")

# A finger held on the glass makes a controller report about a hundred times a
# second; an idle one reports nothing. Measured 2026-09-27 from /proc/interrupts
# is only the idle half: VERIFY-ON-HW the rate with a finger down.
IDENTIFY_MIN = 50


class MapError(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


@dataclass
class Digitizer:
    acpi: str          # ELAN9008
    name: str          # ELAN9008:00, the i2c device and its interrupt's name
    vendor: str        # 04f3, lowercase: Mutter prints the ids with %.4x
    product: str       # 4259
    connector: str     # the panel it is glued to

    @property
    def ids(self):
        return f"{self.vendor}:{self.product}"


@dataclass
class Step:
    digitizer: Digitizer
    kind: str                  # touch | pen
    schema: str
    path: str
    current: list = None       # None = unset, GNOME guesses
    want: list = None          # None = the panel is not connected
    action: str = "ok"         # ok | set | leave | skip
    why: str = ""
    extra: dict = field(default_factory=dict)


def run(argv, timeout=10):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr or p.stdout)


# ── the digitizers ───────────────────────────────────────────────────────────

def digitizers(root="/sys/bus/i2c/devices"):
    """Every digitizer in PAIRING that is present, with its HID ids."""
    out = []
    for acpi, connector in PAIRING.items():
        for dev in sorted(glob.glob(os.path.join(root, f"i2c-{acpi}:*"))):
            try:
                children = sorted(os.listdir(dev))
            except OSError:
                continue
            for child in children:
                m = HID_DIR.match(child)
                if m:
                    out.append(Digitizer(acpi, os.path.basename(dev)[len("i2c-"):],
                                         m.group(1).lower(), m.group(2).lower(), connector))
                    break
    return out


def settings_path(group, d):
    return f"/org/gnome/desktop/peripherals/{group}/{d.ids}/"


# ── GNOME's setting, through the gsettings command ───────────────────────────

def to_gvariant(values):
    """['a', 'b'] as GVariant text, quotes and backslashes escaped."""
    def q(s):
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return "[" + ", ".join(q(str(v)) for v in values) + "]"


def from_gvariant(text):
    """The list gsettings printed, or None for anything else."""
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


class GSettings:
    """The `output` key of one schema at one path. A value of all empty
    strings is what GNOME ships and means "guess", so it reads as None."""

    def get(self, schema, path):
        rc, out = run(["gsettings", "get", f"{schema}:{path}", "output"])
        if rc != 0:
            raise MapError(f"gsettings get {schema}:{path} failed: {out.strip()}")
        value = from_gvariant(out)
        return value if value and any(value) else None

    def set(self, schema, path, values):
        rc, out = run(["gsettings", "set", f"{schema}:{path}", "output", to_gvariant(values)])
        if rc != 0:
            raise MapError(f"gsettings set {schema}:{path} failed: {out.strip()}")

    def reset(self, schema, path):
        rc, out = run(["gsettings", "reset", f"{schema}:{path}", "output"])
        if rc != 0:
            raise MapError(f"gsettings reset {schema}:{path} failed: {out.strip()}")


# ── what to write ────────────────────────────────────────────────────────────

def plan(digs, monitors, store):
    """One Step per digitizer and schema. A setting is only rewritten when it
    is unset or points at one of the two built-in panels: one mapped by hand
    to another monitor is left alone."""
    panels = {(m.get("vendor"), m.get("product"), m.get("serial"))
              for c, m in monitors.items() if c in PAIRING.values()}
    steps = []
    for d in digs:
        mon = monitors.get(d.connector)
        want = [mon["vendor"], mon["product"], mon["serial"], d.connector] if mon else None
        for schema, group, kind in SCHEMAS:
            path = settings_path(group, d)
            cur = store.get(schema, path)
            step = Step(d, kind, schema, path, cur, want)
            if want is None:
                step.action, step.why = "skip", f"{d.connector} is not connected"
            elif cur == want:
                step.action = "ok"
            elif cur is None:
                step.action, step.why = "set", "unset, so GNOME guesses eDP-1"
            elif tuple(cur[:3]) in panels:
                step.action = "set"
                step.why = ("three values cannot tell the twin panels apart" if len(cur) < 4
                            else f"points at {cur[3] or 'no connector'}")
            else:
                step.action, step.why = "leave", "mapped by hand to another monitor: " + " ".join(cur)
            steps.append(step)
    return steps


def apply(steps, store):
    """Write every "set" step; answer how many were written."""
    written = 0
    for s in steps:
        if s.action == "set":
            store.set(s.schema, s.path, s.want)
            written += 1
    return written


def describe(s):
    now = "GNOME's guess" if s.current is None else " ".join(s.current)
    head = f"{s.digitizer.name} {s.digitizer.ids} {s.kind:<5} -> {s.digitizer.connector}"
    if s.action == "ok":
        return f"{head}: in place ({now})"
    if s.action == "set":
        return f"{head}: {s.why}; writes {' '.join(s.want)}"
    return f"{head}: {s.why}; left as it is ({now})"


def mutter_monitors():
    """The connected monitors by connector, straight from Mutter."""
    try:
        _serial, raw, _logical, _props = displayctl.get_state(displayctl.proxy())
    except displayctl.DisplayCtlError as e:
        raise MapError(str(e)) from None
    return displayctl.parse_monitors(raw)


def pin(monitors, store=None, digs=None):
    """What watch-displays calls once per start: fix what is wrong, and say
    what it did. Returns log lines, empty when everything was in place."""
    store = store or GSettings()
    steps = plan(digitizers() if digs is None else digs, monitors, store)
    apply(steps, store)
    return [describe(s) for s in steps if s.action in ("set", "leave")]


# ── which controller is under which finger ───────────────────────────────────

def irq_counts(text):
    """{device name: interrupts since boot, every CPU added} from /proc/interrupts."""
    counts = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or not parts[0].endswith(":"):
            continue
        total = 0
        for tok in parts[1:]:
            if not tok.isdigit():
                break
            total += int(tok)
        counts[parts[-1]] = counts.get(parts[-1], 0) + total
    return counts


def read_interrupts():
    with open("/proc/interrupts") as f:
        return f.read()


def identify(digs, seconds, read=read_interrupts, sleep=time.sleep):
    """(the digitizer that was touched or None, {name: interrupts in the window}).
    One controller has to clearly outcount the other; anything less is no answer."""
    before = irq_counts(read())
    sleep(seconds)
    after = irq_counts(read())
    deltas = {d.name: after.get(d.name, 0) - before.get(d.name, 0) for d in digs}
    ranked = sorted(digs, key=lambda d: deltas[d.name], reverse=True)
    if not ranked or deltas[ranked[0].name] < IDENTIFY_MIN:
        return None, deltas
    if len(ranked) > 1 and deltas[ranked[1].name] * 4 > deltas[ranked[0].name]:
        return None, deltas
    return ranked[0], deltas


# ── the command line ─────────────────────────────────────────────────────────

def cmd_identify(digs, seconds):
    bottom = displayctl.BOTTOM
    print(f"Touch the BOTTOM screen with one finger and keep it moving for {seconds:g} seconds.")
    print("Starting in 3 seconds...", flush=True)
    time.sleep(3)
    print("Now.", flush=True)
    found, deltas = identify(digs, seconds)
    counts = ", ".join(f"{n} {c}" for n, c in sorted(deltas.items()))
    if found is None:
        print(f"No clear answer (interrupts in the window: {counts}). Try again, touching only the bottom screen.")
        return 1
    if found.connector == bottom:
        print(f"{found.name} answered ({counts}): it is the bottom panel's controller, as the table in "
              f"lib/touch_map.py says.")
        return 0
    print(f"{found.name} answered ({counts}), and the table in lib/touch_map.py puts it on {found.connector}: "
          f"this unit has the controllers the other way round. The mapping this command writes would be "
          f"swapped here; please open an issue with this output.")
    return 1


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    flags = [a for a in argv if a.startswith("--")]
    rest = [a for a in argv if not a.startswith("--")]
    known = {"--show", "--check", "--identify", "--reset"}
    if len(flags) > 1 or any(f not in known for f in flags) or (rest and flags != ["--identify"]):
        print("touch_map: usage: [--show | --check | --identify [SECONDS] | --reset]", file=sys.stderr)
        return 64
    flag = flags[0] if flags else ""
    digs = digitizers()
    if not digs:
        msg = "no ELAN9008 or ELAN9009 digitizer under /sys/bus/i2c/devices (not a Zenbook Duo 2024?)"
        print(f"touch_map: {msg}", file=sys.stderr if flag != "--check" else sys.stdout)
        return 2
    try:
        if flag == "--identify":
            seconds = float(rest[0]) if rest else 6.0
            return cmd_identify(digs, seconds)
        store = GSettings()
        if flag == "--reset":
            for d in digs:
                for schema, group, kind in SCHEMAS:
                    store.reset(schema, settings_path(group, d))
                    print(f"{d.name} {d.ids} {kind}: back to GNOME's automatic guess")
            return 0
        steps = plan(digs, mutter_monitors(), store)
        if flag == "--check":
            todo = [s for s in steps if s.action == "set"]
            if not todo:
                print("touch and pen: each panel's own digitizer is pinned to it")
                return 0
            print(f"touch and pen: {len(todo)} of {len(steps)} settings not in place "
                  f"({todo[0].why}); duo set-tablet-mapping writes them")
            return 1
        for s in steps:
            print(describe(s))
        if flag == "--show":
            return 0
        n = apply(steps, store)
        print(f"touch_map: {n} setting(s) written" if n else "touch_map: nothing to change")
        return 0
    except MapError as e:
        print(f"touch_map: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
