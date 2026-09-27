"""touch_map: which digitizer is which, what GNOME's setting should say, and
when to leave it alone.

Nothing here runs gsettings or talks to Mutter: the store is a dict, the
monitors are the dicts displayctl.parse_monitors() returns, and the sysfs
tree and /proc/interrupts are written into a temporary directory. The values
are the ones this machine reported on 2026-09-27."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import touch_map as tm  # noqa: E402

TOUCH, PEN = "org.gnome.desktop.peripherals.touchscreen", "org.gnome.desktop.peripherals.tablet"
PANEL = {"vendor": "SDC", "product": "0x41a0", "serial": "0x00000000"}
TWINS = {"eDP-1": dict(PANEL, connector="eDP-1"), "eDP-2": dict(PANEL, connector="eDP-2")}
TOP = tm.Digitizer("ELAN9008", "ELAN9008:00", "04f3", "4259", "eDP-1")
BOTTOM = tm.Digitizer("ELAN9009", "ELAN9009:00", "04f3", "42ec", "eDP-2")


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def get(self, schema, path):
        return self.values.get((schema, path))

    def set(self, schema, path, value):
        self.writes.append((schema, path, list(value)))
        self.values[(schema, path)] = list(value)


def at(schema, d):
    group = "touchscreens" if schema == TOUCH else "tablets"
    return (schema, f"/org/gnome/desktop/peripherals/{group}/{d.ids}/")


class DigitizersTest(unittest.TestCase):
    def sysfs(self, root, ids):
        for acpi, hid in ids:
            dev = os.path.join(root, f"i2c-{acpi}:00")
            for sub in (hid, "power", "driver"):
                os.makedirs(os.path.join(dev, sub))

    def test_ids_come_from_sysfs_and_the_panel_from_the_acpi_name(self):
        with tempfile.TemporaryDirectory() as root:
            self.sysfs(root, [("ELAN9008", "0018:04F3:4259.0001"), ("ELAN9009", "0018:04F3:42EC.0002")])
            os.makedirs(os.path.join(root, "i2c-ELAN0001:00", "0018:04F3:0001.0003"))  # not a panel
            self.assertEqual(tm.digitizers(root), [TOP, BOTTOM])

    def test_another_unit_with_other_product_ids(self):
        # alesya-h's unit: 425B on top, 425A below; the pairing is by name
        with tempfile.TemporaryDirectory() as root:
            self.sysfs(root, [("ELAN9008", "0018:04F3:425B.0007"), ("ELAN9009", "0018:04F3:425A.0008")])
            got = [(d.ids, d.connector) for d in tm.digitizers(root)]
            self.assertEqual(got, [("04f3:425b", "eDP-1"), ("04f3:425a", "eDP-2")])

    def test_nothing_there(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(tm.digitizers(root), [])


class GVariantTest(unittest.TestCase):
    def test_round_trip(self):
        value = ["SDC", "0x41a0", "0x00000000", "eDP-2"]
        text = tm.to_gvariant(value)
        self.assertEqual(text, "['SDC', '0x41a0', '0x00000000', 'eDP-2']")
        self.assertEqual(tm.from_gvariant(text + "\n"), value)

    def test_quotes_and_backslashes_survive(self):
        value = ["A'B", "c\\d", "", "eDP-1"]
        self.assertEqual(tm.from_gvariant(tm.to_gvariant(value)), value)

    def test_odd_output(self):
        self.assertEqual(tm.from_gvariant("@as []"), [])
        self.assertIsNone(tm.from_gvariant("uint32 5"))
        self.assertIsNone(tm.from_gvariant("[1, 2]"))

    def test_gsettings_reads_the_shipped_default_as_unset(self):
        store = tm.GSettings()
        with mock.patch.object(tm, "run", return_value=(0, "['', '', '']\n")):
            self.assertIsNone(store.get(TOUCH, "/x/"))
        with mock.patch.object(tm, "run", return_value=(0, "['SDC', '0x41a0', '0x00000000', 'eDP-2']\n")):
            self.assertEqual(store.get(TOUCH, "/x/"), ["SDC", "0x41a0", "0x00000000", "eDP-2"])
        with mock.patch.object(tm, "run", return_value=(1, "No such schema")):
            with self.assertRaises(tm.MapError):
                store.get(TOUCH, "/x/")

    def test_gsettings_set_writes_one_typed_value(self):
        calls = []
        with mock.patch.object(tm, "run", side_effect=lambda argv, **k: (calls.append(argv), (0, ""))[1]):
            tm.GSettings().set(TOUCH, "/org/gnome/desktop/peripherals/touchscreens/04f3:42ec/",
                               ["SDC", "0x41a0", "0x00000000", "eDP-2"])
        self.assertEqual(calls, [["gsettings", "set",
                                  f"{TOUCH}:/org/gnome/desktop/peripherals/touchscreens/04f3:42ec/",
                                  "output", "['SDC', '0x41a0', '0x00000000', 'eDP-2']"]])


class PlanTest(unittest.TestCase):
    def test_unset_is_written_with_the_connector_for_touch_and_pen(self):
        store = FakeStore()
        steps = tm.plan([TOP, BOTTOM], TWINS, store)
        self.assertEqual([(s.digitizer.name, s.kind, s.action) for s in steps], [
            ("ELAN9008:00", "touch", "set"), ("ELAN9008:00", "pen", "set"),
            ("ELAN9009:00", "touch", "set"), ("ELAN9009:00", "pen", "set")])
        self.assertEqual(tm.apply(steps, store), 4)
        self.assertEqual(store.values[at(TOUCH, BOTTOM)], ["SDC", "0x41a0", "0x00000000", "eDP-2"])
        self.assertEqual(store.values[at(PEN, BOTTOM)], ["SDC", "0x41a0", "0x00000000", "eDP-2"])
        self.assertEqual(store.values[at(TOUCH, TOP)][3], "eDP-1")

    def test_in_place_writes_nothing(self):
        store = FakeStore()
        tm.apply(tm.plan([TOP, BOTTOM], TWINS, store), store)
        store.writes.clear()
        steps = tm.plan([TOP, BOTTOM], TWINS, store)
        self.assertEqual({s.action for s in steps}, {"ok"})
        self.assertEqual(tm.apply(steps, store), 0)
        self.assertEqual(store.writes, [])

    def test_three_values_from_the_old_command_are_replaced(self):
        # What `duo set-tablet-mapping` wrote before: the twins' shared EDID,
        # which Mutter resolves to eDP-1 for both.
        store = FakeStore({at(TOUCH, BOTTOM): ["SDC", "0x41a0", "0x00000000"]})
        step = next(s for s in tm.plan([BOTTOM], TWINS, store) if s.kind == "touch")
        self.assertEqual((step.action, step.want[3]), ("set", "eDP-2"))
        self.assertIn("three values", step.why)

    def test_a_swapped_connector_is_corrected(self):
        store = FakeStore({at(TOUCH, BOTTOM): ["SDC", "0x41a0", "0x00000000", "eDP-1"]})
        step = next(s for s in tm.plan([BOTTOM], TWINS, store) if s.kind == "touch")
        self.assertEqual((step.action, step.why), ("set", "points at eDP-1"))

    def test_a_hand_mapping_to_another_monitor_is_left_alone(self):
        mine = ["DEL", "DELL U2720Q", "ABC123"]
        store = FakeStore({at(PEN, TOP): mine})
        monitors = dict(TWINS, **{"DP-1": {"vendor": "DEL", "product": "DELL U2720Q", "serial": "ABC123"}})
        steps = tm.plan([TOP], monitors, store)
        pen = next(s for s in steps if s.kind == "pen")
        self.assertEqual(pen.action, "leave")
        tm.apply(steps, store)
        self.assertEqual(store.values[at(PEN, TOP)], mine)

    def test_a_panel_that_is_not_connected_is_skipped(self):
        store = FakeStore()
        steps = tm.plan([TOP, BOTTOM], {"eDP-1": TWINS["eDP-1"]}, store)
        self.assertEqual({s.action for s in steps if s.digitizer is BOTTOM}, {"skip"})
        tm.apply(steps, store)
        self.assertNotIn(at(TOUCH, BOTTOM), store.values)

    def test_pin_says_only_what_it_changed(self):
        store = FakeStore()
        lines = tm.pin(TWINS, store=store, digs=[TOP, BOTTOM])
        self.assertEqual(len(lines), 4)
        self.assertTrue(all("writes SDC 0x41a0 0x00000000" in line for line in lines))
        self.assertEqual(tm.pin(TWINS, store=store, digs=[TOP, BOTTOM]), [])


INTERRUPTS = """            CPU0       CPU1       CPU2
  24:          0       {bottom}          0  intel-gpio   18  ELAN9009:00
 117:        {top}          0          0  intel-gpio  151  ELAN9008:00
 120:        500        500        500  IR-PCI-MSI-0000:00:14.3    0-edge      iwlwifi
"""


def interrupts(top, bottom):
    return INTERRUPTS.format(top=top, bottom=bottom)


class IdentifyTest(unittest.TestCase):
    def test_counts_add_every_cpu(self):
        counts = tm.irq_counts(interrupts(26070, 7508))
        self.assertEqual((counts["ELAN9008:00"], counts["ELAN9009:00"], counts["iwlwifi"]), (26070, 7508, 1500))

    def run_identify(self, before, after):
        reads = iter([interrupts(*before), interrupts(*after)])
        return tm.identify([TOP, BOTTOM], 6, read=lambda: next(reads), sleep=lambda s: None)

    def test_the_touched_controller_answers(self):
        found, deltas = self.run_identify((26070, 7508), (26070, 8308))
        self.assertIs(found, BOTTOM)
        self.assertEqual(deltas, {"ELAN9008:00": 0, "ELAN9009:00": 800})

    def test_too_few_or_both_is_no_answer(self):
        self.assertIsNone(self.run_identify((100, 100), (110, 100))[0])
        self.assertIsNone(self.run_identify((100, 100), (400, 500))[0])

    def test_the_real_file_parses(self):
        if os.path.exists("/proc/interrupts"):
            self.assertIsInstance(tm.irq_counts(tm.read_interrupts()), dict)


class UsageTest(unittest.TestCase):
    def test_bad_arguments_exit_64(self):
        self.assertEqual(tm.main(["--bogus"]), 64)
        self.assertEqual(tm.main(["--show", "--reset"]), 64)
        self.assertEqual(tm.main(["--show", "5"]), 64)


if __name__ == "__main__":
    unittest.main()
