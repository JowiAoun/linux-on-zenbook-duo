"""The duo screen, rendered to text instead of a terminal.

Every view is drawn through the Canvas with a model that was filled by hand,
so these run on a machine with no systemd user session and no journal. The
last test drives the real curses program through a pseudo-terminal and is
skipped where that cannot work."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import duo_model as dm  # noqa: E402
import duo_tui as tui  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def stub_model():
    """A Model with believable data and nothing running."""
    m = dm.Model()
    g = dm.Glance(model="ASUS Zenbook Duo UX8406MA_UX8406MA", kernel="7.0.0-31-generic",
                  panels=[("eDP-1", "connected", "enabled"), ("eDP-2", "connected", "disabled")],
                  keyboard="docked", backlights=[("intel_backlight", 40), ("card1-eDP-2-backlight", 40)],
                  kb_level=2, battery_node="/sys/x", battery_now="80", memory_sets=2,
                  login_state="in step", helper=True, udev=True, amp_state="ok", session="wayland")
    m.glance = g
    feats = {f.name: f for f in dm.FEATURES}
    m.units = [
        dm.Unit(feats["watch-displays"], load="loaded", active="active", sub="running", result="success",
                file_state="enabled", since="Sun 2026-09-13 19:57:27 EDT", pid=3917, fragment="/x/duo-watch-displays.service"),
        dm.Unit(feats["watch-fn"], load="loaded", active="failed", sub="failed", result="exit-code",
                restarts=3, exec_status=13, exec_code="exited", file_state="enabled", fragment="/x/duo-watch-fn.service"),
        dm.Unit(feats["watch-backlight"]),
        dm.Unit(feats["watch-rotation"]),
        dm.Unit(feats["bat-limit"], load="loaded", active="inactive", sub="dead", result="success",
                file_state="enabled", since="Mon 2026-09-14 11:15:25 EDT"),
        dm.Unit(feats["amp-check"], load="loaded", active="active", sub="running", result="success", file_state="enabled"),
    ]
    m.config_path = "/home/duo/.config/zenduo/zenduo.conf"
    m.config = {"APPLY_METHOD": "temporary", "BATTERY_LIMIT": "80", "BACKLIGHT_SOURCE": "intel_backlight",
                "BACKLIGHT_TARGET": "", "KB_BACKLIGHT_RESTORE": "1", "DOCK_POLICY": "1",
                "REMEMBER_LAYOUT": "1", "LOGIN_SCREEN_LAYOUT": "1"}
    now = time.time()
    m.entries.extend([
        dm.Entry(now - 300, "watch-fn: keyboard present on /dev/hidraw4 — sending init", 5, "duo-watch-fn.service", "zenduo", "1"),
        dm.Entry(now - 200, "watch-fn: hotkey mode not confirmed (attempt 1) — media keys are dead", 5, "duo-watch-fn.service", "zenduo", "1"),
        dm.Entry(now - 100, "watch-displays: docked, bottom panel is under the keyboard: [eDP-1, eDP-2] -> [eDP-1]", 5, "duo-watch-displays.service", "zenduo", "2"),
    ])
    m.displays = {"enabled": ["eDP-1"], "layout_mode": 2,
                  "monitors": {"eDP-1": {"vendor": "SDC", "product": "0x41a0", "serial": "",
                                         "modes": [{"id": "1920x1200@60", "width": 1920, "height": 1200,
                                                    "refresh": 60.0, "is_current": True}]},
                               "eDP-2": {"vendor": "SDC", "product": "0x41a0", "serial": "", "modes": []}},
                  "layout": {"eDP-1": {"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": True}}}
    m.layout_lines = ["monitor set : eDP-1 (SDC 0x41a0) · eDP-2 (SDC 0x41a0)", "on screen   : eDP-1 1920x1200@60 primary · eDP-2 off",
                      "mode        : laptop", "remembered  : this layout (it comes back on its own)"]
    m.doctor_lines = dm.parse_doctor("-- system --\n  [ OK ] model: fine\n  [WARN] no gnome-shell\n== summary: 1 ok, 1 warnings, 0 failures (0 gate-critical) ==\n== GATE: no MUST failures. ==\n")
    m.doctor_at = now
    return m


def app_for(model=None, ascii_only=True):
    return tui.App(model or stub_model(), tui.Theme(), ascii_only=ascii_only)


class CanvasTest(unittest.TestCase):
    def test_put_clips_at_every_edge(self):
        cv = tui.Canvas(2, 5)
        cv.put(0, 3, "abcdef")       # off the right edge
        cv.put(1, -2, "xyz")         # starts left of the canvas
        cv.put(5, 0, "never")        # below
        cv.put(0, 0, "a\tb\x01")     # a tab and a control character
        self.assertEqual(cv.text(), "a  b?\nz")

    def test_box_and_title_stay_inside(self):
        cv = tui.Canvas(3, 12)
        cv.box(tui.Region(0, 0, 3, 12), tui.Glyphs(True), title="a very long title")
        rows = cv.text().splitlines()
        self.assertEqual(rows[0][0], "+")
        self.assertEqual(rows[0][-1], "+")
        self.assertEqual(rows[2], "+----------+")

    def test_fit_and_wrap(self):
        g = tui.Glyphs(True)
        self.assertEqual(tui.fit("abcdef", 4, g), "abc~")
        self.assertEqual(tui.fit("abc", 4, g), "abc")
        self.assertEqual(tui.fit("abc", 0, g), "")
        self.assertEqual(tui.wrap("one two three", 7), ["one two", "three"])
        self.assertEqual(tui.wrap("", 7), [""])


class CursorTest(unittest.TestCase):
    def test_cursor_scrolls_the_window(self):
        c = tui.Cursor()
        for _ in range(7):
            c.key(tui.KEY_DOWN, 20, 5)
        self.assertEqual((c.i, c.top), (7, 3))
        c.key(tui.KEY_END, 20, 5)
        self.assertEqual((c.i, c.top), (19, 15))
        c.key(tui.KEY_HOME, 20, 5)
        self.assertEqual((c.i, c.top), (0, 0))
        c.key(tui.KEY_NPAGE, 20, 5)
        self.assertEqual(c.i, 4)
        self.assertFalse(c.key(ord("x"), 20, 5))

    def test_cursor_survives_a_shrinking_list(self):
        c = tui.Cursor()
        c.i = 9
        c.clamp(3, 5)
        self.assertEqual(c.i, 2)
        c.clamp(0, 5)
        self.assertEqual((c.i, c.top), (0, 0))


class RenderTest(unittest.TestCase):
    def test_every_view_renders_at_a_normal_size(self):
        app = app_for()
        for name in app.order:
            app.current = name
            text = app.render_text(100, 30)
            self.assertIn(name, text)
            self.assertLessEqual(max(len(line) for line in text.splitlines()), 100)
            self.assertEqual(len(text.splitlines()), 30)

    def test_overview_says_what_matters(self):
        app = app_for()
        text = app.render_text(110, 34)
        self.assertIn("docked (USB, on the pogo pins)", text)
        self.assertIn("x failed", text)                 # watch-fn, with the ASCII badge
        self.assertIn("exit 13", text)
        self.assertIn("hotkey mode not confirmed", text)  # under Recent problems
        self.assertIn("2 ok, 1 FAILED", text)           # the title bar

    def test_services_detail_pane_shows_the_units_own_errors(self):
        app = app_for()
        app.current = "Services"
        app.views["Services"].cur.i = 1  # watch-fn
        text = app.render_text(110, 34)
        self.assertIn("duo-watch-fn.service: failed/failed", text)
        self.assertIn("restarts 3", text)
        self.assertIn("hotkey mode not confirmed", text)
        self.assertNotIn("bottom panel is under the keyboard", text)  # another unit's line

    def test_settings_marks_home_manager(self):
        app = app_for()
        app.model.config_hm = True
        app.current = "Settings"
        self.assertIn("written by home-manager", app.render_text(100, 30))

    def test_narrow_and_tiny_terminals(self):
        app = app_for()
        narrow = app.render_text(70, 24)
        self.assertIn("1 Overview", narrow.splitlines()[1])   # tabs across the top
        tiny = app.render_text(30, 5)
        self.assertIn("needs at least", tiny)

    def test_unicode_glyphs_when_allowed(self):
        app = app_for(ascii_only=False)
        self.assertIn("─", app.render_text(100, 30))


class KeysTest(unittest.TestCase):
    def test_digits_and_tab_switch_views(self):
        app = app_for()
        app.handle_key(ord("3"))
        self.assertEqual(app.current, "Settings")
        app.handle_key(tui.KEY_TAB)
        self.assertEqual(app.current, "Displays")
        app.handle_key(tui.KEY_BTAB)
        self.assertEqual(app.current, "Settings")
        app.handle_key(ord("q"))
        self.assertTrue(app.quit)

    def test_help_opens_and_closes(self):
        app = app_for()
        app.handle_key(ord("?"))
        self.assertIsInstance(app.modal, tui.Notice)
        self.assertIn("Everywhere", app.render_text(100, 30))
        app.handle_key(tui.KEY_ESC)
        self.assertIsNone(app.modal)

    def test_a_menu_runs_its_item(self):
        app = app_for()
        done = []
        app.open_modal(tui.Menu("Pick", [("a", "first", lambda: done.append("a")),
                                         ("b", "second", lambda: done.append("b"))]))
        app.handle_key(tui.KEY_DOWN)
        app.handle_key(10)
        self.assertEqual(done, ["b"])
        self.assertIsNone(app.modal)

    def test_a_prompt_edits_and_validates(self):
        app = app_for()
        got = []
        app.open_modal(tui.Prompt("Limit", ["20-100"], "8", got.append,
                                  validate=lambda v: "" if v.isdigit() and 20 <= int(v) <= 100 else "between 20 and 100"))
        app.handle_key(ord("0"))          # "80"
        app.handle_key(tui.KEY_LEFT)
        app.handle_key(ord("1"))          # "810"
        app.handle_key(10)                # refused, stays open
        self.assertIsInstance(app.modal, tui.Prompt)
        self.assertIn("between 20 and 100", app.render_text(100, 30))
        app.handle_key(tui.KEY_BACKSPACE if hasattr(tui, "KEY_BACKSPACE") else 127)
        app.handle_key(10)
        self.assertEqual(got, ["80"])
        self.assertIsNone(app.modal)

    def test_confirm_needs_a_yes(self):
        app = app_for()
        done = []
        app.open_modal(tui.Confirm("Sure?", ["really"], lambda: done.append(1)))
        app.handle_key(ord("n"))
        self.assertEqual(done, [])
        app.open_modal(tui.Confirm("Sure?", ["really"], lambda: done.append(1)))
        app.handle_key(ord("y"))
        self.assertEqual(done, [1])

    def test_a_failed_action_opens_its_output(self):
        app = app_for()
        app.act(lambda: dm.Result(False, "duo enable x", "unit duo-x is not installed\nrun ./install.sh --user"))
        self.assertIsInstance(app.modal, tui.Notice)
        self.assertEqual(app.status[1], "err")
        self.assertIn("not installed", app.render_text(100, 30))

    def test_logs_filter_and_errors_only(self):
        app = app_for()
        app.current = "Logs"
        logs = app.views["Logs"]
        logs.errors_only = True
        self.assertEqual([e.level for e in logs.entries()], ["err"])
        logs.errors_only = False
        logs.set_filter("docked")
        self.assertEqual(len(logs.entries()), 1)
        logs.source = "duo-watch-fn.service"
        logs.set_filter("")
        self.assertEqual(len(logs.entries()), 2)

    def test_settings_space_flips_a_bool_through_the_model(self):
        app = app_for()
        calls = []
        app.model.config_set = lambda k, v: (calls.append((k, v)), dm.Result(True, f"config set {k}", f"{k}={v}"))[1]
        app.current = "Settings"
        app.views["Settings"].cur.i = 5      # DOCK_POLICY
        app.handle_key(ord(" "))
        self.assertEqual(calls, [("DOCK_POLICY", "0")])
        # the daemon that reads it is running, so a restart is offered
        self.assertIsInstance(app.modal, tui.Confirm)


@unittest.skipUnless(tui.curses is not None and hasattr(os, "forkpty"), "needs curses and a pty")
class RealTerminalTest(unittest.TestCase):
    def test_the_program_starts_switches_views_and_quits(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.environ["TERM"] = "xterm-256color"
            os.execv(os.path.join(ROOT, "bin", "duo"), ["duo", "--ascii"])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        out = b""

        def drain(seconds):
            nonlocal out
            end = time.time() + seconds
            while time.time() < end:
                r, _, _ = select.select([fd], [], [], 0.1)
                if r:
                    try:
                        out += os.read(fd, 65536)
                    except OSError:
                        return
        drain(3.0)
        for key in (b"2", b"3", b"4", b"?", b"\x1b", b"6", b"1"):
            os.write(fd, key)
            drain(0.7)
        os.write(fd, b"q")
        drain(1.0)
        status = None
        for _ in range(100):
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail("duo did not quit on q")
        text = out.decode("utf-8", "replace")
        self.assertNotIn("Traceback", text)
        self.assertEqual(status, 0, text[-500:])
        for word in ("Overview", "Services", "Settings", "Displays", "Logs", "Everywhere"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
