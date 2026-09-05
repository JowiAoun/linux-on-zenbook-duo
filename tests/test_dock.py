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


class UsbLink(unittest.TestCase):
    """keyboard_docked is the physical fact; keyboard_usb_configured says whether
    the link works. 2026-09-05: the keyboard sat enumerated-but-unconfigured
    ("can't set config #1, error -71") for hours and nothing reported it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = dock.USB_DEVICES
        dock.USB_DEVICES = self.tmp.name

    def tearDown(self):
        dock.USB_DEVICES = self.old
        self.tmp.cleanup()

    def device(self, name, vid, pid, config):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d)
        for fn, val in (("idVendor", vid), ("idProduct", pid), ("bConfigurationValue", config)):
            if val is not None:
                with open(os.path.join(d, fn), "w") as f:
                    f.write(val + "\n")
        return d + os.sep

    def test_no_keyboard(self):
        self.device("1-2", "046d", "c52b", "1")  # some other USB device
        self.assertFalse(dock.keyboard_docked())
        self.assertIsNone(dock.keyboard_usb_configured())

    def test_working_link(self):
        d = self.device("3-6", "0b05", "1b2c", "1")
        self.assertTrue(dock.keyboard_docked())
        self.assertEqual(dock.keyboard_usb_device(), d)
        self.assertTrue(dock.keyboard_usb_configured())

    def test_enumerated_but_unconfigured_is_docked_and_dead(self):
        # bConfigurationValue reads empty after "can't set config #1, error -71"
        self.device("3-6", "0b05", "1b2c", "")
        self.assertTrue(dock.keyboard_docked(), "still lying on the bottom panel")
        self.assertFalse(dock.keyboard_usb_configured())

    def test_ids_are_matched_case_insensitively(self):
        self.device("3-6", "0B05", "1B2C", "1")
        self.assertTrue(dock.keyboard_docked())


if __name__ == "__main__":
    unittest.main()
