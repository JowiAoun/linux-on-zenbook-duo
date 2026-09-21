#!/usr/bin/env python3
"""What the duo screen shows and does, with no curses in it.

The screen (lib/duo_tui.py) never touches sysfs, systemd or the journal on
its own: everything it displays comes from here, and everything it changes
goes through `duo-cli`, so the screen and the command line can never disagree
about what a feature or a knob means. This module is stdlib only and runs
without a terminal, which is what makes it testable and what lets
`duo --snapshot` render a frame on a CI runner.

Three kinds of things live here:

  * readers: units (systemctl --user show), the journal (journalctl -o json),
    the config (duo-cli config show), the hardware glance (sysfs, through the
    same lib modules the daemons use), the Mutter state (displayctl.py) and
    the doctor (duo-cli doctor)
  * a Model that keeps the latest of each and refreshes them on a thread
  * actions, every one of them a duo-cli or systemctl --user command, which
    return what the command printed so the screen can show it verbatim
"""

import collections
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CLI = os.path.join(ROOT, "bin", "duo-cli")
DISPLAYCTL = os.path.join(HERE, "displayctl.py")
PYGI = os.environ.get("DUO_PYGI", "/usr/bin/python3")
AMP_CHECK = "/usr/local/sbin/duo-cs35l41-check"

sys.path.insert(0, HERE)
import audio_probe  # noqa: E402  (same directory)
import dock  # noqa: E402
import kb_backlight  # noqa: E402
import monitors_xml  # noqa: E402
import speaker_dsp  # noqa: E402

# ── the features, as the screen lists them ───────────────────────────────────
# Names, units and one-line descriptions mirror bin/duo-cli (USER_FEATURES and
# feature_desc); the state comes from systemd, not from parsing `duo-cli
# features`, because the screen wants restart counts and exit codes too.

@dataclass
class Feature:
    name: str
    desc: str
    scope: str = "user"        # user | system | dsp
    oneshot: bool = False
    flag: str = ""             # the install.sh switch for a system feature

    @property
    def unit(self):
        if self.scope == "user":
            return f"duo-{self.name}.service"
        if self.name == "amp-check":
            return "duo-cs35l41-check.service"
        return ""


FEATURES = [
    Feature("watch-displays", "bottom panel off while the keyboard is docked, back on when it comes off"),
    Feature("watch-fn", "keyboard hotkey mode + brightness/second-screen/kb-backlight keys"),
    Feature("watch-backlight", "keep the bottom panel backlight synced to the top (off by default)"),
    Feature("watch-rotation", "log accelerometer orientation (EXPERIMENTAL)"),
    Feature("bat-limit", "re-apply BATTERY_LIMIT from the config at login", oneshot=True),
    Feature("speaker-dsp", "EasyEffects voicing chain for the built-in speakers", scope="dsp"),
    Feature("psr-fix", "i915.enable_psr=0 on the kernel command line (OLED flicker)", scope="system", flag="psr-fix"),
    Feature("palm-rejection", "libinput quirk so disable-while-typing covers the detachable touchpad", scope="system", flag="palm-rejection"),
    Feature("amp-check", "notify when the CS35L41 speaker amps fail to power up", scope="system", flag="amp-check"),
]

# ── the knobs, as the screen edits them ──────────────────────────────────────
# `daemon` is the unit that reads the knob and needs a restart to see a change.

@dataclass
class Knob:
    key: str
    kind: str                  # bool | enum | int | backlight | text
    desc: str
    values: tuple = ()         # enum choices
    lo: int = 0
    hi: int = 0
    empty_ok: bool = False
    daemon: str = ""


KNOBS = [
    Knob("APPLY_METHOD", "enum", "how layouts are handed to Mutter; persistent pops \"Keep display settings?\" on every dock and resume",
         values=("temporary", "persistent"), daemon="watch-displays"),
    Knob("BATTERY_LIMIT", "int", "charge limit in percent, re-applied at login; empty leaves the battery alone",
         lo=20, hi=100, empty_ok=True),
    Knob("BACKLIGHT_SOURCE", "backlight", "backlight the brightness keys and sync copy FROM", daemon="watch-fn"),
    Knob("BACKLIGHT_TARGET", "backlight", "backlight they copy TO; empty = the eDP-2 DRM backlight, auto-detected",
         empty_ok=True, daemon="watch-fn"),
    Knob("KB_BACKLIGHT_RESTORE", "bool", "put the keyboard backlight back after the keyboard re-enumerates", daemon="watch-fn"),
    Knob("DOCK_POLICY", "bool", "0 keeps watch-displays running but makes it watch without acting", daemon="watch-displays"),
    Knob("REMEMBER_LAYOUT", "bool", "remember the layout per set of connected monitors, the way Windows does", daemon="watch-displays"),
    Knob("LOGIN_SCREEN_LAYOUT", "bool", "give the GDM login screen the same layouts (needs the root helper)", daemon="watch-displays"),
]

KNOB_BY_KEY = {k.key: k for k in KNOBS}


# ── running things ───────────────────────────────────────────────────────────

@dataclass
class Result:
    ok: bool
    title: str
    output: str = ""

    @property
    def lines(self):
        return [line for line in self.output.splitlines() if line.strip()]

    @property
    def summary(self):
        lines = self.lines
        return lines[-1] if lines else ("ok" if self.ok else "failed")


def run(argv, timeout=30, env=None):
    """(rc, stdout, stderr); a missing binary is rc 127, a hang is rc 124."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: no answer after {timeout}s"
    except OSError as e:
        return 126, "", f"{argv[0]}: {e}"
    return p.returncode, p.stdout, p.stderr


def cli(*args, timeout=30):
    """Run a duo-cli command; the Result carries everything it printed."""
    rc, out, err = run([CLI, *args], timeout=timeout)
    text = (out + ("\n" + err if err.strip() else "")).strip()
    return Result(rc == 0, "duo " + " ".join(args), text)


def user_systemctl(*args, timeout=20):
    rc, out, err = run(["systemctl", "--user", *args], timeout=timeout)
    text = (out + ("\n" + err if err.strip() else "")).strip()
    return Result(rc == 0, "systemctl --user " + " ".join(args), text)


# ── units ────────────────────────────────────────────────────────────────────

UNIT_PROPS = ("Id", "LoadState", "ActiveState", "SubState", "Result", "NRestarts",
              "ExecMainStatus", "ExecMainCode", "UnitFileState", "ActiveEnterTimestamp",
              "InactiveEnterTimestamp", "ExecMainStartTimestamp", "MainPID",
              "FragmentPath", "Description", "StatusText")


@dataclass
class Unit:
    feature: Feature
    load: str = "not-found"
    active: str = "inactive"
    sub: str = "dead"
    result: str = ""
    restarts: int = 0
    exec_status: int = 0
    exec_code: str = ""
    file_state: str = ""
    since: str = ""
    pid: int = 0
    fragment: str = ""
    status_text: str = ""
    error: str = ""            # why the state is unknown, when it is

    @property
    def name(self):
        return self.feature.name

    @property
    def installed(self):
        return self.load == "loaded"

    @property
    def enabled(self):
        return self.file_state in ("enabled", "static", "enabled-runtime", "linked")

    @property
    def hm(self):
        """True when home-manager generated the unit (a Nix store symlink)."""
        try:
            return os.path.islink(self.fragment) and os.readlink(self.fragment).startswith("/nix/store/")
        except OSError:
            return False

    @property
    def state(self):
        """One word the screen colours: running, stopped, failed, absent, ran, unknown."""
        if self.error:
            return "unknown"
        if not self.installed:
            return "absent"
        if self.active == "failed" or (self.result not in ("", "success") and self.active != "active"):
            return "failed"
        if self.active == "active":
            return "running" if not self.feature.oneshot else "ran"
        if self.feature.oneshot and self.result == "success" and self.since:
            return "ran"
        if self.active in ("activating", "deactivating", "reloading"):
            return self.active
        return "stopped"

    @property
    def level(self):
        """ok | warn | err | off, for colouring."""
        s = self.state
        if s in ("running", "ran"):
            return "ok"
        if s == "failed":
            return "err"
        if s in ("absent", "stopped", "unknown"):
            return "off" if not self.enabled else "warn"
        return "warn"


def parse_show(text):
    """`systemctl show` output (several units, blank-line separated) -> [dict]."""
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def unit_from_props(feature, props):
    def num(key):
        try:
            return int(props.get(key, "0") or 0)
        except ValueError:
            return 0
    since = props.get("ActiveEnterTimestamp") or props.get("ExecMainStartTimestamp") \
        or props.get("InactiveEnterTimestamp") or ""
    return Unit(feature, load=props.get("LoadState", "not-found"),
                active=props.get("ActiveState", "inactive"), sub=props.get("SubState", "dead"),
                result=props.get("Result", ""), restarts=num("NRestarts"),
                exec_status=num("ExecMainStatus"), exec_code=props.get("ExecMainCode", ""),
                file_state=props.get("UnitFileState", ""), since=since, pid=num("MainPID"),
                fragment=props.get("FragmentPath", ""), status_text=props.get("StatusText", ""))


def read_units():
    """Every user feature's unit, plus the amp reporter (a system unit)."""
    user = [f for f in FEATURES if f.scope == "user"]
    rc, out, err = run(["systemctl", "--user", "show", *[f.unit for f in user],
                        "-p", ",".join(UNIT_PROPS)], timeout=15)
    units = []
    if rc != 0:
        reason = (err.strip().splitlines() or ["no user systemd session"])[-1]
        units.extend(Unit(f, error=reason) for f in user)
    else:
        by_id = {b.get("Id"): b for b in parse_show(out)}
        for f in user:
            props = by_id.get(f.unit)
            units.append(unit_from_props(f, props) if props else Unit(f, error="not reported"))
    amp = next(f for f in FEATURES if f.name == "amp-check")
    rc, out, err = run(["systemctl", "show", amp.unit, "-p", ",".join(UNIT_PROPS)], timeout=15)
    if rc == 0 and out.strip():
        units.append(unit_from_props(amp, parse_show(out)[0]))
    else:
        units.append(Unit(amp, error=(err.strip().splitlines() or ["systemctl unavailable"])[-1]))
    return units


# ── the journal ──────────────────────────────────────────────────────────────

ERR_RE = re.compile(r"(?i)\b(fail(?:ed|ure|ing)?|error|traceback|refused|cannot|can't|denied"
                    r"|timed out|timeout|dead|not confirmed|not updated|standing down|no-go)\b"
                    r"|\brc=[1-9]\d*\b")
WARN_RE = re.compile(r"(?i)\b(warn(?:ing)?|retry(?:ing)?|ignored|ignoring|unavailable|missing"
                     r"|unknown|not installed|paused|falling back|fallback|storm|unmapped|suspicious)\b")
KERNEL_RE = re.compile(r"(?i)i915|asus|sof|cs35l41|xhci|hid|usb \d|0b05|snd_hda|ELAN")


@dataclass
class Entry:
    ts: float                  # seconds since the epoch
    msg: str
    pri: int = 6
    unit: str = ""             # duo-watch-fn.service, kernel, or ""
    ident: str = ""
    pid: str = ""

    @property
    def level(self):
        if self.pri <= 3 or ERR_RE.search(self.msg):
            return "err"
        if self.pri == 4 or WARN_RE.search(self.msg):
            return "warn"
        return "info"

    @property
    def source(self):
        """A short column: the feature name, kernel, or the identifier."""
        if self.unit.startswith("duo-") and self.unit.endswith(".service"):
            return self.unit[len("duo-"):-len(".service")]
        if self.unit == "kernel":
            return "kernel"
        return self.ident or "-"

    def when(self, now=None):
        now = time.time() if now is None else now
        lt = time.localtime(self.ts)
        if now - self.ts < 20 * 3600 and time.localtime(now).tm_yday == lt.tm_yday:
            return time.strftime("%H:%M:%S", lt)
        return time.strftime("%m-%d %H:%M", lt)


def parse_journal_line(line):
    """One `journalctl -o json` line -> Entry, or None for anything odd."""
    try:
        doc = json.loads(line)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    msg = doc.get("MESSAGE", "")
    if isinstance(msg, list):  # journald encodes non-UTF-8 payloads as a byte array
        msg = bytes(b for b in msg if isinstance(b, int)).decode("utf-8", "replace")
    elif not isinstance(msg, str):
        msg = str(msg)
    try:
        ts = int(doc.get("__REALTIME_TIMESTAMP", "0")) / 1e6
    except (TypeError, ValueError):
        ts = 0.0
    try:
        pri = int(doc.get("PRIORITY", 6))
    except (TypeError, ValueError):
        pri = 6
    transport = doc.get("_TRANSPORT", "")
    unit = "kernel" if transport == "kernel" else doc.get("_SYSTEMD_USER_UNIT", "") or ""
    return Entry(ts, msg.rstrip("\n"), pri, unit, doc.get("SYSLOG_IDENTIFIER", "") or "",
                 str(doc.get("_PID", "") or ""))


def journal_matches():
    """The journalctl match expression for everything zenduo: the identifiers
    plus every unit, OR-ed with `+` (journalctl ANDs different fields)."""
    terms = ["SYSLOG_IDENTIFIER=zenduo", "SYSLOG_IDENTIFIER=duo"]
    terms.extend(f"_SYSTEMD_USER_UNIT={f.unit}" for f in FEATURES if f.scope == "user")
    out = []
    for i, t in enumerate(terms):
        if i:
            out.append("+")
        out.append(t)
    return out


def read_journal(n=600, kernel=False):
    """(entries, error): the last n zenduo lines, or the kernel's Duo-related ones."""
    if kernel:
        argv = ["journalctl", "-k", "-b", "-o", "json", "-n", str(n * 4), "--no-pager"]
    else:
        argv = ["journalctl", "--user", "-o", "json", "-n", str(n), "--no-pager", *journal_matches()]
    rc, out, err = run(argv, timeout=20)
    if rc != 0:
        return [], (err.strip().splitlines() or [f"journalctl exited {rc}"])[-1]
    entries = [e for e in map(parse_journal_line, out.splitlines()) if e is not None]
    if kernel:
        entries = [e for e in entries if KERNEL_RE.search(e.msg)][-n:]
        if not entries and not out.strip():
            return [], "the kernel journal is empty or not readable as this user (join the adm group)"
    return entries, ""


def follow_journal(kernel=False):
    """A journalctl -f process printing json lines; the caller reads its stdout."""
    if kernel:
        argv = ["journalctl", "-k", "-f", "-n", "0", "-o", "json"]
    else:
        argv = ["journalctl", "--user", "-f", "-n", "0", "-o", "json", *journal_matches()]
    try:
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True)
    except OSError:
        return None


# ── the hardware glance (sysfs, no subprocess) ───────────────────────────────

def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _glob_first(pattern):
    import glob
    hits = sorted(glob.glob(pattern))
    return hits[0] if hits else ""


def backlights():
    """[(device, percent or None)] for every backlight the kernel exposes."""
    out = []
    try:
        names = sorted(os.listdir("/sys/class/backlight"))
    except OSError:
        return out
    for name in names:
        base = f"/sys/class/backlight/{name}"
        cur, mx = _read(f"{base}/brightness"), _read(f"{base}/max_brightness")
        pct = None
        if cur.isdigit() and mx.isdigit() and int(mx) > 0:
            pct = min(100, int(cur) * 100 // int(mx))
        out.append((name, pct))
    return out


def panel(connector):
    """(status, enabled) of an internal panel from DRM sysfs."""
    st = _glob_first(f"/sys/class/drm/card*-{connector}/status")
    if not st:
        return "absent", "absent"
    return _read(st, "?"), _read(st[:-len("status")] + "enabled", "?")


@dataclass
class Glance:
    model: str = ""
    kernel: str = ""
    panels: list = field(default_factory=list)      # [(connector, status, enabled)]
    keyboard: str = "undocked"                       # docked | undocked | dead
    override: dict = None
    backlights: list = field(default_factory=list)
    native_led: bool = False
    kb_level: int = 0
    battery_node: str = ""
    battery_now: str = ""
    memory_sets: int = -1                            # -1 = unreadable
    login_state: str = ""
    helper: bool = False
    udev: bool = False
    amp_state: str = ""                              # ok | failed | unknown | ""
    bluetooth: list = field(default_factory=list)    # audio_probe.bluetooth_profiles()
    realtime: list = field(default_factory=list)     # audio_probe.data_loops()
    session: str = ""
    dsp_installed: bool = False                      # the EasyEffects db is seeded

    @property
    def keyboard_text(self):
        known = {"docked": "docked (USB, on the pogo pins)",
                 "undocked": "undocked (or Bluetooth)",
                 "dead": "on the pins but its USB link is DEAD: lift it off and re-seat it"}
        return known.get(self.keyboard, self.keyboard)


def read_glance():
    g = Glance()
    g.model = _read("/sys/class/dmi/id/product_name", "unknown")
    g.kernel = os.uname().release
    g.session = os.environ.get("XDG_SESSION_TYPE", "") or "none"
    for c in ("eDP-1", "eDP-2"):
        st, en = panel(c)
        g.panels.append((c, st, en))
    dev = dock.keyboard_usb_device()
    if dev is None:
        g.keyboard = "undocked"
    elif dock.keyboard_usb_configured(dev) is False:
        g.keyboard = "dead"
    else:
        g.keyboard = "docked"
    g.override = dock.read_override()
    g.backlights = backlights()
    g.native_led = os.path.isdir("/sys/class/leds/asus::kbd_backlight")
    g.kb_level = kb_backlight.read_level()
    node = _glob_first("/sys/class/power_supply/BAT*/charge_control_end_threshold")
    g.battery_node = node
    g.battery_now = _read(node) if node else ""
    # Any failure here is "unreadable", not a dead screen: seen 2026-09-17 with
    # a python whose expat could not load (an LD_LIBRARY_PATH pointing at an
    # older libexpat), which is an ImportError, not a FormatError.
    try:
        g.memory_sets = len(monitors_xml.load().configurations)
    except Exception:
        g.memory_sets = -1
    try:
        g.login_state = monitors_xml.login_screen_state() or ""
    except Exception:
        g.login_state = ""
    g.helper = os.access("/usr/local/sbin/zenduo-helper", os.X_OK)
    g.udev = os.path.exists("/etc/udev/rules.d/70-zenduo.rules")
    try:
        g.dsp_installed = any(speaker_dsp.db_seeded(d) for _label, d in speaker_dsp.installs())
    except OSError:
        g.dsp_installed = False
    return g


def read_amp_state():
    """ok | failed | unknown from the installed reporter, or "" without one."""
    if not os.access(AMP_CHECK, os.X_OK):
        return ""
    rc, _o, _e = run([AMP_CHECK], timeout=10)
    return {0: "ok", 1: "failed"}.get(rc, "unknown")


# ── config, displays, doctor (through duo-cli) ───────────────────────────────

def read_config():
    """(path, values, managed_by_hm, error) from `duo-cli config show`."""
    r = cli("config", "show", timeout=15)
    if not r.ok:
        return "", {}, False, r.summary
    path, values = "", {}
    for line in r.lines:
        if line.startswith("#"):
            path = line[1:].strip().split(" (")[0]
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip()
    managed = False
    try:
        managed = os.path.islink(path) and os.readlink(path).startswith("/nix/store/")
    except OSError:
        pass
    return path, values, managed, ""


def read_displays():
    """(state dict or None, layout-show lines, error) from Mutter, via displayctl."""
    rc, out, err = run([PYGI, DISPLAYCTL, "state", "--json"], timeout=15)
    if rc != 0:
        return None, [], (err.strip().splitlines() or [f"displayctl exited {rc}"])[-1]
    try:
        state = json.loads(out)
    except ValueError:
        return None, [], "displayctl printed something that is not JSON"
    r = cli("layout", "show", timeout=15)
    return state, r.lines, ""


DOCTOR_LINE = re.compile(r"^\s*\[(?P<tag>[^\]]+)\]\s(?P<text>.*)$")


@dataclass
class DoctorLine:
    kind: str                  # ok | warn | fail | must | info | section | summary | text
    text: str


def parse_doctor(text):
    lines = []
    for raw in text.splitlines():
        m = DOCTOR_LINE.match(raw)
        if m:
            tag = m.group("tag").strip()
            kind = {"OK": "ok", "WARN": "warn", "FAIL": "fail", "FAIL/MUST": "must",
                    "info": "info"}.get(tag, "text")
            lines.append(DoctorLine(kind, m.group("text")))
        elif raw.startswith("-- ") and raw.rstrip().endswith(" --"):
            lines.append(DoctorLine("section", raw.strip().strip("- ").strip()))
        elif raw.startswith("== "):
            lines.append(DoctorLine("summary", raw.strip().strip("= ").strip()))
        elif raw.strip():
            lines.append(DoctorLine("text", raw.rstrip()))
    return lines


def run_doctor():
    r = cli("doctor", timeout=90)
    return parse_doctor(r.output), r.ok


# ── the model ────────────────────────────────────────────────────────────────

class Model:
    """The latest of everything, refreshed on a thread, plus the actions.

    Readers put whole new objects in place, so a reader on the screen thread
    always sees a consistent glance/units/config; `version` goes up on every
    change so the screen knows when to redraw.
    """

    FAST_SECONDS = 1.0     # units + sysfs
    SLOW_SECONDS = 6.0     # config, displays, journal backlog
    AMP_SECONDS = 60.0     # the amp reporter reads the whole kernel journal

    def __init__(self):
        self.version_text = _read(os.path.join(ROOT, "VERSION"), "dev")
        self.glance = Glance()
        self.units = []
        self.config_path, self.config, self.config_hm, self.config_error = "", {}, False, ""
        self.displays, self.layout_lines, self.displays_error = None, [], ""
        self.entries = collections.deque(maxlen=4000)
        self.journal_error = ""
        self.cleared_at = 0.0  # lines up to here are hidden from the screen
        self.kernel_entries = []
        self.kernel_error = ""
        self.doctor_lines, self.doctor_ok, self.doctor_running = [], None, False
        self.doctor_at = 0.0
        self.version = 0
        self.amp_state = ""
        self._amp_at = 0.0
        self.bluetooth, self.realtime = [], []
        self.errors = []       # reader failures, shown once each
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._follow = None
        self._follow_thread = None
        self._wanted = {"displays": False}

    # ── refreshing ───────────────────────────────────────────────────────────

    def bump(self):
        with self._lock:
            self.version += 1

    def refresh_fast(self):
        g = read_glance()
        g.amp_state = self.amp_state
        g.bluetooth, g.realtime = self.bluetooth, self.realtime
        self.glance = g
        self.units = read_units()
        self.bump()

    def refresh_slow(self, displays=None):
        # The reporter greps this boot's whole kernel journal, and the amps
        # only fail at probe or on a resume, so once a minute is plenty.
        now = time.monotonic()
        if not self._amp_at or now - self._amp_at >= self.AMP_SECONDS:
            self.amp_state = read_amp_state()
            self._amp_at = now
        self.glance.amp_state = self.amp_state
        # pw-dump and three systemctl calls: cheap, and the profile is what
        # turns a game's sound into a phone call, so it belongs on Overview.
        self.bluetooth = audio_probe.bluetooth_profiles(audio_probe.read_pw_dump())
        self.realtime = audio_probe.data_loops(audio_probe.unit_pids())
        self.glance.bluetooth, self.glance.realtime = self.bluetooth, self.realtime
        self.config_path, self.config, self.config_hm, self.config_error = read_config()
        want = self._wanted["displays"] if displays is None else displays
        if want:
            self.displays, self.layout_lines, self.displays_error = read_displays()
        entries, self.journal_error = read_journal()
        if entries:
            with self._lock:
                self.entries = collections.deque(entries, maxlen=self.entries.maxlen)
        self.bump()

    def refresh_all(self):
        self.refresh_fast()
        self.refresh_slow(displays=True)

    def refresh_kernel(self):
        self.kernel_entries, self.kernel_error = read_journal(kernel=True)
        self.bump()

    def want_displays(self, yes=True):
        self._wanted["displays"] = yes

    def start(self):
        """Refresh on a thread until stop(); the first pass is synchronous
        so the screen never opens empty."""
        self.refresh_fast()
        self._thread = threading.Thread(target=self._loop, name="duo-refresh", daemon=True)
        self._thread.start()
        self._follow_thread = threading.Thread(target=self._follow_loop, name="duo-journal", daemon=True)
        self._follow_thread.start()

    def _loop(self):
        last_slow = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now - last_slow >= self.SLOW_SECONDS:
                    self.refresh_slow()
                    last_slow = now
                else:
                    self.refresh_fast()
            except Exception as e:  # a reader must never take the screen down
                self.errors = (self.errors + [f"refresh: {e!r}"])[-20:]
                self.bump()
            self._stop.wait(self.FAST_SECONDS)

    def _follow_loop(self):
        self._follow = follow_journal()
        if self._follow is None or self._follow.stdout is None:
            return
        for line in self._follow.stdout:
            if self._stop.is_set():
                break
            e = parse_journal_line(line)
            if e is not None:
                with self._lock:
                    self.entries.append(e)
                self.bump()

    def stop(self):
        self._stop.set()
        if self._follow is not None:
            try:
                self._follow.terminate()
            except OSError:
                pass

    def run_doctor_async(self):
        if self.doctor_running:
            return
        self.doctor_running = True
        self.bump()

        def work():
            try:
                self.doctor_lines, self.doctor_ok = run_doctor()
                self.doctor_at = time.time()
            finally:
                self.doctor_running = False
                self.bump()
        threading.Thread(target=work, name="duo-doctor", daemon=True).start()

    # ── derived views ────────────────────────────────────────────────────────

    def unit(self, name):
        return next((u for u in self.units if u.name == name), None)

    def unit_summary(self):
        """(running, failed, stopped-but-enabled) across the user units."""
        running = failed = stalled = 0
        for u in self.units:
            if u.feature.scope != "user":
                continue
            s = u.state
            if s in ("running", "ran"):
                running += 1
            elif s == "failed":
                failed += 1
            elif u.enabled and s == "stopped":
                stalled += 1
        return running, failed, stalled

    def journal(self, kernel=False):
        """The lines the screen shows: what was read, minus what `c` cleared."""
        with self._lock:      # the follow thread is appending to that deque
            src = list(self.kernel_entries if kernel else self.entries)
        if self.cleared_at:
            src = [e for e in src if e.ts > self.cleared_at]
        return src

    def clear_journal(self):
        """Hide every line already on screen, and answer how many that was.

        The journal itself is untouched: forgetting lines is journald's job and
        needs root, and a viewer has no business rewriting a log. So this is a
        cutoff in wall-clock time. A line that arrives after it still shows,
        and the six-second re-read of the backlog does not bring the old ones
        back. show_all() drops the cutoff."""
        hidden = len(self.journal()) + len(self.journal(kernel=True))
        self.cleared_at = time.time()
        self.bump()
        return hidden

    def show_all(self):
        self.cleared_at = 0.0
        self.bump()

    def recent_problems(self, n=8, unit=None):
        out = []
        for e in reversed(self.journal()):
            if unit and e.unit != unit:
                continue
            if e.level in ("err", "warn"):
                out.append(e)
                if len(out) >= n:
                    break
        out.reverse()
        return out

    # ── actions ──────────────────────────────────────────────────────────────
    # Every one is a duo-cli or systemctl --user command; the Result carries
    # the command's own words so the screen shows what actually happened.

    def enable(self, feature):
        f = next((x for x in FEATURES if x.name == feature), None)
        if f is None:
            return Result(False, f"enable {feature}", "unknown feature")
        if f.scope == "system":
            return Result(False, f"enable {feature}",
                          f"a system feature: run  sudo ./install.sh --system --{f.flag}")
        r = cli("enable", feature)
        self.refresh_fast()
        return r

    def disable(self, feature):
        f = next((x for x in FEATURES if x.name == feature), None)
        if f is None:
            return Result(False, f"disable {feature}", "unknown feature")
        if f.scope == "system":
            return Result(False, f"disable {feature}",
                          f"a system feature: run  sudo ./install.sh --system --no-{f.flag}")
        r = cli("disable", feature)
        self.refresh_fast()
        return r

    def restart(self, feature):
        u = self.unit(feature)
        if u is None or not u.feature.unit:
            return Result(False, f"restart {feature}", "nothing to restart")
        if u.feature.scope == "system":
            return Result(False, f"restart {feature}",
                          f"a system unit: run  sudo systemctl restart {u.feature.unit}")
        verb = "start" if u.feature.oneshot else "restart"
        r = user_systemctl(verb, u.feature.unit)
        self.refresh_fast()
        return r

    def start_stop(self, feature):
        u = self.unit(feature)
        if u is None or u.feature.scope != "user":
            return Result(False, f"start/stop {feature}", "not a user unit")
        verb = "stop" if u.state in ("running", "activating") else "start"
        r = user_systemctl(verb, u.feature.unit)
        self.refresh_fast()
        return r

    def config_set(self, key, value):
        knob = KNOB_BY_KEY.get(key)
        err = validate(knob, value) if knob else ""
        if err:
            return Result(False, f"config set {key}", err)
        r = cli("config", "set", key, value) if value != "" else self._config_clear(key)
        self.config_path, self.config, self.config_hm, self.config_error = read_config()
        self.bump()
        return r

    def _config_clear(self, key):
        # conf_set refuses an empty value (nothing to validate), so an empty
        # knob is written by rewriting the line in the file that duo-cli reads.
        path = self.config_path or os.path.expanduser("~/.config/zenduo/zenduo.conf")
        try:
            with open(path) as f:
                lines = f.read().splitlines()
        except OSError as e:
            return Result(False, f"config set {key}", str(e))
        pat = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=")
        done = False
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = f"{key}="
                done = True
                break
        if not done:
            lines.append(f"{key}=")
        try:
            with open(path + ".tmp", "w") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(path + ".tmp", path)
        except OSError as e:
            return Result(False, f"config set {key}", str(e))
        return Result(True, f"config set {key}", f"{key}= written to {path}")

    def panels(self, cmd):
        r = cli(cmd)
        self.refresh_fast()
        if self._wanted["displays"]:
            self.displays, self.layout_lines, self.displays_error = read_displays()
        return r

    def layout(self, verb):
        r = cli("layout", verb)
        if self._wanted["displays"]:
            self.displays, self.layout_lines, self.displays_error = read_displays()
        self.bump()
        return r

    def apply_displays(self):
        r = cli("apply-displays")
        self.refresh_fast()
        return r

    def kb_backlight(self, level):
        r = cli("kb-backlight", str(level))
        self.refresh_fast()
        return r

    def bat_limit(self, pct=None):
        r = cli("bat-limit", *([str(pct)] if pct is not None else []))
        self.refresh_fast()
        return r

    def speaker_dsp(self, verb):
        return cli("speaker-dsp", verb, timeout=60)

    def audio(self, verb, device=""):
        """`duo-cli audio stereo|headset [DEVICE]`; the Bluetooth row is read
        again right away instead of waiting for the slow refresh."""
        r = cli("audio", verb, *([device] if device else []), timeout=20)
        self.bluetooth = audio_probe.bluetooth_profiles(audio_probe.read_pw_dump())
        self.glance.bluetooth = self.bluetooth
        self.bump()
        return r

    def login_layout(self):
        return cli("layout", "login")


def validate(knob, value):
    """'' when the value is acceptable for the knob, else why not."""
    if value == "":
        return "" if knob.empty_ok else f"{knob.key} cannot be empty"
    if re.search(r"[^A-Za-z0-9_./:@,-]", value):
        return "only letters, digits and _ . / : @ , - are allowed"
    if knob.kind == "bool":
        return "" if value in ("0", "1") else "0 or 1"
    if knob.kind == "enum":
        return "" if value in knob.values else "one of " + ", ".join(knob.values)
    if knob.kind == "int":
        if not value.isdigit():
            return "a whole number"
        n = int(value)
        return "" if knob.lo <= n <= knob.hi else f"between {knob.lo} and {knob.hi}"
    if knob.kind == "backlight":
        names = [n for n, _p in backlights()]
        return "" if not names or value in names else "one of " + ", ".join(names)
    return ""
