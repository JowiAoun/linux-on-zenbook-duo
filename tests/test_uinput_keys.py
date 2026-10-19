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


if __name__ == "__main__":
    unittest.main()
