"""lib/kb_init.py — HID plumbing that must be exactly right or silently wrong."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import kb_init  # noqa: E402
import kb_backlight  # noqa: E402


class Ioctls(unittest.TestCase):
    # _IOC(_IOC_READ|_IOC_WRITE, 'H', 0x06, len): dir bits 3<<30, len<<16, 'H'<<8, nr.
    def test_hidiocsfeature_numbers(self):
        self.assertEqual(kb_init.hidiocsfeature(17), 0xC0114806)
        self.assertEqual(kb_init.hidiocsfeature(16), 0xC0104806)
        self.assertEqual(kb_init.hidiocgfeature(17), 0xC0114807)
        self.assertEqual(kb_backlight.hidiocsfeature(17), kb_init.hidiocsfeature(17))


class Descriptor(unittest.TestCase):
    def test_declared_feature_size_walks_a_descriptor(self):
        # Vendor collection: usage page 0xff31, report id 0x5a, 8-bit x 16
        # feature items -> 1 + 16 = 17 bytes including the id.
        desc = bytes([
            0x06, 0x31, 0xff,   # Usage Page (vendor 0xff31)
            0x09, 0x76,         # Usage
            0xa1, 0x01,         # Collection (Application)
            0x85, 0x5a,         #   Report ID 0x5a
            0x75, 0x08,         #   Report Size 8
            0x95, 0x10,         #   Report Count 16
            0xb1, 0x02,         #   Feature (Data,Var,Abs)
            0xc0,               # End Collection
        ])
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            # declared_feature_size reads /sys/class/hidraw/<node>/device/report_descriptor;
            # exercise the parser through the same code path with a monkeypatched open.
            path = os.path.join(d, "report_descriptor")
            with open(path, "wb") as f:
                f.write(desc)
            real_open = open

            def fake_open(p, *a, **k):
                if p.endswith("/device/report_descriptor"):
                    return real_open(path, *a, **k)
                return real_open(p, *a, **k)
            kb_init.open = fake_open
            try:
                self.assertEqual(kb_init.declared_feature_size("/dev/hidrawX", 0x5a), 17)
                self.assertIsNone(kb_init.declared_feature_size("/dev/hidrawX", 0x5d))
            finally:
                del kb_init.open

    def test_candidate_sizes_prefer_declared_then_17_then_16(self):
        from unittest import mock
        with mock.patch.object(kb_init, "declared_feature_size", lambda node, rid: None):
            self.assertEqual(kb_init.candidate_sizes("/dev/hidrawX"), [17, 16])
        with mock.patch.object(kb_init, "declared_feature_size", lambda node, rid: 16):
            self.assertEqual(kb_init.candidate_sizes("/dev/hidrawX"), [16, 17])

    def test_handshake_is_the_kernel_string(self):
        self.assertEqual(bytes(kb_init.HANDSHAKE_TAIL), b"ASUS Tech.Inc.\x00")
        self.assertEqual(kb_init.REPORT_IDS, [0x5A, 0x5D, 0x5E])


if __name__ == "__main__":
    unittest.main()
