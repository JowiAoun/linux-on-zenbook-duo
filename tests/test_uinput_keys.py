"""lib/uinput_keys.py — the bytes the kernel's uinput ABI expects."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import uinput_keys  # noqa: E402


class Layout(unittest.TestCase):
    def test_user_dev_matches_the_kernel_struct(self):
        # name[80] + input_id (4 x u16) + ff_effects_max + 4 x int[ABS_CNT]
        self.assertEqual(len(uinput_keys.user_dev()), 80 + 8 + 4 + 4 * 4 * 64)

    def test_input_event_is_24_bytes_on_64_bit(self):
        if struct.calcsize("l") != 8:
            self.skipTest("32-bit userland")
        self.assertEqual(len(uinput_keys.event(1, 225, 1)), 24)

    def test_a_tap_is_press_sync_release_sync(self):
        events = uinput_keys.tap_events(uinput_keys.KEY_BRIGHTNESSUP)
        size = len(uinput_keys.event(0, 0, 0))
        decoded = [struct.unpack("llHHi", events[i:i + size])[2:]
                   for i in range(0, len(events), size)]
        self.assertEqual(decoded, [(1, 225, 1), (0, 0, 0), (1, 225, 0), (0, 0, 0)])

    def test_brightness_key_codes(self):
        # linux/input-event-codes.h
        self.assertEqual((uinput_keys.KEY_BRIGHTNESSDOWN, uinput_keys.KEY_BRIGHTNESSUP),
                         (224, 225))


class Grant(unittest.TestCase):
    """/dev/uinput lets its holder type anything, so the udev rule that opens
    it must only be written when the install asked for it."""

    def test_the_uinput_rule_is_opt_in(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "system", "45-udev.sh")) as f:
            script = f.read()
        always, _, rest = script.partition("EOF_RULES\n\n")
        self.assertNotIn('KERNEL=="uinput"', always)
        gate = rest.index("if feature_on BRIGHTNESS_OSD 0; then")
        rule = rest.index('KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"')
        self.assertLess(gate, rule)
        self.assertLess(rule, rest.index("\nelse\n", gate))


if __name__ == "__main__":
    unittest.main()
