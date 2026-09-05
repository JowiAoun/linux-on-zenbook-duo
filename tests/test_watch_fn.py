"""lib/watch_fn.py — what the hotkey daemon says and does, without a keyboard."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import dock  # noqa: E402
import watch_fn  # noqa: E402


class AbsentKeyboard(unittest.TestCase):
    """2026-09-05: the keyboard died on USB (enumerated, "can't set config",
    no hidraw nodes) and watch-fn went silent for five hours because the
    read-error path reset its node set without ever reporting what it found."""

    def setUp(self):
        self.saved = (dock.keyboard_docked, dock.keyboard_usb_configured)

    def tearDown(self):
        dock.keyboard_docked, dock.keyboard_usb_configured = self.saved

    def fake(self, docked, configured):
        dock.keyboard_docked = lambda: docked
        dock.keyboard_usb_configured = lambda dev=None: configured

    def test_undocked_is_waiting(self):
        self.fake(False, None)
        self.assertIn("undocked", watch_fn.absent_reason())

    def test_dead_usb_link_is_named(self):
        self.fake(True, False)
        msg = watch_fn.absent_reason()
        self.assertIn("pogo pins", msg)
        self.assertIn("re-seated", msg)

    def test_docked_and_configured_but_no_nodes_is_still_waiting(self):
        # A working link with no hidraw nodes yet (udev still binding): not the
        # dead-link message, which would send the user to re-seat a fine keyboard.
        self.fake(True, True)
        self.assertNotIn("re-seated", watch_fn.absent_reason())


if __name__ == "__main__":
    unittest.main()
