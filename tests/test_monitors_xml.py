"""lib/monitors_xml.py — Mutter's layout database, which we now write.

The stakes: Mutter ignores monitors.xml WHOLESALE if it does not parse, so a
format mistake here does not degrade one layout, it throws away every
remembered monitor set. Hence the parse of mutter's own documented example,
the round-trip tests, and the guard in save().
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import monitors_xml as mx  # noqa: E402

# Verbatim from mutter's src/backends/meta-monitor-config-store.c header
# comment (gnome-46, read 2026-09-12): if this stops parsing, we have drifted
# from the format Mutter documents.
MUTTER_EXAMPLE = """<monitors version="2">
  <configuration>
    <logicalmonitor>
      <x>0</x>
      <y>0</y>
      <scale>1</scale>
      <monitor>
        <monitorspec>
          <connector>LVDS1</connector>
          <vendor>Vendor A</vendor>
          <product>Product A</product>
          <serial>Serial A</serial>
        </monitorspec>
        <mode>
          <width>1920</width>
          <height>1080</height>
          <rate>60.049972534179688</rate>
          <flag>interlace</flag>
        </mode>
      </monitor>
      <transform>
        <rotation>right</rotation>
        <flipped>no</flipped>
      </transform>
      <primary>yes</primary>
      <presentation>no</presentation>
    </logicalmonitor>
    <logicalmonitor>
      <x>1920</x>
      <y>1080</y>
      <monitor>
        <monitorspec>
          <connector>LVDS2</connector>
          <vendor>Vendor B</vendor>
          <product>Product B</product>
          <serial>Serial B</serial>
        </monitorspec>
        <mode>
          <width>1920</width>
          <height>1080</height>
          <rate>60.049972534179688</rate>
        </mode>
        <underscanning>yes</underscanning>
      </monitor>
      <presentation>yes</presentation>
    </logicalmonitor>
    <disabled>
      <monitorspec>
        <connector>LVDS3</connector>
        <vendor>Vendor C</vendor>
        <product>Product C</product>
        <serial>Serial C</serial>
      </monitorspec>
    </disabled>
  </configuration>
</monitors>
"""

# The two Duo panels are identical but for the connector, which is why the
# config key has to carry all four fields.
PANEL = ("SDC", "0x41a0", "0x00000000")
ACER = ("ACR", "KA272", "0x20918938")


def mode(width=2880, height=1800, refresh=120.0, current=True, **extra):
    out = {"id": f"{width}x{height}@{refresh:.3f}", "width": width,
           "height": height, "refresh": refresh, "preferred_scale": 2.0,
           "is_current": current, "is_preferred": True,
           "interlace": False, "variable": False}
    out.update(extra)
    return out


def monitor(connector, ident=PANEL, modes=None, underscanning=False):
    vendor, product, serial = ident
    return {"connector": connector, "vendor": vendor, "product": product,
            "serial": serial, "modes": modes or [mode()],
            "builtin": connector.startswith("eDP"),
            "underscanning": underscanning}


def logical(x, y, scale, connectors, primary=False, transform=0, ident=PANEL):
    return (x, y, scale, transform, primary,
            [(c,) + ident for c in connectors], {})


class ParseMutterExample(unittest.TestCase):
    def setUp(self):
        self.store = mx.parse(MUTTER_EXAMPLE)
        self.config = self.store.configurations[0]

    def test_one_configuration_with_two_logical_monitors(self):
        self.assertEqual(len(self.store.configurations), 1)
        self.assertEqual(len(self.config.logicals), 2)

    def test_key_covers_enabled_and_disabled_monitors(self):
        self.assertEqual([spec[0] for spec in self.config.key()],
                         ["LVDS1", "LVDS2", "LVDS3"])

    def test_rotation_and_flipped_become_a_transform(self):
        self.assertEqual(self.config.logicals[0].transform, 3)  # "right" = 270

    def test_primary_presentation_and_position(self):
        first, second = self.config.logicals
        self.assertTrue(first.primary)
        self.assertFalse(first.presentation)
        self.assertEqual((second.x, second.y), (1920, 1080))
        self.assertTrue(second.presentation)

    def test_mode_flags_and_underscanning(self):
        first = self.config.logicals[0].monitors[0]
        self.assertTrue(first.mode.interlace)
        self.assertAlmostEqual(first.mode.rate, 60.049972534179688)
        self.assertTrue(self.config.logicals[1].monitors[0].underscanning)

    def test_missing_scale_defaults_to_one(self):
        self.assertEqual(self.config.logicals[1].scale, 1.0)

    def test_disabled_monitor_is_not_enabled(self):
        self.assertEqual(self.config.enabled_connectors(), ["LVDS1", "LVDS2"])
        self.assertEqual([s.connector for s in self.config.disabled], ["LVDS3"])

    def test_round_trips_through_our_own_writer(self):
        again = mx.parse(mx.render(self.store))
        self.assertEqual(again.configurations[0].key(), self.config.key())
        self.assertEqual(again.configurations[0].shape(), self.config.shape())
        # And a second pass is byte-identical: rendering is stable.
        self.assertEqual(mx.render(again), mx.render(self.store))


class Format(unittest.TestCase):
    def render_one(self, logicals, disabled=()):
        return mx.render_configuration(mx.Configuration(logicals, disabled))

    def entry(self, connector="eDP-1", width=2880, height=1800, rate=120.0):
        return mx.MonitorEntry(mx.Spec(connector, *PANEL),
                               mx.Mode(width, height, rate))

    def test_rate_is_three_decimals(self):
        # Mutter matches a stored mode against a live one within 0.001 Hz and
        # writes %.3f itself; anything else risks not matching at all.
        text = self.render_one([mx.Logical(0, 0, 1.0, monitors=[
            self.entry(rate=74.97250366210938)])])
        self.assertIn("<rate>74.973</rate>", text)

    def test_scale_is_written_shortest(self):
        self.assertIn("<scale>1</scale>",
                      self.render_one([mx.Logical(0, 0, 1.0, monitors=[self.entry()])]))
        self.assertIn("<scale>1.25</scale>",
                      self.render_one([mx.Logical(0, 0, 1.25, monitors=[self.entry()])]))

    def test_no_transform_block_when_there_is_no_rotation(self):
        self.assertNotIn("<transform>",
                         self.render_one([mx.Logical(0, 0, 1.0, monitors=[self.entry()])]))

    def test_transform_maps_the_way_mutter_writes_it(self):
        for transform, rotation, flipped in ((1, "left", "no"), (2, "upside_down", "no"),
                                             (3, "right", "no"), (4, "normal", "yes"),
                                             (5, "left", "yes"), (7, "right", "yes")):
            text = self.render_one([mx.Logical(0, 0, 1.0, transform=transform,
                                               monitors=[self.entry()])])
            self.assertIn(f"<rotation>{rotation}</rotation>", text)
            self.assertIn(f"<flipped>{flipped}</flipped>", text)
            back = mx.parse(f'<monitors version="2">{text}</monitors>')
            self.assertEqual(back.configurations[0].logicals[0].transform, transform)

    def test_primary_is_only_written_when_true(self):
        self.assertNotIn("<primary>", self.render_one(
            [mx.Logical(0, 0, 1.0, primary=False, monitors=[self.entry()])]))
        self.assertIn("<primary>yes</primary>", self.render_one(
            [mx.Logical(0, 0, 1.0, primary=True, monitors=[self.entry()])]))

    def test_vendor_with_an_ampersand_is_escaped(self):
        entry = mx.MonitorEntry(mx.Spec("DP-1", "A & B", "<x>", ""),
                                mx.Mode(1920, 1080, 60.0))
        text = self.render_one([mx.Logical(0, 0, 1.0, monitors=[entry])])
        self.assertIn("<vendor>A &amp; B</vendor>", text)
        # Mutter's own writer does not escape; ours must, or the file that
        # comes back is not XML at all.
        back = mx.parse(f'<monitors version="2">{text}</monitors>')
        self.assertEqual(back.configurations[0].logicals[0].monitors[0].spec.vendor,
                         "A & B")

    def test_a_version_other_than_two_is_refused(self):
        with self.assertRaises(mx.FormatError):
            mx.parse('<monitors version="1"><configuration/></monitors>')
        with self.assertRaises(mx.FormatError):
            mx.parse("<not-monitors/>")
        with self.assertRaises(mx.FormatError):
            mx.parse("<monitors version=\"2\">")


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.monitors = {
            "eDP-1": monitor("eDP-1"),
            "eDP-2": monitor("eDP-2"),
            "HDMI-1": monitor("HDMI-1", ACER, [mode(1920, 1080, 74.97250366210938)]),
        }

    def test_enabled_and_disabled_are_both_recorded(self):
        live = [logical(0, 0, 1.0, ["HDMI-1"], primary=True, ident=ACER)]
        config = mx.snapshot(self.monitors, live)
        self.assertEqual(config.enabled_connectors(), ["HDMI-1"])
        self.assertEqual(sorted(s.connector for s in config.disabled),
                         ["eDP-1", "eDP-2"])

    def test_key_is_the_whole_connected_set_whatever_is_enabled(self):
        both = mx.snapshot(self.monitors, [logical(0, 0, 1.0, ["HDMI-1"], ident=ACER)])
        neither = mx.snapshot(self.monitors, [logical(0, 0, 2.0, ["eDP-1"])])
        self.assertEqual(both.key(), neither.key())
        self.assertEqual(both.key(), mx.topology(self.monitors))

    def test_the_two_panels_are_distinguished_by_connector_alone(self):
        key = mx.topology(self.monitors)
        panels = [spec for spec in key if spec[0].startswith("eDP")]
        self.assertEqual(len(panels), 2)
        self.assertNotEqual(panels[0], panels[1])
        self.assertEqual(panels[0][1:], panels[1][1:], "same vendor/product/serial")

    def test_mode_position_scale_and_primary_come_from_live_state(self):
        live = [logical(0, 0, 2.0, ["eDP-1"], primary=True),
                logical(0, 900, 2.0, ["eDP-2"])]
        config = mx.snapshot(self.monitors, live)
        first = config.logicals[0]
        self.assertEqual((first.x, first.y, first.scale, first.primary),
                         (0, 0, 2.0, True))
        self.assertEqual((first.monitors[0].mode.width, first.monitors[0].mode.height),
                         (2880, 1800))
        self.assertEqual(config.logicals[1].y, 900)

    def test_a_mirror_is_one_logical_monitor_with_two_monitors(self):
        live = [(0, 0, 1.0, 0, True,
                 [("eDP-1",) + PANEL, ("HDMI-1",) + ACER], {})]
        config = mx.snapshot(self.monitors, live)
        self.assertTrue(config.is_mirrored())
        self.assertEqual(len(config.logicals), 1)
        self.assertEqual(config.enabled_connectors(), ["eDP-1", "HDMI-1"])
        again = mx.parse(mx.render(mx.Store([config])))
        self.assertTrue(again.configurations[0].is_mirrored())

    def test_a_monitor_with_no_current_mode_records_no_mode(self):
        self.monitors["eDP-1"] = monitor("eDP-1", modes=[mode(current=False)])
        config = mx.snapshot(self.monitors, [logical(0, 0, 2.0, ["eDP-1"])])
        self.assertIsNone(config.logicals[0].monitors[0].mode)
        mx.render(mx.Store([config]))  # must still render


class StoreOperations(unittest.TestCase):
    def config_for(self, connectors, enabled, scale=1.0):
        monitors = {c: monitor(c, ACER if c.startswith("HDMI") else PANEL)
                    for c in connectors}
        live = [logical(0, 0, scale, [c],
                        ident=ACER if c.startswith("HDMI") else PANEL)
                for c in enabled]
        return mx.snapshot(monitors, live)

    def test_replace_matches_on_the_monitor_set(self):
        store = mx.Store([self.config_for(["eDP-1", "HDMI-1"], ["eDP-1"])])
        self.assertTrue(store.replace(self.config_for(["eDP-1", "HDMI-1"], ["HDMI-1"])))
        self.assertEqual(len(store.configurations), 1)
        self.assertEqual(store.configurations[0].enabled_connectors(), ["HDMI-1"])

    def test_replace_is_a_no_op_when_nothing_changed(self):
        config = self.config_for(["eDP-1", "HDMI-1"], ["eDP-1"])
        store = mx.Store([config])
        self.assertFalse(store.replace(self.config_for(["eDP-1", "HDMI-1"], ["eDP-1"])))

    def test_a_different_monitor_set_is_a_second_entry(self):
        store = mx.Store([self.config_for(["eDP-1"], ["eDP-1"])])
        store.replace(self.config_for(["eDP-1", "HDMI-1"], ["HDMI-1"]))
        self.assertEqual(len(store.configurations), 2)

    def test_replace_carries_over_what_getcurrentstate_cannot_see(self):
        old = self.config_for(["eDP-1", "HDMI-1"], ["eDP-1"])
        old.logicals[0].presentation = True
        old.logicals[0].monitors[0].extras = ["<maxbpc>12</maxbpc>"]
        store = mx.Store([old])
        store.replace(self.config_for(["eDP-1", "HDMI-1"], ["eDP-1"], scale=2.0))
        kept = store.configurations[0].logicals[0]
        self.assertTrue(kept.presentation, "presentation flag survives a rewrite")
        self.assertEqual(kept.monitors[0].extras, ["<maxbpc>12</maxbpc>"])
        self.assertIn("<maxbpc>12</maxbpc>", mx.render(store))

    def test_forget_removes_only_the_matching_set(self):
        a = self.config_for(["eDP-1"], ["eDP-1"])
        b = self.config_for(["eDP-1", "HDMI-1"], ["HDMI-1"])
        store = mx.Store([a, b])
        self.assertTrue(store.forget(a.key()))
        self.assertEqual([c.key() for c in store.configurations], [b.key()])
        self.assertFalse(store.forget(a.key()))


class OnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "monitors.xml")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, enabled="eDP-1"):
        monitors = {"eDP-1": monitor("eDP-1"), "eDP-2": monitor("eDP-2")}
        return mx.snapshot(monitors, [logical(0, 0, 2.0, [enabled], primary=True)])

    def test_missing_file_reads_as_an_empty_store(self):
        self.assertEqual(mx.load(self.path).configurations, [])
        self.assertIsNone(mx.stored_for((), self.path))

    def test_remember_then_read_back(self):
        config = self.config()
        self.assertTrue(mx.remember(config, self.path))
        self.assertFalse(mx.remember(config, self.path), "second time changes nothing")
        stored = mx.stored_for(config.key(), self.path)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.shape(), config.shape())
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o644")

    def test_forget_rewrites_the_file(self):
        config = self.config()
        mx.remember(config, self.path)
        self.assertTrue(mx.forget(config.key(), self.path))
        self.assertEqual(mx.load(self.path).configurations, [])
        self.assertFalse(mx.forget(config.key(), self.path))

    def test_an_unknown_top_level_element_survives_a_rewrite(self):
        # <policy> decides whether Mutter accepts configurations over D-Bus at
        # all; dropping it while recording a layout would change GNOME's
        # behaviour behind the user's back.
        with open(self.path, "w") as f:
            f.write('<monitors version="2">\n'
                    '  <policy><stores><store>file</store></stores></policy>\n'
                    '</monitors>\n')
        mx.remember(self.config(), self.path)
        with open(self.path) as f:
            text = f.read()
        self.assertIn("<policy>", text)
        self.assertIn("<store>file</store>", text)
        self.assertEqual(len(mx.load(self.path).configurations), 1)

    def test_a_file_we_cannot_parse_is_left_alone(self):
        with open(self.path, "w") as f:
            f.write('<monitors version="1"><configuration/></monitors>')
        with self.assertRaises(mx.FormatError):
            mx.remember(self.config(), self.path)
        with open(self.path) as f:
            self.assertIn('version="1"', f.read(), "the file was not touched")

    def test_no_temporary_file_is_left_behind(self):
        mx.remember(self.config(), self.path)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["monitors.xml"])

    def test_path_honours_the_environment(self):
        old = os.environ.get("ZENDUO_MONITORS_XML")
        os.environ["ZENDUO_MONITORS_XML"] = self.path
        try:
            self.assertEqual(mx.path(), self.path)
        finally:
            if old is None:
                del os.environ["ZENDUO_MONITORS_XML"]
            else:
                os.environ["ZENDUO_MONITORS_XML"] = old


class Replay(unittest.TestCase):
    """to_apply_logicals: a stored layout handed back to ApplyMonitorsConfig."""

    def stored(self, mirrored=False, docked_bottom=True):
        monitors = {"eDP-1": monitor("eDP-1"), "eDP-2": monitor("eDP-2"),
                    "HDMI-1": monitor("HDMI-1", ACER, [mode(1920, 1080, 60.0)])}
        if mirrored:
            live = [(0, 0, 1.0, 0, True,
                     [("eDP-1",) + PANEL, ("HDMI-1",) + ACER], {})]
        else:
            live = [logical(0, 0, 2.0, ["eDP-1"], primary=True),
                    logical(0, 900, 2.0, ["eDP-2"]),
                    logical(1440, 0, 1.0, ["HDMI-1"], ident=ACER)]
        return mx.snapshot(monitors, live)

    def resolve(self, connector, mode_obj):
        return f"{connector}-mode"

    def test_replays_positions_scales_and_primary(self):
        logicals = mx.to_apply_logicals(self.stored(), self.resolve)
        self.assertEqual([(lm[0], lm[1], lm[2], lm[4], [m[0] for m in lm[5]])
                          for lm in logicals],
                         [(0, 0, 2.0, True, ["eDP-1"]),
                          (0, 900, 2.0, False, ["eDP-2"]),
                          (1440, 0, 1.0, False, ["HDMI-1"])])

    def test_mode_ids_come_from_the_resolver_not_from_the_stored_text(self):
        logicals = mx.to_apply_logicals(self.stored(), self.resolve)
        self.assertEqual(logicals[0][5][0][1], "eDP-1-mode")

    def test_dropping_a_monitor_from_a_mirror_keeps_the_rest_mirrored(self):
        logicals = mx.to_apply_logicals(self.stored(mirrored=True), self.resolve,
                                        drop={"eDP-1"})
        self.assertEqual(len(logicals), 1)
        self.assertEqual([m[0] for m in logicals[0][5]], ["HDMI-1"])

    def test_dropping_the_origin_monitor_translates_the_layout_back(self):
        # Mutter refuses a layout whose top-left corner is not the origin.
        logicals = mx.to_apply_logicals(self.stored(), self.resolve, drop={"eDP-1"})
        self.assertEqual(min(lm[0] for lm in logicals), 0)
        self.assertEqual(min(lm[1] for lm in logicals), 0)

    def test_dropping_the_primary_monitor_promotes_another(self):
        logicals = mx.to_apply_logicals(self.stored(), self.resolve, drop={"eDP-1"})
        self.assertEqual(sum(1 for lm in logicals if lm[4]), 1)

    def test_dropping_everything_yields_nothing_rather_than_a_bad_layout(self):
        self.assertEqual(mx.to_apply_logicals(
            self.stored(), self.resolve,
            drop={"eDP-1", "eDP-2", "HDMI-1"}), [])

    def test_as_logical_monitors_matches_getcurrentstate_shape(self):
        stored = self.stored()
        replayed = mx.as_logical_monitors(stored)
        self.assertEqual(mx.snapshot(
            {"eDP-1": monitor("eDP-1"), "eDP-2": monitor("eDP-2"),
             "HDMI-1": monitor("HDMI-1", ACER, [mode(1920, 1080, 60.0)])},
            replayed).shape(), stored.shape())


class LoginScreen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ours = os.path.join(self.tmp.name, "monitors.xml")
        self.theirs = os.path.join(self.tmp.name, "gdm-monitors.xml")
        self.saved = mx.gdm_monitors_path
        mx.gdm_monitors_path = lambda: self.theirs

    def tearDown(self):
        mx.gdm_monitors_path = self.saved
        self.tmp.cleanup()

    def test_states(self):
        with open(self.ours, "w") as f:
            f.write("x")
        self.assertEqual(mx.login_screen_state(self.ours), "not installed")
        with open(self.theirs, "w") as f:
            f.write("y")
        self.assertEqual(mx.login_screen_state(self.ours), "out of step")
        with open(self.theirs, "w") as f:
            f.write("x")
        self.assertEqual(mx.login_screen_state(self.ours), "in step")

    def test_no_display_manager_is_not_an_error(self):
        mx.gdm_monitors_path = lambda: None
        self.assertIsNone(mx.login_screen_state(self.ours))


if __name__ == "__main__":
    unittest.main()
