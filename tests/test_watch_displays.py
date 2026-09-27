"""watch_displays: what can be checked without a session bus.

The module needs PyGObject to import at all, so every test here is skipped on
an interpreter without it; CI runs the suite once with and once without."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

try:
    import watch_displays  # noqa: E402
except SystemExit:  # the module exits 1 when gi is missing
    watch_displays = None


class FakeProxy:
    def __init__(self):
        self.connected = []

    def connect(self, signal, handler):
        self.connected.append((signal, handler))


@unittest.skipIf(watch_displays is None, "PyGObject not importable here")
class ProxyResubscribeTest(unittest.TestCase):
    def test_a_fresh_proxy_gets_the_monitors_changed_handler(self):
        # converge() drops the proxy after a D-Bus failure; the subscription
        # lives on the proxy object and has to be made again on the new one
        # or the daemon only wakes for the keyboard poll from then on.
        w = watch_displays.Watcher()
        with mock.patch.object(watch_displays.displayctl, "proxy", side_effect=lambda: FakeProxy()):
            w._subscribe = True
            first = w.proxy()
            self.assertEqual([s for s, _h in first.connected], ["g-signal"])
            self.assertIs(w.proxy(), first, "the proxy is cached while it works")
            w._proxy = None  # what converge() does on a DisplayCtlError
            second = w.proxy()
            self.assertIsNot(second, first)
            self.assertEqual([s for s, _h in second.connected], ["g-signal"])

    def test_a_stale_helper_is_tried_once_until_it_changes(self):
        # The installed helper predates login-layout (exit 64). One push, one
        # line; then nothing until the file's mtime changes (a reinstall).
        import tempfile

        class FakeProc:
            returncode = 64

            def poll(self):
                return 64
        calls = []
        w = watch_displays.Watcher()
        with tempfile.TemporaryDirectory() as d:
            helper = os.path.join(d, "zenduo-helper")
            with open(helper, "w") as f:
                f.write("#!/bin/sh\n")
            os.utime(helper, (1000, 1000))
            with mock.patch.object(watch_displays, "HELPER", helper), \
                 mock.patch.object(watch_displays.monitors_xml, "gdm_monitors_path", lambda: "/x"), \
                 mock.patch.object(watch_displays.subprocess, "Popen",
                                   lambda *a, **k: (calls.append(a), FakeProc())[1]), \
                 mock.patch.dict(os.environ, {"ZENDUO_LOGIN_SCREEN_LAYOUT": "1"}):
                w.push_login_screen()
                w.reap_children()
                w.push_login_screen()
                w.push_login_screen()
                self.assertEqual(len(calls), 1, "no retry while the helper is unchanged")
                os.utime(helper, (2000, 2000))
                w.push_login_screen()
                self.assertEqual(len(calls), 2, "a reinstalled helper is tried again")

    def test_touch_is_pinned_once_per_start_and_never_by_once(self):
        # GNOME's own guess puts both touchscreens on the top panel; the daemon
        # writes the mapping on the first state Mutter answers with, and
        # `duo apply-displays` (--once) never does, since it is the dock policy.
        w = watch_displays.Watcher()
        calls, lines = [], []
        with mock.patch.object(watch_displays.touch_map, "pin",
                               side_effect=lambda mons: (calls.append(mons), ["ELAN9009:00 touch -> eDP-2"])[1]), \
             mock.patch.object(watch_displays, "log", side_effect=lines.append):
            w.maybe_pin_touch({"eDP-1": {}})
            self.assertEqual(calls, [], "a Watcher that run() did not start pins nothing")
            w._touch_pending = True
            w.maybe_pin_touch({"eDP-1": {}})
            w.maybe_pin_touch({"eDP-1": {}})
        self.assertEqual(len(calls), 1)
        self.assertEqual(lines, ["touch mapping: ELAN9009:00 touch -> eDP-2"])

    def test_a_failed_write_is_one_line_not_a_crash(self):
        w = watch_displays.Watcher()
        w._touch_pending = True
        lines = []
        err = watch_displays.touch_map.MapError("gsettings set failed: no session")
        with mock.patch.object(watch_displays.touch_map, "pin", side_effect=err), \
             mock.patch.object(watch_displays, "log", side_effect=lines.append):
            w.maybe_pin_touch({})
        self.assertEqual(lines, ["touch mapping not written: gsettings set failed: no session"])

    def test_the_knob(self):
        with mock.patch.dict(os.environ, {"ZENDUO_TOUCH_MAPPING": "0"}):
            self.assertFalse(watch_displays.touch_mapping_on())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ZENDUO_TOUCH_MAPPING", None)
            self.assertTrue(watch_displays.touch_mapping_on())

    def test_no_subscription_outside_the_daemon(self):
        # --once has no main loop; a handler on its proxy would never fire.
        w = watch_displays.Watcher()
        with mock.patch.object(watch_displays.displayctl, "proxy", side_effect=lambda: FakeProxy()):
            self.assertEqual(w.proxy().connected, [])


if __name__ == "__main__":
    unittest.main()
