"""The audio probe: Bluetooth profiles out of pw-dump, realtime out of /proc.

Nothing here runs pw-dump or systemctl; the parsers get the shapes those
tools produce, taken from a live session on 2026-09-20."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import audio_probe as ap  # noqa: E402


def device(name, desc, profile=None, api="bluez5"):
    info = {"props": {"device.api": api, "device.name": name, "device.description": desc}}
    if profile is not None:
        info["params"] = {"Profile": [profile]}
    return {"id": 202, "type": "PipeWire:Interface:Device", "info": info}


HEADSET = {"index": 261, "name": "headset-head-unit-msbc",
           "description": "Headset Head Unit (HSP/HFP, codec mSBC)"}
A2DP = {"index": 9, "name": "a2dp-sink", "description": "High Fidelity Playback (A2DP Sink, codec aptX)"}

# /proc/2200/task/2290/stat of pipewire's data loop, 2026-09-20: field 40 is
# rt_priority (20) and 41 the policy (2 = SCHED_RR)
STAT_RR = ("2290 (pw-data-loop) S 2120 2200 2200 0 -1 4194368 422 0 0 0 376 452 0 0 -21 0 3 0 819 "
           "144822272 8078 18446744073709551615 110000040325120 110000040327289 140723582334608 0 0 0 "
           "16386 4096 0 1 0 0 -1 8 20 2 0 0 0 110000040336432 110000040337424 110000063524864 "
           "140723582335674 140723582335692 140723582335692 140723582336998 0\n")
STAT_OTHER = STAT_RR.replace(" -1 8 20 2 0 0 0 ", " -1 8 0 0 0 0 0 ")


class BluetoothTest(unittest.TestCase):
    def test_a_headset_profile_is_named_and_flagged(self):
        out = ap.bluetooth_profiles([device("bluez_card.x", "EarFun Air Pro 4", HEADSET)])
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual((d["description"], d["profile"], d["headset"], d["stereo"]),
                         ("EarFun Air Pro 4", "headset-head-unit-msbc", True, False))
        self.assertIn("mSBC", d["profile_description"])

    def test_a2dp_is_stereo(self):
        d = ap.bluetooth_profiles([device("bluez_card.x", "Buds", A2DP)])[0]
        self.assertEqual((d["stereo"], d["headset"]), (True, False))

    def test_other_devices_and_shapes_are_ignored(self):
        objs = [device("alsa_card.pci", "HDA", A2DP, api="alsa"),
                {"id": 7, "type": "PipeWire:Interface:Node", "info": {"props": {"device.api": "bluez5"}}},
                device("bluez_card.y", "Off buds")]        # connected, no Profile param yet
        out = ap.bluetooth_profiles(objs)
        self.assertEqual([d["description"] for d in out], ["Off buds"])
        self.assertEqual((out[0]["profile"], out[0]["stereo"], out[0]["headset"]), ("", False, False))
        self.assertEqual(ap.bluetooth_profiles([]), [])
        self.assertEqual(ap.bluetooth_profiles([{"type": "x"}, 3, {"type": "PipeWire:Interface:Device"}]), [])


class RealtimeTest(unittest.TestCase):
    def fake_proc(self, root, pid, threads):
        for tid, comm, stat in threads:
            d = os.path.join(root, str(pid), "task", str(tid))
            os.makedirs(d)
            with open(os.path.join(d, "comm"), "w") as f:
                f.write(comm + "\n")
            with open(os.path.join(d, "stat"), "w") as f:
                f.write(stat)

    def test_only_the_data_loop_threads_count_and_the_policy_is_read(self):
        with tempfile.TemporaryDirectory() as proc:
            self.fake_proc(proc, 2200, [(2200, "pipewire", STAT_OTHER), (2275, "module-rt", STAT_OTHER),
                                        (2290, "pw-data-loop", STAT_RR)])
            self.fake_proc(proc, 2211, [(2292, "pw-data-loop", STAT_OTHER)])
            loops = ap.data_loops({"pipewire": 2200, "pipewire-pulse": 2211, "wireplumber": 9999}, proc)
            self.assertEqual(loops, [("pipewire", 2200, 2290, "rr", 20),
                                     ("pipewire-pulse", 2211, 2292, "other", 0)])

    def test_a_vanished_thread_is_unknown_not_a_crash(self):
        with tempfile.TemporaryDirectory() as proc:
            self.assertEqual(ap.thread_policy(proc, 1, 2), ("", 0))
            os.makedirs(os.path.join(proc, "1", "task", "2"))
            with open(os.path.join(proc, "1", "task", "2", "stat"), "w") as f:
                f.write("2 (x) S 1\n")
            self.assertEqual(ap.thread_policy(proc, 1, 2), ("", 0))


if __name__ == "__main__":
    unittest.main()
