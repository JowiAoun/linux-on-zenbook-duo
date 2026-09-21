"""`duo audio`: picking the device and the profile, and reading the switch back.

wpctl and pw-dump are replaced by callables, so a profile switch that never
lands is exercised without a headset. The shapes come from a live pw-dump on
2026-09-20 (EarFun Air Pro 4)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import audioctl as ac  # noqa: E402

PROFILES = [
    {"index": 0, "name": "off", "description": "Off", "priority": 0, "available": "yes"},
    {"index": 3, "name": "headset-head-unit", "description": "Headset Head Unit (HSP/HFP)", "priority": 1, "available": "yes"},
    {"index": 5, "name": "a2dp-sink-sbc", "description": "High Fidelity Playback (A2DP Sink, codec SBC)", "priority": 10, "available": "yes"},
    {"index": 6, "name": "a2dp-sink-sbc_xq", "description": "High Fidelity Playback (A2DP Sink, codec SBC-XQ)", "priority": 11, "available": "yes"},
    {"index": 9, "name": "a2dp-sink", "description": "High Fidelity Playback (A2DP Sink, codec aptX)", "priority": 20, "available": "yes"},
    {"index": 12, "name": "a2dp-sink-ldac", "description": "High Fidelity Playback (A2DP Sink, codec LDAC)", "priority": 30, "available": "no"},
    {"index": 260, "name": "headset-head-unit-cvsd", "description": "Headset Head Unit (HSP/HFP, codec CVSD)", "priority": 2, "available": "yes"},
    {"index": 261, "name": "headset-head-unit-msbc", "description": "Headset Head Unit (HSP/HFP, codec mSBC)", "priority": 3, "available": "yes"},
]


def objs(active=PROFILES[7], extra=()):
    dev = {"id": 202, "type": "PipeWire:Interface:Device",
           "info": {"props": {"device.api": "bluez5", "device.name": "bluez_card.70_5A_6F_6B_3B_81",
                              "device.description": "EarFun Air Pro 4"},
                    "params": {"Profile": [active] if active else [], "EnumProfile": PROFILES}}}
    meta = {"id": 31, "type": "PipeWire:Interface:Metadata", "props": {"metadata.name": "default"},
            "metadata": [{"subject": 0, "key": "default.audio.sink", "type": "Spa:String:JSON",
                          "value": {"name": "bluez_output.70_5A_6F_6B_3B_81.1"}}]}
    node = {"id": 201, "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "bluez_output.70_5A_6F_6B_3B_81.1", "node.description": "EarFun Air Pro 4"}}}
    alsa = {"id": 50, "type": "PipeWire:Interface:Device", "info": {"props": {"device.api": "alsa"}}}
    return [alsa, dev, meta, node, *extra]


class ReadingTest(unittest.TestCase):
    def test_devices_profiles_and_the_default_sink(self):
        devs = ac.bluetooth_devices(objs())
        self.assertEqual([d["description"] for d in devs], ["EarFun Air Pro 4"])
        self.assertEqual(devs[0]["active"]["name"], "headset-head-unit-msbc")
        self.assertEqual(len(devs[0]["profiles"]), len(PROFILES))
        self.assertEqual(ac.default_sink(objs()), ("bluez_output.70_5A_6F_6B_3B_81.1", "EarFun Air Pro 4"))
        self.assertEqual(ac.default_sink([]), ("", ""))
        self.assertIsNone(ac.bluetooth_devices(objs(active=None))[0]["active"])

    def test_picking_the_device(self):
        one = ac.bluetooth_devices(objs())
        self.assertEqual(ac.pick_device(one)["description"], "EarFun Air Pro 4")
        self.assertEqual(ac.pick_device(one, "earfun")["description"], "EarFun Air Pro 4")
        with self.assertRaises(ac.Problem):
            ac.pick_device([])
        with self.assertRaises(ac.Problem):
            ac.pick_device(one, "sony")
        two = one + [dict(one[0], description="Sony WH", name="bluez_card.x")]
        with self.assertRaises(ac.Problem):
            ac.pick_device(two)
        self.assertEqual(ac.pick_device(two, "sony")["name"], "bluez_card.x")

    def test_best_profile_skips_what_the_device_cannot_do(self):
        dev = ac.bluetooth_devices(objs())[0]
        # LDAC has the highest priority but available=no, so aptX wins
        self.assertEqual(ac.best_profile(dev, "stereo")["name"], "a2dp-sink")
        self.assertEqual(ac.best_profile(dev, "headset")["name"], "headset-head-unit-msbc")
        self.assertEqual(ac.profile_by(dev, "9")["name"], "a2dp-sink")
        self.assertEqual(ac.profile_by(dev, "headset-head-unit-cvsd")["index"], 260)
        self.assertIsNone(ac.profile_by(dev, "nope"))
        bare = dict(dev, profiles=[PROFILES[0]])
        self.assertIsNone(ac.best_profile(bare, "stereo"))


class SwitchTest(unittest.TestCase):
    def test_already_on_it_asks_for_nothing(self):
        dev = ac.bluetooth_devices(objs(active=PROFILES[4]))[0]
        calls = []
        ended = ac.switch(dev, PROFILES[4], setter=lambda i, x: calls.append((i, x)) or "", sleep=lambda s: None)
        self.assertEqual((calls, ended["name"]), ([], "a2dp-sink"))

    def test_the_switch_is_read_back_from_the_device(self):
        dev = ac.bluetooth_devices(objs())[0]
        calls, polls = [], []

        def reader():
            polls.append(1)
            return ac.bluetooth_devices(objs(active=PROFILES[4] if len(polls) >= 2 else PROFILES[7]))
        ended = ac.switch(dev, PROFILES[4], setter=lambda i, x: calls.append((i, x)) or "",
                          reader=reader, sleep=lambda s: None)
        self.assertEqual(calls, [(202, 9)])
        self.assertEqual((ended["name"], len(polls)), ("a2dp-sink", 2))

    def test_a_switch_that_never_lands_is_a_failure(self):
        dev = ac.bluetooth_devices(objs())[0]
        with self.assertRaises(ac.Problem) as cm:
            ac.switch(dev, PROFILES[4], setter=lambda i, x: "", reader=lambda: ac.bluetooth_devices(objs()),
                      sleep=lambda s: None, timeout=0)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("still on headset-head-unit-msbc", str(cm.exception))

    def test_wpctl_refusing_is_reported(self):
        dev = ac.bluetooth_devices(objs())[0]
        with self.assertRaises(ac.Problem) as cm:
            ac.switch(dev, PROFILES[4], setter=lambda i, x: "Object '202' not found", sleep=lambda s: None)
        self.assertIn("wpctl refused", str(cm.exception))


class UsageTest(unittest.TestCase):
    def test_bad_verbs_exit_64(self):
        self.assertEqual(ac.main(["bogus"]), 64)
        self.assertEqual(ac.main(["profile"]), 64)
        self.assertEqual(ac.main(["status", "x"]), 64)


if __name__ == "__main__":
    unittest.main()
