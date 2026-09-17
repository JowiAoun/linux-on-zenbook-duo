"""The screen's data layer: parsers, the error heuristics, validation.

Nothing here talks to systemd or the journal; the parsers get the exact text
those tools print, so a change in what the screen shows is caught here."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import duo_model as dm  # noqa: E402


SHOW = """Id=duo-watch-fn.service
LoadState=loaded
ActiveState=active
SubState=running
Result=success
NRestarts=2
ExecMainStatus=0
ExecMainCode=0
UnitFileState=enabled
ActiveEnterTimestamp=Sun 2026-09-13 19:57:27 EDT
MainPID=3920
FragmentPath=/home/duo/.config/systemd/user/duo-watch-fn.service

Id=duo-watch-backlight.service
LoadState=not-found
ActiveState=inactive
SubState=dead
Result=success
NRestarts=0
UnitFileState=

Id=duo-bat-limit.service
LoadState=loaded
ActiveState=inactive
SubState=dead
Result=success
NRestarts=0
ExecMainStatus=0
ExecMainCode=1
UnitFileState=enabled
InactiveEnterTimestamp=Mon 2026-09-14 11:15:25 EDT
"""


def feature(name):
    return next(f for f in dm.FEATURES if f.name == name)


class ParseShowTest(unittest.TestCase):
    def test_blocks_are_split_on_blank_lines(self):
        blocks = dm.parse_show(SHOW)
        self.assertEqual([b["Id"] for b in blocks],
                         ["duo-watch-fn.service", "duo-watch-backlight.service", "duo-bat-limit.service"])

    def test_a_running_daemon(self):
        u = dm.unit_from_props(feature("watch-fn"), dm.parse_show(SHOW)[0])
        self.assertEqual((u.state, u.level, u.restarts, u.pid, u.enabled), ("running", "ok", 2, 3920, True))

    def test_a_unit_that_is_not_installed(self):
        u = dm.unit_from_props(feature("watch-backlight"), dm.parse_show(SHOW)[1])
        self.assertEqual((u.state, u.level, u.installed), ("absent", "off", False))

    def test_a_oneshot_that_ran(self):
        u = dm.unit_from_props(feature("bat-limit"), dm.parse_show(SHOW)[2])
        self.assertEqual((u.state, u.level), ("ran", "ok"))

    def test_a_failed_unit(self):
        props = dict(dm.parse_show(SHOW)[0], ActiveState="failed", SubState="failed",
                     Result="exit-code", ExecMainStatus="1", ExecMainCode="exited")
        u = dm.unit_from_props(feature("watch-fn"), props)
        self.assertEqual((u.state, u.level, u.exec_status), ("failed", "err", 1))

    def test_an_enabled_unit_that_stopped_is_a_warning(self):
        props = dict(dm.parse_show(SHOW)[0], ActiveState="inactive", SubState="dead")
        u = dm.unit_from_props(feature("watch-fn"), props)
        self.assertEqual((u.state, u.level), ("stopped", "warn"))

    def test_hm_is_a_nix_store_symlink(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            link = os.path.join(d, "duo-watch-fn.service")
            os.symlink("/nix/store/000-home-manager-files/.config/systemd/user/duo-watch-fn.service", link)
            u = dm.Unit(feature("watch-fn"), fragment=link)
            self.assertTrue(u.hm)
            plain = os.path.join(d, "plain.service")
            open(plain, "w").close()
            self.assertFalse(dm.Unit(feature("watch-fn"), fragment=plain).hm)


class JournalTest(unittest.TestCase):
    LINE = ('{"__REALTIME_TIMESTAMP":"1789596176885074","PRIORITY":"5","MESSAGE":"synced 65%",'
            '"_SYSTEMD_USER_UNIT":"duo-watch-displays.service","SYSLOG_IDENTIFIER":"zenduo","_PID":"2538711"}')

    def test_a_syslog_line(self):
        e = dm.parse_journal_line(self.LINE)
        self.assertEqual((e.msg, e.pri, e.unit, e.source, e.pid),
                         ("synced 65%", 5, "duo-watch-displays.service", "watch-displays", "2538711"))
        self.assertAlmostEqual(e.ts, 1789596176.885074, places=3)
        self.assertEqual(e.level, "info")

    def test_a_kernel_line(self):
        e = dm.parse_journal_line('{"__REALTIME_TIMESTAMP":"1","PRIORITY":"3","MESSAGE":"cs35l41-hda: Failed waiting",'
                                  '"_TRANSPORT":"kernel","SYSLOG_IDENTIFIER":"kernel"}')
        self.assertEqual((e.unit, e.source, e.level), ("kernel", "kernel", "err"))

    def test_a_byte_array_message(self):
        # journald encodes a payload that is not UTF-8 as an array of bytes
        e = dm.parse_journal_line('{"__REALTIME_TIMESTAMP":"1","MESSAGE":[104,105,255]}')
        self.assertEqual(e.msg, "hi�")

    def test_garbage_is_skipped(self):
        self.assertIsNone(dm.parse_journal_line("not json"))
        self.assertIsNone(dm.parse_journal_line("[1,2]"))

    def test_level_heuristics(self):
        def level(msg, pri=6):
            return dm.Entry(0, msg, pri).level
        self.assertEqual(level("watch-fn: hotkey mode not confirmed (attempt 1)"), "err")
        self.assertEqual(level("kb_init: permission denied on hidraw"), "err")
        self.assertEqual(level("duo kb-backlight 2 failed (rc=13)"), "err")
        self.assertEqual(level("ApplyMonitorsConfig failed: x — retrying in 5s"), "err")
        self.assertEqual(level("ignoring unreadable fn-map.json"), "warn")
        self.assertEqual(level("no keyboard (undocked / BT off) — waiting"), "info")
        self.assertEqual(level("keyboard docked"), "info")
        self.assertEqual(level("anything", pri=3), "err")
        self.assertEqual(level("anything", pri=4), "warn")

    def test_matches_or_every_unit_with_the_identifiers(self):
        m = dm.journal_matches()
        self.assertEqual(m[0], "SYSLOG_IDENTIFIER=zenduo")
        self.assertIn("_SYSTEMD_USER_UNIT=duo-watch-fn.service", m)
        self.assertEqual(m.count("+"), len(m) // 2)


class DoctorTest(unittest.TestCase):
    TEXT = """== zenduo doctor 0.9.0 — 2026-09-17T04:19:52Z ==

-- system --
  [info] kernel: 7.0.0-31-generic
  [ OK ] model: ASUS Zenbook Duo UX8406MA_UX8406MA (the machine this project targets)
  [WARN] no gnome-shell
-- storage (V16) --
  [FAIL/MUST] no NVMe device visible
  [FAIL] something else

== summary: 1 ok, 1 warnings, 2 failures (1 gate-critical) ==
== GATE: NO-GO — a MUST check failed. ==
"""

    def test_kinds(self):
        kinds = [(ln.kind, ln.text[:12]) for ln in dm.parse_doctor(self.TEXT)]
        self.assertEqual(kinds, [
            ("summary", "zenduo docto"), ("section", "system"), ("info", "kernel: 7.0."),
            ("ok", "model: ASUS "), ("warn", "no gnome-she"), ("section", "storage (V16"),
            ("must", "no NVMe devi"), ("fail", "something el"), ("summary", "summary: 1 o"),
            ("summary", "GATE: NO-GO "),
        ])


class ValidateTest(unittest.TestCase):
    def test_bool_enum_int(self):
        k = dm.KNOB_BY_KEY
        self.assertEqual(dm.validate(k["DOCK_POLICY"], "1"), "")
        self.assertNotEqual(dm.validate(k["DOCK_POLICY"], "yes"), "")
        self.assertEqual(dm.validate(k["APPLY_METHOD"], "persistent"), "")
        self.assertNotEqual(dm.validate(k["APPLY_METHOD"], "never"), "")
        self.assertEqual(dm.validate(k["BATTERY_LIMIT"], "80"), "")
        self.assertEqual(dm.validate(k["BATTERY_LIMIT"], ""), "")
        self.assertNotEqual(dm.validate(k["BATTERY_LIMIT"], "10"), "")
        self.assertNotEqual(dm.validate(k["BATTERY_LIMIT"], "eighty"), "")
        self.assertNotEqual(dm.validate(k["DOCK_POLICY"], ""), "")

    def test_the_conf_allow_list_is_enforced(self):
        # lib/conf.sh ignores a value with any other character, so the screen
        # must refuse it before duo-cli would.
        self.assertNotEqual(dm.validate(dm.KNOB_BY_KEY["BACKLIGHT_SOURCE"], "x;rm -rf /"), "")


class ResultTest(unittest.TestCase):
    def test_summary_is_the_last_line(self):
        r = dm.Result(True, "duo enable x", "one\n\ntwo\n")
        self.assertEqual((r.lines, r.summary), (["one", "two"], "two"))
        self.assertEqual(dm.Result(False, "x").summary, "failed")

    def test_run_reports_a_missing_binary(self):
        rc, _out, err = dm.run(["/nonexistent/duo-cli", "x"])
        self.assertEqual(rc, 127)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main()
