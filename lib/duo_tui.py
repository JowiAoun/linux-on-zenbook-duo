#!/usr/bin/env python3
"""The duo screen: every feature, knob, check and log of the Duo in one place.

Stdlib curses, so it runs on a stock Ubuntu with nothing installed. Six
views, picked with 1-6 or Tab:

  Overview   the machine at a glance, the daemons, the last problems
  Services   each unit with its state, restarts and exit code; enable,
             disable, restart, start/stop; the unit's own recent errors
  Settings   the knobs in zenduo.conf, edited in place through duo-cli
  Displays   what Mutter is running, the remembered layout, the Win+P verbs
  Doctor     `duo-cli doctor`, coloured, problems-only on demand
  Logs       the zenduo journal per unit or the kernel's Duo lines, live,
             errors-only, filtered

Drawing goes through a Canvas (a grid of characters and attributes) that is
blitted to curses at the end of a frame, or joined into text for
`duo --snapshot`, which is how the screen is tested without a terminal. The
screen never reads sysfs or systemd itself: lib/duo_model.py does, and every
change goes through duo-cli, so what the screen does is what the command line
would do.
"""

import os
import sys
import textwrap
import time
from collections import namedtuple

try:
    import curses
except ImportError:  # a python built without _curses: snapshots still work
    curses = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duo_model as dm  # noqa: E402

Region = namedtuple("Region", "y x h w")

KEY_ESC = 27
KEYS_ENTER = (10, 13, 343)          # 343 = curses.KEY_ENTER
KEYS_BACKSPACE = (8, 127, 263)      # 263 = curses.KEY_BACKSPACE
KEY_TAB, KEY_BTAB = 9, 353
KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = 259, 258, 260, 261
KEY_PPAGE, KEY_NPAGE, KEY_HOME, KEY_END, KEY_DC = 339, 338, 262, 360, 330
KEY_RESIZE = 410

MOVE_KEYS = (KEY_UP, KEY_DOWN, KEY_PPAGE, KEY_NPAGE, KEY_HOME, KEY_END,
             ord("j"), ord("k"), ord("g"), ord("G"))


# ── glyphs, with an ASCII fallback for a terminal that cannot draw them ──────

class Glyphs:
    def __init__(self, ascii_only=False):
        if ascii_only:
            self.h, self.v = "-", "|"
            self.tl, self.tr, self.bl, self.br = "+", "+", "+", "+"
            self.lt, self.rt = "+", "+"
            self.on, self.off, self.bad, self.none = "*", "o", "x", "-"
            self.ell, self.dot, self.arrow = "~", ".", ">"
        else:
            self.h, self.v = "─", "│"
            self.tl, self.tr, self.bl, self.br = "┌", "┐", "└", "┘"
            self.lt, self.rt = "├", "┤"
            self.on, self.off, self.bad, self.none = "●", "○", "✗", "–"
            self.ell, self.dot, self.arrow = "…", "·", "▸"


def utf8_terminal():
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


# ── the canvas ───────────────────────────────────────────────────────────────

class Canvas:
    """A grid of (char, attr). Everything is clipped, so a view can draw
    past its region without curses raising on the bottom-right corner."""

    def __init__(self, h, w):
        self.h, self.w = max(0, h), max(0, w)
        self.rows = [[(" ", 0)] * self.w for _ in range(self.h)]

    def put(self, y, x, text, attr=0, maxw=None):
        if y < 0 or y >= self.h or not text:
            return
        text = text.replace("\t", "  ")
        text = "".join(c if c >= " " and c != "\x7f" else "?" for c in text)
        if maxw is not None:
            text = text[:max(0, maxw)]
        if x < 0:
            text, x = text[-x:], 0
        row = self.rows[y]
        for i, c in enumerate(text):
            if x + i >= self.w:
                break
            row[x + i] = (c, attr)

    def fill(self, y, x, h, w, ch=" ", attr=0):
        for yy in range(y, y + h):
            self.put(yy, x, ch * max(0, w), attr)

    def hline(self, y, x, w, g, attr=0):
        self.put(y, x, g.h * max(0, w), attr)

    def box(self, r, g, attr=0, title="", title_attr=None):
        y, x, h, w = r
        if h < 2 or w < 2:
            return
        self.put(y, x, g.tl + g.h * (w - 2) + g.tr, attr)
        for yy in range(y + 1, y + h - 1):
            self.put(yy, x, g.v, attr)
            self.put(yy, x + w - 1, g.v, attr)
        self.put(y + h - 1, x, g.bl + g.h * (w - 2) + g.br, attr)
        if title:
            self.put(y, x + 2, f" {title} ", title_attr if title_attr is not None else attr, maxw=w - 4)

    def text(self):
        return "\n".join("".join(c for c, _a in row).rstrip() for row in self.rows)

    def blit(self, scr):
        for y, row in enumerate(self.rows):
            x = 0
            while x < len(row):
                attr = row[x][1]
                end = x
                while end < len(row) and row[end][1] == attr:
                    end += 1
                chunk = "".join(c for c, _a in row[x:end])
                try:
                    scr.addstr(y, x, chunk, attr)
                except curses.error:
                    pass  # the bottom-right cell, always
                x = end


def fit(text, w, g):
    """Truncate to w columns with an ellipsis; never wider than w."""
    text = str(text)
    if w <= 0:
        return ""
    if len(text) <= w:
        return text
    if w == 1:
        return g.ell
    return text[:w - 1] + g.ell


def wrap(text, w):
    out = []
    for para in str(text).splitlines() or [""]:
        out.extend(textwrap.wrap(para, max(1, w)) or [""])
    return out


# ── the theme ────────────────────────────────────────────────────────────────

class Theme:
    NAMES = ("normal", "dim", "bold", "title", "nav", "nav_sel", "sel", "ok", "warn", "err",
             "key", "box", "head", "info", "field", "edit")

    def __init__(self):
        for n in self.NAMES:
            setattr(self, n, 0)

    @classmethod
    def for_curses(cls):
        t = cls()
        colors = curses.has_colors()
        if colors:
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            pairs = {1: curses.COLOR_GREEN, 2: curses.COLOR_YELLOW, 3: curses.COLOR_RED,
                     4: curses.COLOR_CYAN, 5: curses.COLOR_BLUE, 6: curses.COLOR_MAGENTA}
            for n, fg in pairs.items():
                curses.init_pair(n, fg, bg)
            curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_CYAN)
            cp = curses.color_pair
        else:
            def cp(_n):
                return 0
        t.dim = curses.A_DIM
        t.bold = curses.A_BOLD
        t.title = cp(7) | curses.A_BOLD if colors else curses.A_REVERSE | curses.A_BOLD
        t.nav = cp(4)
        t.nav_sel = cp(8) | curses.A_BOLD if colors else curses.A_REVERSE | curses.A_BOLD
        t.sel = curses.A_REVERSE
        t.ok = cp(1)
        t.warn = cp(2)
        t.err = cp(3) | curses.A_BOLD
        t.key = cp(4) | curses.A_BOLD
        t.box = cp(5)
        t.head = curses.A_BOLD | curses.A_UNDERLINE
        t.info = cp(6)
        t.field = cp(4)
        t.edit = curses.A_REVERSE
        return t

    def level(self, level):
        return {"ok": self.ok, "warn": self.warn, "err": self.err, "off": self.dim,
                "info": self.normal, "must": self.err, "fail": self.err}.get(level, self.normal)


# ── list and scroll state ────────────────────────────────────────────────────

class Cursor:
    def __init__(self):
        self.i, self.top = 0, 0
        self.h = 10            # rows that fit; render() corrects it every frame

    def clamp(self, n, h):
        h = max(1, h)
        self.h = h
        self.i = max(0, min(self.i, n - 1)) if n else 0
        if self.i < self.top:
            self.top = self.i
        if self.i >= self.top + h:
            self.top = self.i - h + 1
        self.top = max(0, min(self.top, max(0, n - h)))

    def key(self, ch, n, h=None):
        h = max(1, h or self.h)
        if ch in (KEY_UP, ord("k")):
            self.i -= 1
        elif ch in (KEY_DOWN, ord("j")):
            self.i += 1
        elif ch == KEY_PPAGE:
            self.i -= max(1, h - 1)
        elif ch == KEY_NPAGE:
            self.i += max(1, h - 1)
        elif ch in (KEY_HOME, ord("g")):
            self.i = 0
        elif ch in (KEY_END, ord("G")):
            self.i = n - 1
        else:
            return False
        self.clamp(n, h)
        return True


class Scroll:
    def __init__(self):
        self.top, self.follow = 0, True
        self.n, self.h = 0, 8  # what was drawn last frame; see Cursor above

    def clamp(self, n, h):
        h = max(1, h)
        self.n, self.h = n, h
        if self.follow:
            self.top = max(0, n - h)
        self.top = max(0, min(self.top, max(0, n - h)))

    def key(self, ch, n=None, h=None):
        n = self.n if n is None else n
        h = max(1, h or self.h)
        if ch in (KEY_UP, ord("k")):
            self.top -= 1
        elif ch in (KEY_DOWN, ord("j")):
            self.top += 1
        elif ch == KEY_PPAGE:
            self.top -= max(1, h - 1)
        elif ch == KEY_NPAGE:
            self.top += max(1, h - 1)
        elif ch in (KEY_HOME, ord("g")):
            self.top = 0
        elif ch in (KEY_END, ord("G")):
            self.top = n
        else:
            return False
        self.follow = self.top >= n - h
        self.top = max(0, min(self.top, max(0, n - h)))
        return True


# ── modals ───────────────────────────────────────────────────────────────────

class Modal:
    title = ""

    def render(self, app, cv, r):
        raise NotImplementedError

    def handle(self, app, ch):
        raise NotImplementedError

    def frame(self, app, cv, r, inner_h, inner_w):
        """A centred box; returns the Region inside it."""
        g, t = app.g, app.t
        h = min(r.h - 2, inner_h + 2)
        w = min(r.w - 4, max(inner_w + 4, len(self.title) + 8))
        h, w = max(h, 3), max(w, 10)
        y = r.y + (r.h - h) // 2
        x = r.x + (r.w - w) // 2
        cv.fill(y, x, h, w)
        cv.box(Region(y, x, h, w), g, t.box, self.title, t.bold)
        return Region(y + 1, x + 2, h - 2, w - 4)


class Confirm(Modal):
    def __init__(self, title, lines, on_yes):
        self.title, self.lines, self.on_yes = title, lines, on_yes

    def render(self, app, cv, r):
        body = []
        for line in self.lines:
            body.extend(wrap(line, max(20, r.w - 12)))
        body += ["", "y: yes    n / Esc: no"]
        inner = self.frame(app, cv, r, len(body), max(len(b) for b in body))
        for i, line in enumerate(body[:inner.h]):
            cv.put(inner.y + i, inner.x, line, app.t.key if line.startswith("y:") else 0, inner.w)

    def handle(self, app, ch):
        if ch in (ord("y"), ord("Y")) or ch in KEYS_ENTER:
            app.close_modal()
            self.on_yes()
        elif ch in (ord("n"), ord("N"), KEY_ESC, ord("q")):
            app.close_modal()
        return True


class Notice(Modal):
    """Scrollable text; what an action printed, a journal entry, the help."""

    def __init__(self, title, lines, level="info"):
        self.title, self.lines, self.level = title, list(lines) or ["(nothing printed)"], level
        self.scroll = Scroll()
        self.scroll.follow = False

    def render(self, app, cv, r):
        width = min(max(len(line) for line in self.lines), max(30, r.w - 10))
        body = []
        for line in self.lines:
            body.extend(wrap(line, width))
        inner = self.frame(app, cv, r, min(len(body), r.h - 4), width)
        self.scroll.clamp(len(body), inner.h)   # also what handle() pages by
        for i, line in enumerate(body[self.scroll.top:self.scroll.top + inner.h]):
            cv.put(inner.y + i, inner.x, line, app.t.level(self.level) if i == 0 and self.level != "info" else 0, inner.w)
        if len(body) > inner.h:
            cv.put(inner.y + inner.h - 1, inner.x + inner.w - 12, f"{self.scroll.top + 1}/{len(body)} ", app.t.dim)

    def handle(self, app, ch):
        if ch in (KEY_ESC, ord("q")) or ch in KEYS_ENTER:
            app.close_modal()
            return True
        self.scroll.key(ch)
        return True


class Menu(Modal):
    """Pick one of a list; each item is (label, description, callback)."""

    def __init__(self, title, items):
        self.title, self.items = title, items
        self.cur = Cursor()

    def render(self, app, cv, r):
        label_w = max(len(i[0]) for i in self.items)
        lines = [f"{i[0]:<{label_w}}  {i[1]}" for i in self.items]
        width = min(max(len(line) for line in lines) + 2, max(30, r.w - 8))
        inner = self.frame(app, cv, r, min(len(lines), r.h - 4), width)
        self.cur.clamp(len(lines), inner.h)     # also what handle() pages by
        for i, line in enumerate(lines[self.cur.top:self.cur.top + inner.h]):
            idx = self.cur.top + i
            attr = app.t.sel if idx == self.cur.i else 0
            cv.put(inner.y + i, inner.x, fit(f" {line}", inner.w, app.g).ljust(inner.w), attr)

    def handle(self, app, ch):
        if ch in (KEY_ESC, ord("q")):
            app.close_modal()
        elif ch in KEYS_ENTER:
            app.close_modal()
            self.items[self.cur.i][2]()
        else:
            self.cur.key(ch, len(self.items))
        return True


class Prompt(Modal):
    """A one-line editor. on_ok(text) gets the value once validate() likes it."""

    def __init__(self, title, lines, initial, on_ok, validate=None):
        self.title, self.lines, self.on_ok, self.validate = title, lines, on_ok, validate
        self.text, self.pos, self.error = str(initial), len(str(initial)), ""

    def render(self, app, cv, r):
        width = max(40, min(r.w - 10, max([len(line) for line in self.lines] + [len(self.text) + 4])))
        body = []
        for line in self.lines:
            body.extend(wrap(line, width))
        rows = len(body) + 3 + (1 if self.error else 0)
        inner = self.frame(app, cv, r, rows, width)
        for i, line in enumerate(body):
            cv.put(inner.y + i, inner.x, line, 0, inner.w)
        y = inner.y + len(body) + 1
        cv.put(y, inner.x, " " * inner.w, app.t.edit)
        cv.put(y, inner.x, " " + self.text, app.t.edit, inner.w)
        cx = inner.x + 1 + self.pos
        if cx < inner.x + inner.w:
            ch = self.text[self.pos] if self.pos < len(self.text) else " "
            cv.put(y, cx, ch, app.t.edit | (curses.A_BLINK if curses else 0))
        if self.error:
            cv.put(y + 1, inner.x, fit(self.error, inner.w, app.g), app.t.err)
        cv.put(inner.y + rows - 1, inner.x, "Enter: save    Esc: cancel", app.t.dim, inner.w)

    def handle(self, app, ch):
        if ch == KEY_ESC:
            app.close_modal()
        elif ch in KEYS_ENTER:
            err = self.validate(self.text) if self.validate else ""
            if err:
                self.error = err
                return True
            app.close_modal()
            self.on_ok(self.text)
        elif ch in KEYS_BACKSPACE:
            if self.pos:
                self.text = self.text[:self.pos - 1] + self.text[self.pos:]
                self.pos -= 1
        elif ch == KEY_DC:
            self.text = self.text[:self.pos] + self.text[self.pos + 1:]
        elif ch == KEY_LEFT:
            self.pos = max(0, self.pos - 1)
        elif ch == KEY_RIGHT:
            self.pos = min(len(self.text), self.pos + 1)
        elif ch == KEY_HOME:
            self.pos = 0
        elif ch == KEY_END:
            self.pos = len(self.text)
        elif 32 <= ch < 127:
            self.text = self.text[:self.pos] + chr(ch) + self.text[self.pos:]
            self.pos += 1
        else:
            return True
        self.error = ""
        return True


# ── views ────────────────────────────────────────────────────────────────────

class View:
    name = "view"
    hint = ""
    help_lines = ()

    def __init__(self, app):
        self.app = app
        self.m = app.model

    def on_show(self):
        pass

    def on_hide(self):
        pass

    def render(self, cv, r):
        raise NotImplementedError

    def handle(self, ch):
        return False

    def entry_notice(self, e):
        """One journal line, in full, with everything journald knows about it."""
        head = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.ts))}  {e.source}"
                f"  pid {e.pid or '?'}  priority {e.pri}")
        self.app.notice("Journal entry", [head, "", e.msg], e.level)


class Overview(View):
    name = "Overview"
    hint = "k backlight  b battery  B bluetooth  a dock policy  d doctor  l logs  R restart"
    help_lines = (
        "k        set the keyboard backlight level (0-3)",
        "b        set the battery charge limit and apply it now",
        "B        put the Bluetooth headset on its stereo (A2DP) or headset (own mic, mono) profile",
        "a        enforce the dock policy once (drops a manual layout override)",
        "d        open Doctor and run it",
        "l        the same problems in Logs, errors only",
        "c        clear: hide every problem listed here and in Logs (C brings them back)",
        "R        restart every running duo daemon",
        "Up/Down  walk the problem list; Enter opens one in full, G returns to the newest",
    )

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()
        self.follow = True     # stay on the newest problem until you move

    def problems(self):
        return self.m.recent_problems(n=400)

    def render(self, cv, r):
        m, t, g = self.m, self.app.t, self.app.g
        gl = m.glance
        y, x = r.y, r.x
        col = min(30, max(18, r.w // 3))

        def row(label, value, attr=0, note=""):
            nonlocal y
            if y >= r.y + r.h:
                return
            cv.put(y, x, fit(label, col - 1, g), t.field)
            cv.put(y, x + col, fit(value, r.w - col - len(note) - 1, g), attr)
            if note:
                shown = len(fit(value, r.w - col - len(note) - 1, g))
                cv.put(y, x + col + shown + 2, fit(note, r.w - col - shown - 2, g), t.dim)
            y += 1

        def head(text):
            nonlocal y
            if y > r.y:
                y += 1
            cv.put(y, x, fit(text, r.w, g), t.head)
            y += 1

        head("Machine")
        row("model", gl.model or "unknown", t.ok if "UX8406" in gl.model else t.warn)
        row("kernel", gl.kernel, 0, "" if gl.session == "wayland" else f"session: {gl.session}")
        for name, st, en in gl.panels:
            attr = t.ok if en == "enabled" else (t.dim if st == "connected" else t.warn)
            row(f"panel {name}", f"{st}, {en}", attr)
        kb_attr = {"docked": t.ok, "undocked": 0, "dead": t.err}.get(gl.keyboard, 0)
        row("keyboard", gl.keyboard_text, kb_attr)
        policy = m.config.get("DOCK_POLICY", "1")
        if policy != "1":
            row("dock policy", "OFF (DOCK_POLICY=0): watching, not acting", t.warn)
        elif gl.override:
            want = ", ".join(gl.override.get("want", [])) or "?"
            row("dock policy", f"paused by a manual layout ({want})", t.warn, "a resumes it")
        else:
            row("dock policy", "active: bottom panel off while docked, on when lifted", t.ok)
        if m.config.get("REMEMBER_LAYOUT", "1") != "1":
            row("layout memory", "off (REMEMBER_LAYOUT=0)", t.dim)
        elif gl.memory_sets < 0:
            row("layout memory", "monitors.xml unreadable (not version 2?)", t.warn)
        else:
            login = f"login screen {gl.login_state}" if gl.login_state else ""
            row("layout memory", f"{gl.memory_sets} monitor set(s) remembered", 0, login)
        for dev, pct in gl.backlights:
            row(f"backlight {dev}", "?" if pct is None else f"{pct}%", 0)
        row("keyboard backlight", f"level {gl.kb_level}", 0,
            "native LED" if gl.native_led else "HID fallback")
        if gl.battery_node:
            want = m.config.get("BATTERY_LIMIT", "")
            row("battery limit", f"{gl.battery_now}% now", 0,
                f"configured: {want or 'not set'}" + ("" if not want or want == gl.battery_now else "  (b applies it)"))
        else:
            row("battery limit", "no charge_control_end_threshold node", t.dim)
        amp = {"ok": ("amps powered up cleanly this boot", t.ok),
               "failed": ("amps FAILED their handshake: sound unprotected, power off fully", t.err),
               "unknown": ("kernel journal not readable as this user", t.dim)}.get(gl.amp_state)
        if amp:
            row("speaker amps", amp[0], amp[1])
        for d in gl.bluetooth:
            if d["headset"]:
                row("bluetooth", f"{d['description']}: headset profile, mono 16 kHz", t.warn,
                    "phone quality; B switches")
            elif d["stereo"]:
                row("bluetooth", f"{d['description']}: {d['profile_description']}", t.ok, "B switches")
            else:
                row("bluetooth", f"{d['description']}: profile {d['profile'] or 'off'}", t.dim)
        no_rt = sorted({u for u, _p, _t, pol, _r in gl.realtime if pol not in ("rr", "fifo")})
        if no_rt:
            row("audio realtime", "none on " + ", ".join(no_rt) + " (started before rtkit)", t.warn,
                "./install.sh --user grants it")
        elif gl.realtime:
            row("audio realtime", "PipeWire's data loops at realtime priority", t.ok)

        head("Daemons")
        for u in m.units:
            if u.feature.scope != "user":
                continue
            extra = ""
            if u.restarts:
                extra = f"{u.restarts} restart(s)"
            if u.state == "failed" and u.exec_status:
                extra = f"exit {u.exec_status}  " + extra
            row(u.name, f"{self.app.badge(u)} {u.state}" + ("" if u.enabled else "  (not enabled)"),
                t.level(u.level), extra)
        if not m.units:
            row("units", "no user systemd session reachable", t.warn)
        install = []
        install.append("helper " + ("ok" if gl.helper else "missing"))
        install.append("udev " + ("ok" if gl.udev else "missing"))
        row("root half", ", ".join(install), 0 if gl.helper and gl.udev else t.warn,
            "" if gl.helper and gl.udev else "sudo ./install.sh --system")

        cleared = time.strftime("%H:%M:%S", time.localtime(m.cleared_at)) if m.cleared_at else ""
        head("Recent problems" + (f"   (cleared at {cleared}; C brings them back)" if cleared else "   (c clears)"))
        avail = max(1, r.y + r.h - y)
        problems = self.problems()
        if m.journal_error:
            cv.put(y, x, fit(f"journal: {m.journal_error}", r.w, g), t.warn)
        elif not problems:
            cv.put(y, x, "none since you cleared" if cleared else "none in the last few hundred journal lines", t.ok)
        else:
            if self.follow:
                self.cur.i = max(0, len(problems) - 1)
            self.cur.clamp(len(problems), avail)
            for i, e in enumerate(problems[self.cur.top:self.cur.top + avail]):
                selected = self.cur.top + i == self.cur.i and not self.follow
                base = t.sel if selected else 0
                line = f"{e.when()}  {e.source:<15} {e.msg}"
                cv.put(y + i, x, " " * r.w, base)
                cv.put(y + i, x, fit(line, r.w, g), base if selected else t.level(e.level))

    def handle(self, ch):
        app, m = self.app, self.m
        problems = self.problems()
        if ch in MOVE_KEYS:
            if not problems:
                return True
            self.follow = ch in (KEY_END, ord("G"))
            self.cur.key(ch, len(problems))
        elif ch in KEYS_ENTER and problems:
            self.entry_notice(problems[min(self.cur.i, len(problems) - 1)])
        elif ch == ord("l"):
            app.views["Logs"].errors_only = True
            app.switch("Logs")
        elif ch == ord("c"):
            app.clear_journal()
        elif ch == ord("C"):
            app.show_all_journal()
        elif ch == ord("k"):
            items = [(str(n), ["off", "low", "mid", "high"][n], (lambda n=n: app.act(lambda: m.kb_backlight(n))))
                     for n in range(4)]
            app.open_modal(Menu("Keyboard backlight", items))
        elif ch == ord("b"):
            app.edit_knob(dm.KNOB_BY_KEY["BATTERY_LIMIT"])
        elif ch == ord("B"):
            devs = m.glance.bluetooth
            if not devs:
                app.notice("Bluetooth", ["no Bluetooth audio device is connected"], "warn")
                return True
            d = devs[0]
            desc = d["description"]
            items = [("stereo", "A2DP: stereo, 48 kHz; calls use the laptop's mic",
                      lambda: app.act(lambda: m.audio("stereo", desc))),
                     ("headset", "its own mic, and mono 16 kHz for everything that plays",
                      lambda: app.act(lambda: m.audio("headset", desc)))]
            app.open_modal(Menu(desc, items))
        elif ch == ord("a"):
            app.act(m.apply_displays)
        elif ch == ord("d"):
            app.switch("Doctor")
            m.run_doctor_async()
        elif ch == ord("R"):
            running = [u for u in m.units if u.feature.scope == "user" and u.state == "running"]
            if not running:
                app.notice("Restart", ["no daemon is running"], "warn")
                return True
            names = ", ".join(u.name for u in running)
            app.open_modal(Confirm("Restart daemons", [f"Restart {names}?"],
                                   lambda: self.restart_all(running)))
        else:
            return False
        return True

    def restart_all(self, units):
        """Restart several daemons under one notice; one act() per unit would
        leave only the last one's output on screen."""
        app, m = self.app, self.m
        out, ok = [], True
        for u in units:
            try:
                r = m.restart(u.name)
            except Exception as e:      # an action must never take the screen down
                r = dm.Result(False, f"restart {u.name}", repr(e))
            ok = ok and r.ok
            out.append(f"{u.name}: {r.summary}")
        names = ", ".join(u.name for u in units)
        app.say(f"restarted {names}" if ok else "a restart failed", "ok" if ok else "err")
        app.notice("Restart daemons", out, "ok" if ok else "err")
        m.bump()


class Services(View):
    name = "Services"
    hint = "Enter actions  e enable  d disable  r restart  s start/stop  l logs"
    help_lines = (
        "Enter    a menu of everything that can be done to the selected feature",
        "e / d    enable (and start) / disable (and stop) it; system features tell you the sudo command",
        "r        restart the unit (a oneshot like bat-limit is run again)",
        "s        stop a running unit, or start a stopped one, without touching enablement",
        "l        open Logs filtered to this unit",
    )

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()

    def rows(self):
        units = {u.name: u for u in self.m.units}
        out = []
        for f in dm.FEATURES:
            out.append((f, units.get(f.name)))
        return out

    def state_of(self, f, u):
        """(text, level, detail) for a feature row."""
        m, g = self.m, self.app.g
        if f.scope == "user" or f.name == "amp-check":
            if u is None:
                return ("unknown", "off", "")
            detail = []
            if u.enabled:
                detail.append("enabled")
            elif u.installed:
                detail.append("disabled")
            if u.hm:
                detail.append("[hm]")
            if u.restarts:
                detail.append(f"{u.restarts} restart(s)")
            if u.state == "failed":
                detail.append(f"exit {u.exec_status}" if u.exec_status else (u.result or "failed"))
            if u.error:
                detail.append(u.error)
            return (u.state, u.level, "  ".join(detail))
        if f.scope == "dsp":
            if self.m.glance.dsp_installed:
                return ("installed", "ok", "Enter: status")
            return ("absent", "off", "Enter: install")
        if f.name == "psr-fix":
            on = "i915.enable_psr=0" in dm._read("/proc/cmdline")
            return ("active", "ok", "") if on else ("inactive", "off", "")
        if f.name == "palm-rejection":
            on = os.path.exists("/etc/libinput/local-overrides.quirks")
            return ("installed", "ok", "") if on else ("absent", "off", "")
        return ("?", "off", "")

    def render(self, cv, r):
        t, g = self.app.t, self.app.g
        rows = self.rows()
        # The detail pane gives way first: on a short terminal the list of
        # features is the part that must stay readable.
        detail_h = max(3, min(12, r.h // 3))
        list_h = max(2, r.h - detail_h - 1)
        self.cur.clamp(len(rows), list_h - 1)
        cols = (16, 11, 26)
        head = f"{'FEATURE':<{cols[0]}} {'STATE':<{cols[1]}} {'DETAIL':<{cols[2]}} WHAT"
        cv.put(r.y, r.x, fit(head, r.w, g), t.head)
        for i, (f, u) in enumerate(rows[self.cur.top:self.cur.top + list_h - 1]):
            idx = self.cur.top + i
            state, level, detail = self.state_of(f, u)
            badge = self.app.badge_level(level)
            y = r.y + 1 + i
            selected = idx == self.cur.i
            base = t.sel if selected else 0
            cv.put(y, r.x, " " * r.w, base)
            cv.put(y, r.x, fit(f.name, cols[0], g), base | (t.bold if selected else 0))
            cv.put(y, r.x + cols[0] + 1, fit(f"{badge} {state}", cols[1], g), base | t.level(level) if not selected else base)
            cv.put(y, r.x + cols[0] + cols[1] + 2, fit(detail, cols[2], g), base | (t.dim if not selected else 0))
            cv.put(y, r.x + sum(cols) + 3, fit(f.desc, r.w - sum(cols) - 3, g), base)
        # detail pane for the selected feature
        dy = r.y + list_h
        cv.hline(dy, r.x, r.w, g, t.box)
        f, u = rows[self.cur.i] if rows else (None, None)
        if f is None:
            return
        cv.put(dy, r.x + 2, f" {f.name} ", t.bold)
        y = dy + 1
        lines = []
        if f.scope == "user" or f.name == "amp-check":
            if u is None or u.error:
                lines.append((f"state unknown: {u.error if u else 'no data'}", t.warn))
            elif not u.installed:
                lines.append((f"{f.unit} is not installed here" + ("" if f.scope != "user" else "  (./install.sh --user)"), t.dim))
            else:
                since = f"  since {u.since}" if u.since else ""
                lines.append((f"{f.unit}: {u.active}/{u.sub}{since}", t.level(u.level)))
                bits = [f"unit file {u.file_state or '?'}", f"result {u.result or '?'}",
                        f"restarts {u.restarts}"]
                if u.pid:
                    bits.append(f"pid {u.pid}")
                if u.exec_code or u.exec_status:
                    bits.append(f"last exit {u.exec_code or '?'}={u.exec_status}")
                lines.append(("  ".join(bits), 0))
                if u.hm:
                    lines.append(("generated by home-manager: enable/disable here lasts until the next switch", t.dim))
                if f.scope == "system":
                    lines.append((f"a system unit: sudo systemctl restart {f.unit}", t.dim))
            # Only the user units are in the journal the screen reads, so a
            # system unit must not be reported as quiet: nothing looked.
            problems = self.m.recent_problems(n=6, unit=f.unit) if f.scope == "user" else []
            if problems:
                lines.append(("recent problems from this unit:", t.head))
                for e in problems:
                    lines.append((f"  {e.when()}  {e.msg}", t.level(e.level)))
            elif f.scope != "user":
                lines.append((f"its lines are in the system journal: journalctl -u {f.unit} -b", t.dim))
            elif u is not None and u.installed:
                lines.append(("no warnings or errors from this unit in the journal backlog", t.ok))
        elif f.scope == "dsp":
            lines.append(("`duo-cli speaker-dsp status` on Enter; install and uninstall write the EasyEffects preset and db", t.dim))
            for line in getattr(self.app, "dsp_lines", [])[:8]:
                lines.append((line, 0))
        else:
            lines.append((f"a root feature: sudo ./install.sh --system --{f.flag} / --no-{f.flag}", t.dim))
        for text, attr in lines[:detail_h - 1]:
            cv.put(y, r.x, fit(text, r.w, g), attr)
            y += 1

    def handle(self, ch):
        app, m = self.app, self.m
        rows = self.rows()
        if self.cur.key(ch, len(rows)):
            return True
        if not rows:
            return False
        f, u = rows[self.cur.i]
        if ch in KEYS_ENTER:
            self.menu(f, u)
        elif ch == ord("e"):
            self.enable(f)
        elif ch == ord("d"):
            self.disable(f)
        elif ch == ord("r"):
            if f.scope in ("user", "system"):
                app.act(lambda: m.restart(f.name))
            else:
                app.notice("Restart", ["speaker-dsp is not a daemon; restart EasyEffects instead: systemctl --user restart easyeffects"], "warn")
        elif ch == ord("s"):
            if f.scope == "user":
                app.act(lambda: m.start_stop(f.name))
            elif f.unit:
                app.notice("Start / stop", [f"{f.unit} is a system unit:",
                                            f"sudo systemctl start {f.unit}", f"sudo systemctl stop {f.unit}"], "warn")
            else:
                app.notice("Start / stop", [f"{f.name} is not a unit; there is nothing to start or stop"], "warn")
        elif ch == ord("l"):
            self.logs(f)
        else:
            return False
        return True

    def logs(self, f):
        """Open Logs on this unit, or say where its lines really are."""
        app = self.app
        if f.scope == "user":
            app.views["Logs"].source = f.unit
            app.views["Logs"].follow = True
            app.switch("Logs")
        elif f.unit:
            app.notice("Logs", [f"{f.unit} is a system unit. duo reads the user journal, so its",
                                "lines are not here:", f"journalctl -u {f.unit} -b"], "info")
        else:
            app.notice("Logs", [f"{f.name} has no unit of its own, so nothing logs under that name"], "info")

    def enable(self, f):
        app, m = self.app, self.m
        if f.scope == "dsp":
            app.open_modal(Confirm("Install the speaker chain",
                                   ["Write the EasyEffects preset and db for the built-in speakers?",
                                    "EasyEffects then needs a restart to pick it up."],
                                   lambda: app.act(lambda: m.speaker_dsp("install"))))
            return
        app.act(lambda: m.enable(f.name))

    def disable(self, f):
        app, m = self.app, self.m
        if f.scope == "dsp":
            app.open_modal(Confirm("Remove the speaker chain",
                                   ["Remove the duo-speakers preset and its db entries?"],
                                   lambda: app.act(lambda: m.speaker_dsp("uninstall"))))
            return
        if f.scope == "system":
            app.act(lambda: m.disable(f.name))
            return
        app.open_modal(Confirm(f"Disable {f.name}",
                               [f"Stop duo-{f.name} now and keep it off at login?"],
                               lambda: app.act(lambda: m.disable(f.name))))

    def menu(self, f, u):
        app, m = self.app, self.m
        items = []
        if f.scope == "user":
            items.append(("enable", "start now and at every login", lambda: self.enable(f)))
            items.append(("disable", "stop now and keep off at login", lambda: self.disable(f)))
            items.append(("restart", "restart the unit" if not f.oneshot else "run it again now",
                          lambda: app.act(lambda: m.restart(f.name))))
            if u is not None and u.installed:
                verb = "stop" if u.state in ("running", "activating") else "start"
                items.append((verb, f"{verb} without changing enablement", lambda: app.act(lambda: m.start_stop(f.name))))
            items.append(("logs", "the journal of this unit", lambda: self.logs(f)))
        elif f.scope == "dsp":
            items.append(("status", "what is installed, and whether the chain is live", self.dsp_status))
            items.append(("install", "write the preset and db", lambda: self.enable(f)))
            items.append(("uninstall", "remove them", lambda: self.disable(f)))
        else:
            items.append(("how to enable", "shows the installer command", lambda: app.act(lambda: m.enable(f.name))))
            items.append(("how to disable", "shows the installer command", lambda: app.act(lambda: m.disable(f.name))))
            if f.unit:
                items.append(("logs", "where this unit's journal is", lambda: self.logs(f)))
        app.open_modal(Menu(f.name, items))

    def dsp_status(self):
        r = self.m.speaker_dsp("status")
        self.app.dsp_lines = [line.replace("speaker-dsp: ", "") for line in r.lines]
        self.app.notice("speaker-dsp status", self.app.dsp_lines, "info" if r.ok else "err")


class Settings(View):
    name = "Settings"
    hint = "Enter edit  space toggle  R restart the daemon that reads it"
    help_lines = (
        "Enter    edit the knob: a toggle, a choice list, or a text prompt with validation",
        "space    the same thing: a 0/1 knob flips, anything else opens its editor",
        "R        restart the daemon that reads the selected knob (shown in the row)",
        "Every change is written by `duo-cli config set`; the daemon reads it on its next start.",
    )

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()

    def render(self, cv, r):
        m, t, g = self.m, self.app.t, self.app.g
        y = r.y
        if m.config_error:
            cv.put(y, r.x, fit(f"config unreadable: {m.config_error}", r.w, g), t.err)
            y += 1
        path = m.config_path or "~/.config/zenduo/zenduo.conf"
        if m.config_hm:
            cv.put(y, r.x, fit(f"{path} is written by home-manager: change the zenduo.* options there and switch", r.w, g), t.warn)
        else:
            cv.put(y, r.x, fit(path, r.w, g), t.dim)
        y += 1
        cols = (22, 18)
        cv.put(y, r.x, fit(f"{'KEY':<{cols[0]}} {'VALUE':<{cols[1]}} WHAT", r.w, g), t.head)
        y += 1
        list_h = r.y + r.h - y
        self.cur.clamp(len(dm.KNOBS), list_h)
        for i, k in enumerate(dm.KNOBS[self.cur.top:self.cur.top + list_h]):
            idx = self.cur.top + i
            selected = idx == self.cur.i
            base = t.sel if selected else 0
            val = m.config.get(k.key, "")
            shown = val if val != "" else ("(empty)" if k.empty_ok else "(unset)")
            if k.kind == "bool":
                shown = ("on  (1)" if val == "1" else "off (0)") if val in ("0", "1") else shown
            what = k.desc + (f"   [{k.daemon}]" if k.daemon else "")
            cv.put(y + i, r.x, " " * r.w, base)
            cv.put(y + i, r.x, fit(k.key, cols[0], g), base | (t.bold if selected else t.field))
            vattr = base if selected else (t.dim if val == "" else (t.ok if k.kind == "bool" and val == "1" else 0))
            cv.put(y + i, r.x + cols[0] + 1, fit(shown, cols[1], g), vattr)
            cv.put(y + i, r.x + sum(cols) + 2, fit(what, r.w - sum(cols) - 2, g), base)

    def handle(self, ch):
        app, m = self.app, self.m
        if self.cur.key(ch, len(dm.KNOBS)):
            return True
        k = dm.KNOBS[self.cur.i]
        if ch in KEYS_ENTER or ch == ord(" "):
            app.edit_knob(k)     # a bool flips, anything else opens a list or a prompt
        elif ch == ord("R"):
            if k.daemon:
                app.act(lambda: m.restart(k.daemon))
            else:
                app.notice("Restart", [f"{k.key} is read by `duo-cli bat-limit`, not a daemon; b on Overview applies it"], "warn")
        else:
            return False
        return True


class Displays(View):
    name = "Displays"
    hint = "Enter run the selected action   r refresh"
    help_lines = (
        "The table is what Mutter runs now; below it, what `duo-cli layout` says is remembered.",
        "Enter    run the selected action (the panel verbs pause the dock policy until the next dock/undock)",
        "r        ask Mutter again",
    )
    ACTIONS = (
        ("top", "the laptop's top panel only (eDP-1)", "panels"),
        ("bottom", "the bottom panel only (eDP-2)", "panels"),
        ("both", "both internal panels, stacked", "panels"),
        ("toggle", "bottom panel on <-> off, everything else untouched", "panels"),
        ("laptop", "layout: this laptop's screens only", "layout"),
        ("external", "layout: external monitor(s) only", "layout"),
        ("extend", "layout: everything, side by side", "layout"),
        ("mirror", "layout: the same picture on every screen", "layout"),
        ("cycle", "layout: step through those four, Windows' order", "layout"),
        ("remember", "record what is on screen for this set of monitors", "layout"),
        ("forget", "drop what is remembered for this set", "layout"),
        ("login", "give the login screen these layouts (root helper)", "layout"),
        ("apply-displays", "enforce the dock policy once; drops a manual override", "apply"),
        ("touch", "pin each panel's touch and pen to that panel", "touch"),
        ("touch --show", "what the touch and pen settings say now", "touch"),
    )

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()

    def on_show(self):
        self.m.want_displays(True)
        if self.m.displays is None and not self.m.displays_error:
            self.app.background(lambda: self.m.refresh_slow(displays=True))

    def on_hide(self):
        # Every poll spawns displayctl.py under PyGObject. Nothing else on the
        # screen reads Mutter, so stop asking the moment this view is gone.
        self.m.want_displays(False)

    def render(self, cv, r):
        m, t, g = self.m, self.app.t, self.app.g
        y = r.y
        st = m.displays
        if st is None:
            msg = m.displays_error or "asking Mutter..."
            cv.put(y, r.x, fit(msg, r.w, g), t.warn if m.displays_error else t.dim)
            y += 2
        else:
            head = f"{'CONNECTOR':<10} {'MONITOR':<18} {'MODE':<18} {'STATE':<9} {'POS':<12} {'SCALE':<6} PRIMARY"
            cv.put(y, r.x, fit(head, r.w, g), t.head)
            y += 1
            enabled = set(st.get("enabled", []))
            layout = st.get("layout", {})
            for name, mon in st.get("monitors", {}).items():
                cur = next((md for md in mon.get("modes", []) if md.get("is_current")), None)
                mode = f"{cur['width']}x{cur['height']}@{cur['refresh']:.0f}" if cur else "-"
                lm = layout.get(name, {})
                pos = f"{lm.get('x', 0)},{lm.get('y', 0)}" if lm else "-"
                scale = f"{lm.get('scale', 1):g}" if lm else "-"
                prim = "yes" if lm.get("primary") else ""
                label = " ".join(p for p in (mon.get("vendor"), mon.get("product")) if p) or "-"
                on = name in enabled
                line = f"{name:<10} {label[:18]:<18} {mode:<18} {'on' if on else 'off':<9} {pos:<12} {scale:<6} {prim}"
                cv.put(y, r.x, fit(line, r.w, g), t.ok if on else t.dim)
                y += 1
            y += 1
            for line in m.layout_lines:
                attr = 0
                if line.startswith("remembered") and "nothing yet" in line:
                    attr = t.warn
                if line.startswith("login screen") and "not installed" in line:
                    attr = t.dim
                cv.put(y, r.x, fit(line, r.w, g), attr)
                y += 1
            y += 1
        cv.put(y, r.x, "ACTIONS", t.head)
        y += 1
        list_h = max(1, r.y + r.h - y)
        self.cur.clamp(len(self.ACTIONS), list_h)
        for i, (verb, desc, _kind) in enumerate(self.ACTIONS[self.cur.top:self.cur.top + list_h]):
            idx = self.cur.top + i
            selected = idx == self.cur.i
            base = t.sel if selected else 0
            cv.put(y + i, r.x, " " * r.w, base)
            cv.put(y + i, r.x, fit(f" {verb:<15} {desc}", r.w, g), base | (t.bold if selected else 0))

    def handle(self, ch):
        app, m = self.app, self.m
        if self.cur.key(ch, len(self.ACTIONS)):
            return True
        if ch == ord("r"):
            app.background(lambda: m.refresh_slow(displays=True))
            return True
        if ch in KEYS_ENTER:
            verb, _desc, kind = self.ACTIONS[self.cur.i]
            if kind == "panels":
                app.act(lambda: m.panels(verb))
            elif kind == "apply":
                app.act(m.apply_displays)
            elif kind == "touch":
                app.act(lambda: m.touch_mapping(*verb.split()[1:]))
            elif verb == "forget":
                app.open_modal(Confirm("Forget this layout",
                                       ["Drop what is remembered for the monitors connected now?",
                                        "GNOME's own default comes back next time they are connected."],
                                       lambda: app.act(lambda: m.layout("forget"))))
            else:
                app.act(lambda: m.layout(verb))
            return True
        return False


class Doctor(View):
    name = "Doctor"
    hint = "r run again   e problems only   Enter full line"
    help_lines = (
        "Runs `duo-cli doctor` (read-only, safe anywhere) the first time you open this view.",
        "r        run it again",
        "e        show only warnings and failures",
        "Enter    the selected line in full",
    )

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()
        self.problems_only = False

    def on_show(self):
        if not self.m.doctor_lines and not self.m.doctor_running:
            self.m.run_doctor_async()

    def lines(self):
        lines = self.m.doctor_lines
        if self.problems_only:
            lines = [ln for ln in lines if ln.kind in ("warn", "fail", "must", "summary", "section")]
            # a section with nothing under it is noise
            out = []
            for i, ln in enumerate(lines):
                if ln.kind == "section" and (i + 1 >= len(lines) or lines[i + 1].kind in ("section", "summary")):
                    continue
                out.append(ln)
            lines = out
        return lines

    def render(self, cv, r):
        m, t, g = self.m, self.app.t, self.app.g
        y = r.y
        if m.doctor_running:
            cv.put(y, r.x, "running duo-cli doctor...", t.info)
        elif m.doctor_at:
            when = time.strftime("%H:%M:%S", time.localtime(m.doctor_at))
            summary = next((ln.text for ln in m.doctor_lines if ln.kind == "summary" and "summary" in ln.text), "")
            gate = next((ln.text for ln in m.doctor_lines if ln.kind == "summary" and "GATE" in ln.text), "")
            cv.put(y, r.x, fit(f"ran at {when}   {summary}", r.w, g), t.bold)
            if gate:
                cv.put(y + 1, r.x, fit(gate, r.w, g), t.err if "NO-GO" in gate else t.ok)
                y += 1
        else:
            cv.put(y, r.x, "not run yet (r)", t.dim)
        y += 2
        lines = self.lines()
        list_h = max(1, r.y + r.h - y)
        self.cur.clamp(len(lines), list_h)
        tag = {"ok": " OK ", "warn": "WARN", "fail": "FAIL", "must": "MUST", "info": "info"}
        for i, ln in enumerate(lines[self.cur.top:self.cur.top + list_h]):
            idx = self.cur.top + i
            selected = idx == self.cur.i
            base = t.sel if selected else 0
            if ln.kind == "section":
                cv.put(y + i, r.x, fit(ln.text, r.w, g), base | t.head)
            elif ln.kind == "summary":
                cv.put(y + i, r.x, fit(ln.text, r.w, g), base | t.bold)
            elif ln.kind in tag:
                cv.put(y + i, r.x, f"[{tag[ln.kind]}]", base | t.level({"ok": "ok", "info": "info"}.get(ln.kind, ln.kind)))
                cv.put(y + i, r.x + 7, fit(ln.text, r.w - 7, g), base)
            else:
                cv.put(y + i, r.x, fit(ln.text, r.w, g), base | t.dim)

    def handle(self, ch):
        lines = self.lines()
        if self.cur.key(ch, len(lines)):
            return True
        if ch == ord("r"):
            self.m.run_doctor_async()
        elif ch == ord("e"):
            self.problems_only = not self.problems_only
            self.cur.i = 0
        elif ch in KEYS_ENTER and lines:
            ln = lines[self.cur.i]
            self.app.notice(ln.kind.upper(), [ln.text])
        else:
            return False
        return True


class Logs(View):
    name = "Logs"
    hint = "s source  e errors  f follow  / filter  c clear  C show all  Enter entry"
    help_lines = (
        "s        next source: all zenduo, each unit, then the kernel's Duo-related lines",
        "e        only warnings and errors (priority, or words like failed/refused/cannot)",
        "f        follow: stay at the bottom as new lines arrive",
        "/        filter by a substring; an empty filter shows everything again",
        "c        clear: hide every line on screen now, here and under Recent problems",
        "C        bring the cleared lines back",
        "Enter    the selected entry in full",
        "Clearing hides lines, it never deletes them: the journal belongs to journald,",
        "and duo only reads it (journalctl --user -o json; the kernel view needs adm).",
    )
    SOURCES = ["all"] + [f.unit for f in dm.FEATURES if f.scope == "user"] + ["kernel"]

    def __init__(self, app):
        super().__init__(app)
        self.cur = Cursor()
        self.source = "all"
        self.errors_only = False
        self.follow = True
        self.filter = ""
        self._kernel_loaded = False

    def on_show(self):
        if self.source == "kernel" and not self._kernel_loaded:
            self._kernel_loaded = True
            self.app.background(self.m.refresh_kernel)

    def entries(self):
        src = self.m.journal(kernel=self.source == "kernel")
        if self.source not in ("all", "kernel"):
            src = [e for e in src if e.unit == self.source]
        if self.errors_only:
            src = [e for e in src if e.level in ("err", "warn")]
        if self.filter:
            f = self.filter.lower()
            src = [e for e in src if f in e.msg.lower() or f in e.source.lower()]
        return src

    def render(self, cv, r):
        m, t, g = self.m, self.app.t, self.app.g
        entries = self.entries()
        label = {"all": "all zenduo", "kernel": "kernel (i915/asus/sof/cs35l41/usb)"}.get(self.source, self.source)
        bits = [f"source: {label}"]
        if self.errors_only:
            bits.append("errors only")
        if self.filter:
            bits.append(f"filter: {self.filter!r}")
        if m.cleared_at:
            bits.append("cleared " + time.strftime("%H:%M:%S", time.localtime(m.cleared_at)))
        bits.append("following" if self.follow else "paused")
        bits.append(f"{len(entries)} lines")
        cv.put(r.y, r.x, fit("   ".join(bits), r.w, g), t.info)
        err = m.kernel_error if self.source == "kernel" else m.journal_error
        y = r.y + 1
        if err:
            cv.put(y, r.x, fit(err, r.w, g), t.warn)
            y += 1
        list_h = max(1, r.y + r.h - y)
        if self.follow:
            self.cur.i = max(0, len(entries) - 1)
        self.cur.clamp(len(entries), list_h)
        now = time.time()
        src_w = 15 if self.source in ("all", "kernel") else 0
        for i, e in enumerate(entries[self.cur.top:self.cur.top + list_h]):
            idx = self.cur.top + i
            selected = idx == self.cur.i and not self.follow
            base = t.sel if selected else 0
            x = r.x
            cv.put(y + i, x, e.when(now), base | t.dim)
            x += 9 if len(e.when(now)) <= 8 else 12
            if src_w:
                cv.put(y + i, x, fit(e.source, src_w - 1, g), base | t.field)
                x += src_w
            cv.put(y + i, x, fit(e.msg, r.x + r.w - x, g), base | t.level(e.level) if e.level != "info" else base)

    def handle(self, ch):
        app = self.app
        entries = self.entries()
        if ch in MOVE_KEYS:
            if not entries:
                return True
            self.follow = ch in (KEY_END, ord("G"))
            self.cur.key(ch, len(entries))
            return True
        if ch == ord("s"):
            i = self.SOURCES.index(self.source) if self.source in self.SOURCES else -1
            self.source = self.SOURCES[(i + 1) % len(self.SOURCES)]
            self.cur.i = 0
            self.on_show()
        elif ch == ord("e"):
            self.errors_only = not self.errors_only
        elif ch == ord("f"):
            self.follow = not self.follow
        elif ch == ord("c"):
            app.clear_journal()
            self.follow = True
        elif ch == ord("C"):
            app.show_all_journal()
        elif ch == ord("/"):
            app.open_modal(Prompt("Filter", ["Show only lines containing:"], self.filter, self.set_filter))
        elif ch in KEYS_ENTER and entries:
            self.entry_notice(entries[min(self.cur.i, len(entries) - 1)])
        elif ch == ord("r"):
            app.background(self.m.refresh_kernel if self.source == "kernel" else self.m.refresh_slow)
        else:
            return False
        return True

    def set_filter(self, text):
        self.filter = text.strip()


# ── the app ──────────────────────────────────────────────────────────────────

VIEW_CLASSES = (Overview, Services, Settings, Displays, Doctor, Logs)
NAV_WIDTH = 12
MIN_H, MIN_W = 12, 50


class App:
    def __init__(self, model, theme=None, ascii_only=False):
        self.model = model
        self.t = theme or Theme()
        self.g = Glyphs(ascii_only)
        self.views = {}
        self.order = []
        for cls in VIEW_CLASSES:
            v = cls(self)
            self.views[cls.name] = v
            self.order.append(cls.name)
        self.current = self.order[0]
        self.modal = None
        self.status = ("", "info")     # the last action's one line
        self.status_at = 0.0
        self.quit = False
        self.dsp_lines = []
        self._drawn_version = -1
        self._threads = []

    # ── helpers views call ───────────────────────────────────────────────────

    def badge(self, unit):
        return self.badge_level(unit.level)

    def badge_level(self, level):
        g = self.g
        return {"ok": g.on, "warn": g.off, "err": g.bad, "off": g.none}.get(level, g.none)

    def switch(self, name):
        if name not in self.views:
            return
        if name != self.current:
            self.views[self.current].on_hide()
        self.current = name
        self.views[name].on_show()

    def open_modal(self, modal):
        self.modal = modal

    def close_modal(self):
        self.modal = None

    def notice(self, title, lines, level="info"):
        self.open_modal(Notice(title, lines, level))

    def say(self, text, level="info"):
        self.status = (text, level)
        self.status_at = time.time()

    def clear_journal(self):
        hidden = self.model.clear_journal()
        self.say(f"cleared {hidden} line(s) from the screen; journald still has them, C brings them back")

    def show_all_journal(self):
        self.model.show_all()
        self.say("showing every line the journal kept")

    def act(self, fn):
        """Run an action now, put its one-line outcome in the status bar and
        its full output in a notice when it failed or said several things."""
        try:
            r = fn()
        except Exception as e:  # an action must never take the screen down
            r = dm.Result(False, "action", repr(e))
        level = "ok" if r.ok else "err"
        self.say(f"{r.title}: {r.summary}", level)
        if not r.ok or len(r.lines) > 1:
            self.notice(r.title + (" (failed)" if not r.ok else ""), r.lines, level)
        self.model.bump()
        return r

    def background(self, fn):
        import threading

        def work():
            try:
                fn()
            except Exception as e:
                self.say(f"refresh failed: {e!r}", "err")
            self.model.bump()
        th = threading.Thread(target=work, daemon=True)
        th.start()
        self._threads = [t for t in self._threads if t.is_alive()] + [th]

    def edit_knob(self, k):
        m = self.model
        if m.config_hm:
            self.notice("Managed by home-manager",
                        [f"{m.config_path} is a read-only symlink into the Nix store.",
                         "Change the zenduo.* options in your home-manager config and switch."], "warn")
            return
        cur = m.config.get(k.key, "")
        if k.kind == "bool":
            self.set_knob(k, "0" if cur == "1" else "1")
        elif k.kind == "enum":
            items = [(v, "current" if v == cur else "", (lambda v=v: self.set_knob(k, v))) for v in k.values]
            self.open_modal(Menu(k.key, items))
        elif k.kind == "backlight":
            names = [n for n, _p in dm.backlights()]
            items = [(n, f"{p}%" if p is not None else "", (lambda n=n: self.set_knob(k, n)))
                     for n, p in dm.backlights()]
            if k.empty_ok:
                items.insert(0, ("(auto)", "the eDP-2 DRM backlight, detected", lambda: self.set_knob(k, "")))
            if not names:
                self.notice(k.key, ["no backlight device under /sys/class/backlight"], "warn")
                return
            self.open_modal(Menu(k.key, items))
        else:
            lines = [k.desc]
            if k.kind == "int":
                lines.append(f"{k.lo}-{k.hi}" + (", or empty" if k.empty_ok else ""))
            self.open_modal(Prompt(k.key, lines, cur, lambda v: self.set_knob(k, v),
                                   validate=lambda v: dm.validate(k, v.strip())))

    def set_knob(self, k, value):
        m = self.model
        value = value.strip()
        r = self.act(lambda: m.config_set(k.key, value))
        if not r.ok:
            return
        if k.key == "BATTERY_LIMIT":
            if value:
                self.open_modal(Confirm("Apply now", [f"Set the charge limit to {value}% now and enable duo-bat-limit at login?"],
                                        lambda: (self.act(lambda: m.bat_limit(int(value))), self.act(lambda: m.enable("bat-limit")))))
            else:
                self.open_modal(Confirm("Battery limit cleared", ["Also disable duo-bat-limit at login?"],
                                        lambda: self.act(lambda: m.disable("bat-limit"))))
            return
        u = m.unit(k.daemon) if k.daemon else None
        if u is not None and u.state == "running":
            self.open_modal(Confirm("Restart the daemon",
                                    [f"{k.key} is read by duo-{k.daemon} when it starts.", f"Restart duo-{k.daemon} now?"],
                                    lambda: self.act(lambda: m.restart(k.daemon))))

    # ── drawing ──────────────────────────────────────────────────────────────

    def render(self, cv):
        t, g, m = self.t, self.g, self.model
        h, w = cv.h, cv.w
        if h < MIN_H or w < MIN_W:
            cv.put(0, 0, f"duo needs at least {MIN_W}x{MIN_H}; this terminal is {w}x{h}", t.warn)
            return
        # title bar
        running, failed, stalled = m.unit_summary()
        units = f"{running} ok"
        if failed:
            units += f", {failed} FAILED"
        if stalled:
            units += f", {stalled} enabled but stopped"
        kb = {"docked": "docked", "undocked": "undocked",
              "dead": "USB link DEAD"}.get(m.glance.keyboard, m.glance.keyboard)
        left = f" duo {m.version_text} {g.dot} {m.glance.model or 'unknown model'} {g.dot} keyboard {kb} {g.dot} {units} "
        clock = time.strftime(" %H:%M:%S ")
        cv.put(0, 0, " " * w, t.title)
        cv.put(0, 0, fit(left, w - len(clock), g), t.title)
        cv.put(0, w - len(clock), clock, t.title)
        # nav + body
        narrow = w < 90
        body_y = 1
        if narrow:
            x = 0
            for i, name in enumerate(self.order):
                label = f" {i + 1} {name} "
                cv.put(1, x, label, t.nav_sel if name == self.current else t.nav)
                x += len(label)
            cv.hline(2, 0, w, g, t.box)
            body_y = 3
            region = Region(body_y, 1, h - body_y - 2, w - 2)
        else:
            for i, name in enumerate(self.order):
                attr = t.nav_sel if name == self.current else t.nav
                cv.put(body_y + 1 + i * 2, 0, f" {i + 1} {name:<{NAV_WIDTH - 4}}", attr)
            for yy in range(body_y, h - 2):
                cv.put(yy, NAV_WIDTH, g.v, t.box)
            region = Region(body_y + 1, NAV_WIDTH + 2, h - body_y - 3, w - NAV_WIDTH - 3)
        view = self.views[self.current]
        view.render(cv, region)
        # status + hints
        cv.hline(h - 2, 0, w, g, t.box)
        text, level = self.status
        if text and time.time() - self.status_at < 30:
            cv.put(h - 2, 2, fit(f" {text} ", w - 4, g), t.level(level) | t.bold)
        elif m.errors:
            cv.put(h - 2, 2, fit(f" {m.errors[-1]} ", w - 4, g), t.warn)
        # The nav column already shows the view numbers, so the tail stays short:
        # every view's own keys have to fit on a 100-column terminal.
        hint = f"{view.hint}   ? help  q quit"
        cv.put(h - 1, 0, fit(" " + hint, w, g), t.dim)
        if self.modal is not None:
            self.modal.render(self, cv, Region(1, 0, h - 2, w))

    def render_text(self, w, h):
        cv = Canvas(h, w)
        self.render(cv)
        return cv.text()

    # ── input ────────────────────────────────────────────────────────────────

    def handle_key(self, ch):
        if self.modal is not None:
            self.modal.handle(self, ch)
            return
        view = self.views[self.current]
        if view.handle(ch):
            return
        if ch in (ord("q"), ord("Q")):
            self.quit = True
        elif ch == ord("?"):
            self.help()
        elif ch == KEY_TAB:
            self.switch(self.order[(self.order.index(self.current) + 1) % len(self.order)])
        elif ch == KEY_BTAB:
            self.switch(self.order[(self.order.index(self.current) - 1) % len(self.order)])
        elif ord("1") <= ch <= ord("9") and ch - ord("1") < len(self.order):
            self.switch(self.order[ch - ord("1")])
        elif ch == ord("r"):
            self.background(self.model.refresh_all)
            self.say("refreshing", "info")
        elif ch == KEY_ESC:
            self.status = ("", "info")

    def help(self):
        view = self.views[self.current]
        lines = [f"{view.name}", ""]
        lines.extend(view.help_lines)
        lines += ["", "Everywhere",
                  "1-6, Tab, Shift-Tab   switch view",
                  "Up/Down, j/k, PgUp/PgDn, g/G   move in the list this view shows",
                  "r        refresh everything now (the screen also refreshes itself every second)",
                  "Esc      clear the status line, or close the box in front of you",
                  "?        this help        q        quit",
                  "",
                  "In a box: Up/Down and PgUp/PgDn scroll it, Enter or Esc closes it, and a",
                  "question takes y or n.",
                  "",
                  "Every action here is a duo-cli or systemctl --user command; the status line",
                  "shows what it printed, and a failure opens the full output."]
        self.notice("Help", lines)

    # ── the curses loop ──────────────────────────────────────────────────────

    def run(self, scr):
        curses.curs_set(0) if hasattr(curses, "curs_set") else None
        try:
            curses.set_escdelay(25)
        except (AttributeError, curses.error):
            pass
        scr.keypad(True)
        scr.timeout(200)
        self.model.start()
        self.views[self.current].on_show()
        try:
            while not self.quit:
                try:
                    self.frame(scr)
                except KeyboardInterrupt:   # Ctrl-C is a way out, not a crash
                    self.quit = True
        finally:
            self.model.stop()

    def frame(self, scr):
        version = self.model.version
        now = int(time.time())
        if version != self._drawn_version or now != getattr(self, "_drawn_second", None):
            h, w = scr.getmaxyx()
            cv = Canvas(h, w)
            self.render(cv)
            scr.erase()
            cv.blit(scr)
            scr.refresh()
            self._drawn_version, self._drawn_second = version, now
        ch = scr.getch()
        if ch == -1:
            return
        if ch == KEY_RESIZE:
            self._drawn_version = -1
            return
        self.handle_key(ch)
        self._drawn_version = -1


def main(argv=None):
    """Entry point used by bin/duo: open the screen, or render a snapshot."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ascii_only = "--ascii" in argv or not utf8_terminal()
    argv = [a for a in argv if a != "--ascii"]
    if argv and argv[0] == "--snapshot":
        # `duo --snapshot [VIEW] [WxH]`: one frame as text, for CI and bug reports.
        view, size = "Overview", "100x32"
        for a in argv[1:]:
            if a.count("x") == 1 and a.replace("x", "").isdigit():
                size = a
            else:
                view = a.capitalize()
        w, h = (int(n) for n in size.split("x"))
        model = dm.Model()
        model.refresh_all()
        app = App(model, Theme(), ascii_only=True)
        if view not in app.views:
            print(f"duo: no view called {view!r}; one of {', '.join(app.order)}", file=sys.stderr)
            return 64
        app.current = view
        if view == "Doctor":
            model.doctor_lines, model.doctor_ok = dm.run_doctor()
            model.doctor_at = time.time()
        if view == "Logs":
            app.views[view].follow = True
        if view == "Displays":
            model.want_displays(True)
            model.refresh_slow(displays=True)
        print(app.render_text(w, h))
        return 0
    if curses is None:
        print("duo: this python has no curses module; use duo-cli", file=sys.stderr)
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("duo: the screen needs a terminal; use duo-cli <command> from a script, "
              "or `duo --snapshot` for one frame as text", file=sys.stderr)
        return 2
    if not os.environ.get("TERM"):
        os.environ["TERM"] = "xterm-256color"
    app_holder = {}

    def start(scr):
        app = App(dm.Model(), Theme.for_curses(), ascii_only=ascii_only)
        app_holder["app"] = app
        app.run(scr)
    try:
        curses.wrapper(start)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
