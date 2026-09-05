"""lib/dock.py — the manual-override marker the daemon and the CLI share."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import dock  # noqa: E402


class Override(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = dict(os.environ)
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        os.environ.pop("ZENDUO_MANAGED", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def test_write_read_clear(self):
        self.assertIsNone(dock.read_override())
        self.assertTrue(dock.write_override(True, ["eDP-1", "eDP-2"]))
        self.assertEqual(dock.read_override(), {"docked": True, "want": ["eDP-1", "eDP-2"]})
        self.assertTrue(dock.clear_override())
        self.assertIsNone(dock.read_override())
        self.assertFalse(dock.clear_override(), "clearing twice reports nothing was there")

    def test_daemon_applies_do_not_record_an_override(self):
        os.environ["ZENDUO_MANAGED"] = "1"
        self.assertFalse(dock.write_override(False, ["eDP-1"]))
        self.assertIsNone(dock.read_override())

    def test_marker_lives_under_the_runtime_dir(self):
        self.assertTrue(dock.override_path().startswith(self.tmp.name))

    def test_corrupt_marker_reads_as_none(self):
        os.makedirs(os.path.dirname(dock.override_path()), exist_ok=True)
        with open(dock.override_path(), "w") as f:
            f.write("{not json")
        self.assertIsNone(dock.read_override())


if __name__ == "__main__":
    unittest.main()
