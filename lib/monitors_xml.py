#!/usr/bin/env python3
"""~/.config/monitors.xml — Mutter's per-monitor-set layout memory.

Windows 11 keeps a display configuration per *set of connected monitors* and
restores it whenever that set comes back: which screens are on, where, at what
scale, and which one is primary — so the sign-in prompt appears on the monitor
you were last using. Mutter has exactly the same database, and restores it
itself at session start, on monitor hotplug, on lid open and after resume,
*before* anything is drawn. That database is this file.

The gap this module closes is that Mutter only *writes* it when a
configuration arrives with the PERSISTENT apply method, which in practice only
GNOME Settings' "Keep changes" flow uses. Super+P applies TEMPORARY (read from
mutter's own meta_monitor_manager_switch_config, which passes
META_MONITORS_CONFIG_METHOD_TEMPORARY), and so does every `duo` command — for
the reasons in DESIGN rule 1. So a layout chosen with the keyboard was never
remembered, and the next lid-open came up on Mutter's fallback instead: every
panel on, laptop primary, password prompt on the laptop screen.

Recording the layout that is ALREADY on screen, rather than re-applying one,
is the whole point:

  * no ApplyMonitorsConfig call, so no flicker and no "Keep display settings?"
    countdown (the reason DESIGN rule 1 rejects persistent applies);
  * what gets written is a layout Mutter itself validated and is running, so
    an unusable layout cannot be persisted;
  * Mutter restores it at the earliest possible moment, which is the only way
    the lock screen can come up on the right monitor.

Format: version 2, as documented in mutter's
`src/backends/meta-monitor-config-store.c` (read 2026-09-12, gnome-46 branch).
Written to match that file's own writer, because Mutter's parser is strict:
element order inside `<logicalmonitor>`, `<rate>` as `%.3f` (it matches a
stored mode against a live one with a 0.001 Hz tolerance), `<transform>`
omitted entirely when there is no rotation, `<primary>` only when true.

The key is the sorted set of monitor specs — connector AND vendor/product/
serial, all four, exactly as `meta_monitor_spec_equals` compares them. The two
Duo panels are indistinguishable but for the connector (both report
SDC 0x41a0 with an empty serial), which is why the connector is part of it.

Caveats, both documented rather than worked around:
  * Mutter loads this file once at session start and rewrites the whole thing
    from memory when GNOME Settings persists a layout, so entries added here
    afterwards can be dropped by that rewrite. They are recorded again the
    next time that monitor set is seen.
  * A monitor's `maxbpc`/`rgbrange` and a logical monitor's `presentation`
    flag are not exposed by GetCurrentState, so they are carried over from the
    entry being replaced instead of being re-derived.

stdlib only, so the layout maths stays testable without PyGObject.
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

VERSION = "2"

# MetaMonitorTransform: 0-3 are the rotations, +4 is the flipped variant.
ROTATIONS = ("normal", "left", "upside_down", "right")
FLIPPED = 4


def path():
    """The file Mutter reads. ZENDUO_MONITORS_XML overrides it (tests)."""
    override = os.environ.get("ZENDUO_MONITORS_XML")
    if override:
        return override
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(cfg, "monitors.xml")


def _fmt_scale(scale):
    """Mutter writes a scale with %.17g; emit the shortest exact round-trip.

    Both are read back with g_ascii_strtod, and the config key does not
    include the scale, so "1" and "1.0" are interchangeable to Mutter.
    """
    text = repr(float(scale))
    return text[:-2] if text.endswith(".0") else text


def _fmt_rate(rate):
    return f"{float(rate):.3f}"


class Spec(tuple):
    """A monitor's identity: (connector, vendor, product, serial)."""

    __slots__ = ()

    def __new__(cls, connector, vendor="", product="", serial=""):
        return super().__new__(cls, (connector, vendor or "", product or "",
                                     serial or ""))

    connector = property(lambda self: self[0])
    vendor = property(lambda self: self[1])
    product = property(lambda self: self[2])
    serial = property(lambda self: self[3])

    def describe(self):
        name = " ".join(p for p in (self.vendor, self.product) if p)
        return f"{self.connector} ({name})" if name else self.connector


class Mode:
    def __init__(self, width, height, rate, interlace=False, variable=False):
        self.width, self.height = int(width), int(height)
        self.rate = float(rate)
        self.interlace, self.variable = bool(interlace), bool(variable)

    def matches(self, width, height, rate):
        # The same test mutter's meta_monitor_mode_spec_equals applies.
        return (self.width == int(width) and self.height == int(height)
                and abs(self.rate - float(rate)) < 0.001)

    def __repr__(self):
        return f"{self.width}x{self.height}@{self.rate:.3f}"


class MonitorEntry:
    """One monitor inside a logical monitor: its identity, mode and extras."""

    def __init__(self, spec, mode, underscanning=False, extras=()):
        self.spec, self.mode = spec, mode
        self.underscanning = bool(underscanning)
        # Raw XML fragments for elements GetCurrentState cannot tell us about
        # (maxbpc, rgbrange): preserved verbatim across a rewrite.
        self.extras = list(extras)


class Logical:
    """One logical monitor: a position, a scale, and the monitors cloned onto it."""

    def __init__(self, x, y, scale, transform=0, primary=False,
                 presentation=False, monitors=()):
        self.x, self.y = int(x), int(y)
        self.scale = float(scale)
        self.transform = int(transform)
        self.primary, self.presentation = bool(primary), bool(presentation)
        self.monitors = list(monitors)

    @property
    def connectors(self):
        return [m.spec.connector for m in self.monitors]


class Configuration:
    def __init__(self, logicals=(), disabled=()):
        self.logicals = list(logicals)
        self.disabled = list(disabled)

    def specs(self):
        out = [m.spec for lm in self.logicals for m in lm.monitors]
        out.extend(self.disabled)
        return out

    def key(self):
        """The monitor set this configuration is for (mutter's config key)."""
        return tuple(sorted(tuple(s) for s in self.specs()))

    def enabled_connectors(self):
        return [c for lm in self.logicals for c in lm.connectors]

    def is_mirrored(self):
        return any(len(lm.monitors) > 1 for lm in self.logicals)

    def modes(self):
        """connector -> Mode, for the monitors this configuration enables."""
        return {m.spec.connector: m.mode for lm in self.logicals
                for m in lm.monitors}

    def shape(self):
        """What has to match for the live layout to count as "already this".

        Position, scale, rotation, primary and the cloned set — not the mode,
        which mutter may satisfy with a differently-named but equal mode.
        """
        return frozenset(
            (lm.x, lm.y, round(lm.scale, 4), lm.transform, lm.primary,
             tuple(sorted(lm.connectors)))
            for lm in self.logicals)

    def describe(self):
        parts = []
        for lm in sorted(self.logicals, key=lambda l: (l.y, l.x)):
            names = "+".join(lm.connectors)  # + = mirrored onto each other
            mode = lm.monitors[0].mode if lm.monitors else None
            bits = [names]
            if mode:
                bits.append(f"{mode.width}x{mode.height}@{mode.rate:.0f}")
            if lm.scale != 1.0:
                bits.append(f"scale {_fmt_scale(lm.scale)}")
            if lm.transform:
                bits.append(ROTATIONS[lm.transform & 3]
                            + ("+flipped" if lm.transform >= FLIPPED else ""))
            if lm.primary:
                bits.append("primary")
            parts.append(" ".join(bits))
        for spec in self.disabled:
            parts.append(f"{spec.connector} off")
        return " · ".join(parts) or "(nothing enabled)"


class Store:
    """The parsed file: the configurations, plus whatever else it held."""

    def __init__(self, configurations=(), extra=()):
        self.configurations = list(configurations)
        # <policy> and anything else at the top level, kept verbatim so a
        # rewrite never drops a setting this module does not model.
        self.extra = list(extra)

    def find(self, key):
        for config in self.configurations:
            if config.key() == key:
                return config
        return None

    def replace(self, config):
        """Put `config` in, replacing any entry for the same monitor set.

        Returns True if the store changed.
        """
        key = config.key()
        for i, existing in enumerate(self.configurations):
            if existing.key() != key:
                continue
            if render_configuration(existing) == render_configuration(config):
                return False
            _carry_over(existing, config)
            self.configurations[i] = config
            return True
        self.configurations.append(config)
        return True

    def forget(self, key):
        before = len(self.configurations)
        self.configurations = [c for c in self.configurations if c.key() != key]
        return len(self.configurations) != before


def _carry_over(old, new):
    """Keep what GetCurrentState cannot see: maxbpc, rgbrange, presentation."""
    old_extras = {m.spec.connector: m.extras for lm in old.logicals
                  for m in lm.monitors}
    old_presentation = {tuple(sorted(lm.connectors)): lm.presentation
                        for lm in old.logicals}
    for lm in new.logicals:
        for m in lm.monitors:
            if not m.extras:
                m.extras = list(old_extras.get(m.spec.connector, ()))
        if not lm.presentation:
            lm.presentation = old_presentation.get(
                tuple(sorted(lm.connectors)), False)


# ── parsing ──────────────────────────────────────────────────────────────────

class FormatError(Exception):
    """The file is not a version 2 monitors.xml — leave it alone."""


def _text(element, tag, default=None):
    child = element.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _bool(element, tag):
    return _text(element, tag, "no") == "yes"


def _parse_spec(element):
    return Spec(_text(element, "connector", ""), _text(element, "vendor", ""),
                _text(element, "product", ""), _text(element, "serial", ""))


def _parse_monitor(element):
    mode_el = element.find("mode")
    mode = None
    if mode_el is not None:
        flags = [f.text for f in mode_el.findall("flag") if f.text]
        mode = Mode(_text(mode_el, "width", 0), _text(mode_el, "height", 0),
                    _text(mode_el, "rate", 0),
                    interlace="interlace" in flags,
                    variable=_text(mode_el, "ratemode") == "variable")
    extras = [ET.tostring(child, encoding="unicode").strip()
              for child in element
              if child.tag in ("maxbpc", "rgbrange")]
    spec_el = element.find("monitorspec")
    spec = _parse_spec(spec_el) if spec_el is not None else Spec("")
    return MonitorEntry(spec, mode, _bool(element, "underscanning"), extras)


def _parse_logical(element):
    transform = 0
    transform_el = element.find("transform")
    if transform_el is not None:
        rotation = _text(transform_el, "rotation", "normal")
        transform = ROTATIONS.index(rotation) if rotation in ROTATIONS else 0
        if _bool(transform_el, "flipped"):
            transform += FLIPPED
    return Logical(
        _text(element, "x", 0), _text(element, "y", 0),
        _text(element, "scale", 1), transform,
        _bool(element, "primary"), _bool(element, "presentation"),
        [_parse_monitor(m) for m in element.findall("monitor")])


def parse(text):
    """Parse a monitors.xml document into a Store."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise FormatError(f"monitors.xml does not parse as XML: {e}")
    if root.tag != "monitors":
        raise FormatError(f"monitors.xml root element is <{root.tag}>, not <monitors>")
    version = root.get("version")
    if version != VERSION:
        # Mutter rejects any other version too; migrating one is its job.
        raise FormatError(f"monitors.xml is version {version!r}, not {VERSION!r}")
    configurations, extra = [], []
    for child in root:
        if child.tag != "configuration":
            extra.append(ET.tostring(child, encoding="unicode").strip())
            continue
        logicals = [_parse_logical(lm) for lm in child.findall("logicalmonitor")]
        disabled = []
        for disabled_el in child.findall("disabled"):
            disabled.extend(_parse_spec(s)
                            for s in disabled_el.findall("monitorspec"))
        configurations.append(Configuration(logicals, disabled))
    return Store(configurations, extra)


# ── rendering ────────────────────────────────────────────────────────────────

def _spec_xml(spec, indent):
    out = [f"{indent}<monitorspec>"]
    for tag, value in (("connector", spec.connector), ("vendor", spec.vendor),
                       ("product", spec.product), ("serial", spec.serial)):
        out.append(f"{indent}  <{tag}>{escape(value)}</{tag}>")
    out.append(f"{indent}</monitorspec>")
    return out


def _monitor_xml(monitor):
    out = ["      <monitor>"]
    out.extend(_spec_xml(monitor.spec, "        "))
    if monitor.mode is not None:
        out.append("        <mode>")
        out.append(f"          <width>{monitor.mode.width}</width>")
        out.append(f"          <height>{monitor.mode.height}</height>")
        out.append(f"          <rate>{_fmt_rate(monitor.mode.rate)}</rate>")
        if monitor.mode.variable:
            out.append("          <ratemode>variable</ratemode>")
        if monitor.mode.interlace:
            out.append("          <flag>interlace</flag>")
        out.append("        </mode>")
    if monitor.underscanning:
        out.append("        <underscanning>yes</underscanning>")
    out.extend(f"        {fragment}" for fragment in monitor.extras)
    out.append("      </monitor>")
    return out


def _logical_xml(logical):
    out = ["    <logicalmonitor>",
           f"      <x>{logical.x}</x>",
           f"      <y>{logical.y}</y>",
           f"      <scale>{_fmt_scale(logical.scale)}</scale>"]
    if logical.primary:
        out.append("      <primary>yes</primary>")
    if logical.presentation:
        out.append("      <presentation>yes</presentation>")
    if logical.transform:
        out.append("      <transform>")
        out.append(f"        <rotation>{ROTATIONS[logical.transform & 3]}</rotation>")
        flipped = "yes" if logical.transform >= FLIPPED else "no"
        out.append(f"        <flipped>{flipped}</flipped>")
        out.append("      </transform>")
    for monitor in logical.monitors:
        out.extend(_monitor_xml(monitor))
    out.append("    </logicalmonitor>")
    return out


def render_configuration(config):
    out = ["  <configuration>"]
    for logical in config.logicals:
        out.extend(_logical_xml(logical))
    if config.disabled:
        out.append("    <disabled>")
        for spec in config.disabled:
            out.extend(_spec_xml(spec, "      "))
        out.append("    </disabled>")
    out.append("  </configuration>")
    return "\n".join(out)


def render(store):
    out = [f'<monitors version="{VERSION}">']
    out.extend(f"  {fragment}" for fragment in store.extra)
    for config in store.configurations:
        out.append(render_configuration(config))
    out.append("</monitors>")
    return "\n".join(out) + "\n"


# ── the live layout, as a configuration ──────────────────────────────────────

def snapshot(monitors, logical_monitors):
    """Build a Configuration from what Mutter reports it is running.

    `monitors` is displayctl.parse_monitors output; `logical_monitors` is the
    raw GetCurrentState list. Every connected monitor ends up either in a
    logical monitor or in <disabled>, which is what makes the result's key the
    key for this monitor set.
    """
    logicals = []
    for (x, y, scale, transform, primary, assigned, _props) in logical_monitors:
        entries = []
        for (connector, vendor, product, serial) in assigned:
            mon = monitors.get(connector, {})
            mode = None
            for candidate in mon.get("modes", ()):
                if candidate.get("is_current"):
                    mode = Mode(candidate["width"], candidate["height"],
                                candidate["refresh"],
                                candidate.get("interlace", False),
                                candidate.get("variable", False))
                    break
            entries.append(MonitorEntry(
                Spec(connector, vendor, product, serial), mode,
                mon.get("underscanning", False)))
        logicals.append(Logical(x, y, scale, transform, primary, False, entries))
    enabled = {c for lm in logicals for c in lm.connectors}
    disabled = [Spec(connector, mon["vendor"], mon["product"], mon["serial"])
                for connector, mon in monitors.items() if connector not in enabled]
    return Configuration(logicals, disabled)


def topology(monitors):
    """The monitor-set key for everything currently connected."""
    return tuple(sorted(
        (connector, mon["vendor"], mon["product"], mon["serial"])
        for connector, mon in monitors.items()))


def as_logical_monitors(config):
    """A stored configuration in GetCurrentState's shape.

    build_config reads positions, scales, rotation and primary out of the
    live logical monitors; handing it these instead replays a remembered
    layout without teaching it a second input format.
    """
    return [(lm.x, lm.y, lm.scale, lm.transform, lm.primary,
             [tuple(m.spec) for m in lm.monitors], {})
            for lm in config.logicals]


def to_apply_logicals(config, resolve_mode, drop=()):
    """ApplyMonitorsConfig logicals straight from a stored configuration.

    Used for a mirrored layout, which build_config cannot express (it models
    one logical monitor per connector, so rebuilding a clone would un-mirror
    the desktop). `drop` removes connectors the dock policy will not allow.
    `resolve_mode(connector, stored_mode)` turns a stored mode into the id of
    a mode the monitor actually has now: a mode id is the backend's own string
    ("1920x1080@74.973" on this machine) and must not be rebuilt by hand.
    """
    logicals = []
    for lm in config.logicals:
        monitors = [m for m in lm.monitors if m.spec.connector not in drop]
        if not monitors:
            continue
        logicals.append([lm.x, lm.y, lm.scale, lm.transform, lm.primary,
                         [(m.spec.connector,
                           resolve_mode(m.spec.connector, m.mode), {})
                          for m in monitors]])
    if not logicals:
        return []
    if not any(lm[4] for lm in logicals):
        logicals[0][4] = True  # the primary monitor was one of the dropped ones
    # Mutter refuses a layout whose top-left corner is not the origin, and
    # dropping a panel can strand the rest — translate the block back.
    min_x = min(lm[0] for lm in logicals)
    min_y = min(lm[1] for lm in logicals)
    for lm in logicals:
        lm[0] -= min_x
        lm[1] -= min_y
    return [tuple(lm) for lm in logicals]


# ── the file ─────────────────────────────────────────────────────────────────

def gdm_monitors_path():
    """Where the login screen keeps its own copy, or None if there is no GDM.

    GDM runs its own session with its own Mutter, so the greeter reads a
    separate monitors.xml and otherwise comes up on Mutter's fallback — which
    is why the password prompt appeared on the laptop panel while the user was
    looking at an external monitor. Ubuntu's account has /var/lib/gdm3 as its
    home, Fedora's /var/lib/gdm, so ask the account rather than guessing.
    """
    try:
        import pwd
        home = pwd.getpwnam("gdm").pw_dir
    except (ImportError, KeyError):
        return None
    return os.path.join(home, ".config", "monitors.xml")


def login_screen_state(file_path=None):
    """How the login screen's copy compares: in step, out of step, absent."""
    gdm = gdm_monitors_path()
    if gdm is None:
        return None
    try:
        with open(gdm) as f:
            theirs = f.read()
    except OSError:
        return "not installed"
    try:
        with open(file_path or path()) as f:
            ours = f.read()
    except OSError:
        return "out of step"
    return "in step" if theirs == ours else "out of step"


def load(file_path=None):
    """The Store on disk, or an empty one when there is no file yet."""
    file_path = file_path or path()
    try:
        with open(file_path) as f:
            return parse(f.read())
    except FileNotFoundError:
        return Store()


def save(store, file_path=None):
    """Write the store atomically, so Mutter never reads a half-written file.

    The rendered document is parsed back and compared before it is written:
    Mutter ignores this file WHOLESALE if it does not parse, which would throw
    away every remembered monitor set, so a formatting or escaping bug must
    fail here rather than on disk.
    """
    file_path = file_path or path()
    text = render(store)
    try:
        reparsed = parse(text)
    except FormatError as e:
        raise FormatError(f"refusing to write monitors.xml: it would not parse back ({e})")
    if [c.key() for c in reparsed.configurations] != [c.key() for c in store.configurations]:
        raise FormatError("refusing to write monitors.xml: it does not round-trip")
    directory = os.path.dirname(file_path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".monitors.xml.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, file_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def remember(config, file_path=None):
    """Record `config` as the layout for its monitor set. True if it changed."""
    file_path = file_path or path()
    store = load(file_path)
    if not store.replace(config):
        return False
    save(store, file_path)
    return True


def stored_for(key, file_path=None):
    return load(file_path or path()).find(key)


def forget(key, file_path=None):
    file_path = file_path or path()
    store = load(file_path)
    if not store.forget(key):
        return False
    save(store, file_path)
    return True


def main(argv):
    """`monitors_xml.py [--brief] [file]` — what is remembered, for duo status."""
    brief = "--brief" in argv
    args = [a for a in argv if not a.startswith("-")]
    file_path = args[0] if args else path()
    try:
        store = load(file_path)
    except FormatError as e:
        print(f"monitors_xml: {e}", file=sys.stderr)
        return 1
    login = login_screen_state(file_path)
    if brief:
        bits = [f"{len(store.configurations)} monitor set(s) remembered"]
        if login is not None:
            bits.append(f"login screen {login}")
        print("; ".join(bits))
        return 0
    print(f"{file_path}: {len(store.configurations)} remembered monitor set(s)")
    for config in store.configurations:
        print("  set: " + " · ".join(Spec(*s).describe() for s in config.key()))
        print("    -> " + config.describe())
    if login is not None:
        print(f"login screen ({gdm_monitors_path()}): {login}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
