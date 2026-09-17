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

    def test_no_subscription_outside_the_daemon(self):
        # --once has no main loop; a handler on its proxy would never fire.
        w = watch_displays.Watcher()
        with mock.patch.object(watch_displays.displayctl, "proxy", side_effect=lambda: FakeProxy()):
            self.assertEqual(w.proxy().connected, [])


if __name__ == "__main__":
    unittest.main()
