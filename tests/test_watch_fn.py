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

    def test_an_unknown_code_is_logged_once_per_run(self):
        # 0x3d arrived 41 times in a day (2026-09-27) and every arrival put two
        # lines in the journal, which filled the screen's Recent problems.
        from unittest import mock
        lines = []
        d = Recorder()
        with mock.patch.object(watch_fn, "log", side_effect=lines.append):
            for _ in range(5):
                d.dispatch(0x3D, "unmapped-0x3d")
            d.dispatch(0x9C, "unmapped-0x9c")
            d.dispatch(0x10, "brightness-down")
        self.assertEqual(len([ln for ln in lines if "0x3d" in ln]), 1)
        self.assertEqual(len([ln for ln in lines if "0x9c" in ln]), 1)
        self.assertIn("key 5a 10 -> brightness-down", lines)
        self.assertEqual(d.unhandled, {"unmapped-0x3d": 5, "unmapped-0x9c": 1})

    def test_every_default_action_is_handled_or_known_unbound(self):
        for action in watch_fn.DEFAULT_ACTIONS.values():
            self.assertIn(action, watch_fn.KNOWN_ACTIONS)
        self.assertLessEqual(watch_fn.HANDLED, watch_fn.KNOWN_ACTIONS)

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


class ReEnumeration(unittest.TestCase):
    """2026-09-16: five times in an evening the keyboard's nodes vanished and
    came back within 2 s; each time the daemon rescanned mid-teardown, sent
    the init to nodes that were gone, and logged "media keys are dead"."""

    def test_settled_nodes_waits_for_two_scans_that_agree(self):
        scans = iter([["/dev/hidraw5", "/dev/hidraw6"], ["/dev/hidraw4", "/dev/hidraw5", "/dev/hidraw6"],
                      ["/dev/hidraw4", "/dev/hidraw5", "/dev/hidraw6"], ["never"]])
        slept = []
        nodes = watch_fn.settled_nodes(lambda: next(scans), sleep=slept.append)
        self.assertEqual(nodes, ("/dev/hidraw4", "/dev/hidraw5", "/dev/hidraw6"))
        self.assertEqual(len(slept), 2)

    def test_settled_nodes_gives_up_after_its_tries(self):
        n = iter(range(100))
        nodes = watch_fn.settled_nodes(lambda: [f"/dev/hidraw{next(n)}"], sleep=lambda s: None, tries=3)
        self.assertEqual(nodes, ("/dev/hidraw3",))

    def test_the_first_attempts_are_not_an_alarm(self):
        early = watch_fn.failure_message(1, 1, 2)
        self.assertIn("waiting", early)
        self.assertNotIn("dead", early)
        denied = watch_fn.failure_message(13, 2, 4)
        self.assertIn("not accessible yet", denied)
        loud = watch_fn.failure_message(1, 3, 8)
        self.assertIn("dead", loud)
        self.assertIn("not confirmed", loud)
        self.assertIn("udev", watch_fn.failure_message(13, 3, 8))


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
