"""lib/watch_fn.py — what the hotkey daemon says and does, without a keyboard."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import dock  # noqa: E402
import watch_fn  # noqa: E402


class Recorder(watch_fn.Dispatcher):
    """A Dispatcher that records instead of running anything."""

    def __init__(self):
        super().__init__()
        self.spawned, self.ran = [], []

    def spawn(self, argv):
        self.spawned.append(argv)

    def run(self, argv):
        self.ran.append(argv)


class FnRow(unittest.TestCase):
    def test_mainline_codes_for_mic_mute_and_emoji(self):
        # 2026-09-05: 5a 7c and 5a 7e arrived as "unmapped" 42 times between them.
        self.assertEqual(watch_fn.DEFAULT_ACTIONS[0x7C], "mic-mute")
        self.assertEqual(watch_fn.DEFAULT_ACTIONS[0x7E], "emoji")
        self.assertTrue({"mic-mute", "emoji"} <= watch_fn.KNOWN_ACTIONS)

    def test_mic_mute_toggles_the_default_source(self):
        d = Recorder()
        d.dispatch(0x7C, "mic-mute")
        self.assertEqual(d.spawned, [["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"]])

    def test_emoji_raises_the_ibus_picker(self):
        d = Recorder()
        d.dispatch(0x7E, "emoji")
        self.assertEqual(d.spawned, [["ibus", "emoji"]])

    def test_unknown_action_runs_nothing(self):
        d = Recorder()
        d.dispatch(0x3D, "unmapped-0x3d")
        self.assertEqual((d.spawned, d.ran), ([], []))

    def test_fn_map_override_wins_over_the_default(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "zenduo"))
            with open(os.path.join(tmp, "zenduo", "fn-map.json"), "w") as f:
                f.write('{"keys": {"camera-toggle": {"report": "5a 3d"}, "emoji": {"report": "5a 7e"}}}')
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                table = watch_fn.load_overrides()
            finally:
                if old is None:
                    del os.environ["XDG_CONFIG_HOME"]
                else:
                    os.environ["XDG_CONFIG_HOME"] = old
        self.assertEqual(table[0x3D], "camera-toggle")
        self.assertEqual(table[0x7E], "emoji")
        self.assertEqual(table[0x10], "brightness-down", "defaults survive an override file")


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
