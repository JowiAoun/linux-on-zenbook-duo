"""Layout maths in lib/displayctl.py, without a Mutter to talk to.

These are the functions that decide what ApplyMonitorsConfig is handed. Every
case here was a real failure or a real rejection from Mutter at some point:
off-origin layouts, non-adjacent layouts, externals stranded when the panel
stack shrank, the top panel being forced on by "docked -> exactly [top]".
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import displayctl  # noqa: E402
import monitors_xml  # noqa: E402

TOP, BOTTOM = displayctl.TOP, displayctl.BOTTOM


def mon(connector, w=2880, h=1800, scale=2.0):
    return {
        "connector": connector, "vendor": "SDC", "product": "x", "serial": "0",
        "modes": [{"id": f"{w}x{h}@120", "width": w, "height": h, "refresh": 120.0,
                   "preferred_scale": scale, "is_current": True, "is_preferred": True}],
        "builtin": connector.startswith("eDP"),
    }


def logical(x, y, scale, connectors, primary=False, transform=0):
    return (x, y, scale, transform, primary, [(c, "SDC", "x", "0") for c in connectors], {})


PROPS = {"layout-mode": 1}


class Geometry(unittest.TestCase):
    def test_logical_size_scales_and_rotates(self):
        mode = {"width": 2880, "height": 1800}
        self.assertEqual(displayctl.logical_size(mode, 2.0, 1), (1440, 900))
        self.assertEqual(displayctl.logical_size(mode, 2.0, 2), (2880, 1800))
        self.assertEqual(displayctl.logical_size(mode, 2.0, 1, transform=1), (900, 1440))

    def test_touches_and_contiguous(self):
        a, b, c = (0, 0, 10, 10), (10, 0, 10, 10), (30, 0, 10, 10)
        self.assertTrue(displayctl.touches(a, b))
        self.assertFalse(displayctl.touches(a, c))
        self.assertTrue(displayctl.contiguous([a, b]))
        self.assertFalse(displayctl.contiguous([a, b, c]))
        self.assertTrue(displayctl.contiguous([a]))

    def test_order_connectors_puts_panels_first_top_above_bottom(self):
        self.assertEqual(displayctl.order_connectors(["HDMI-1", BOTTOM, TOP]), [TOP, BOTTOM, "HDMI-1"])


class BuildConfig(unittest.TestCase):
    def setUp(self):
        self.monitors = {TOP: mon(TOP), BOTTOM: mon(BOTTOM), "HDMI-1": mon("HDMI-1", 1920, 1080, 1.0)}

    def test_zero_panels_is_refused(self):
        with self.assertRaises(displayctl.DisplayCtlError) as ctx:
            displayctl.build_config(self.monitors, [], PROPS, [])
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_connector_is_a_usage_error(self):
        with self.assertRaises(displayctl.DisplayCtlError) as ctx:
            displayctl.build_config(self.monitors, [], PROPS, ["DP-9"])
        self.assertEqual(ctx.exception.code, 64)

    def test_both_panels_stack_top_above_bottom(self):
        current = [logical(0, 0, 2.0, [TOP], primary=True)]
        out = displayctl.build_config(self.monitors, current, PROPS, [TOP, BOTTOM])
        self.assertEqual([(lm[0], lm[1], lm[5][0][0]) for lm in out], [(0, 0, TOP), (0, 900, BOTTOM)])
        self.assertTrue(out[0][4], "the previous primary stays primary")
        self.assertFalse(out[1][4])

    def test_external_keeps_its_position_when_it_still_fits(self):
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(1440, 0, 1.0, ["HDMI-1"])]
        out = displayctl.build_config(self.monitors, current, PROPS, [TOP, "HDMI-1"])
        ext = next(lm for lm in out if lm[5][0][0] == "HDMI-1")
        self.assertEqual((ext[0], ext[1]), (1440, 0))

    def test_external_moved_below_when_it_would_collide_with_the_stack(self):
        # The external sat where the bottom panel now goes.
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(0, 900, 1.0, ["HDMI-1"])]
        out = displayctl.build_config(self.monitors, current, PROPS, [TOP, BOTTOM, "HDMI-1"])
        ext = next(lm for lm in out if lm[5][0][0] == "HDMI-1")
        self.assertEqual((ext[0], ext[1]), (0, 1800))

    def test_stranded_external_falls_back_to_a_vertical_stack(self):
        # Two panels stacked, external hanging off the BOTTOM panel's right
        # edge; then the bottom panel goes away -> the external no longer
        # touches anything at its old coordinates.
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(0, 900, 2.0, [BOTTOM]),
                   logical(1440, 900, 1.0, ["HDMI-1"])]
        out = displayctl.build_config(self.monitors, current, PROPS, [TOP, "HDMI-1"])
        rects = [(lm[0], lm[1]) for lm in out]
        self.assertEqual(rects, [(0, 0), (0, 900)])

    def test_layout_is_translated_back_to_the_origin(self):
        # External-only, with the external living at x=1440 from when a panel
        # sat to its left. Mutter rejects an off-origin layout.
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(1440, 0, 1.0, ["HDMI-1"])]
        out = displayctl.build_config(self.monitors, current, PROPS, ["HDMI-1"])
        self.assertEqual((out[0][0], out[0][1]), (0, 0))
        self.assertTrue(out[0][4], "the only monitor becomes primary")

    def test_primary_falls_back_when_the_old_primary_is_disabled(self):
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(0, 900, 2.0, [BOTTOM])]
        out = displayctl.build_config(self.monitors, current, PROPS, [BOTTOM])
        self.assertEqual(out[0][5][0][0], BOTTOM)
        self.assertTrue(out[0][4])

    def test_enabled_connectors_and_current_layout(self):
        current = [logical(0, 0, 2.0, [TOP], primary=True), logical(0, 900, 2.0, [BOTTOM])]
        self.assertEqual(displayctl.enabled_connectors(current), [TOP, BOTTOM])
        self.assertEqual(displayctl.current_layout(current)[BOTTOM]["y"], 900)

    def test_gi_is_only_required_when_talking_to_mutter(self):
        # The module must import without PyGObject (this test may run on a
        # python that has none); proxy() is what must then fail cleanly.
        if not displayctl.HAVE_GI:
            with self.assertRaises(displayctl.DisplayCtlError):
                displayctl.proxy()


def multi_mon(connector, sizes, vendor="SDC", product="x"):
    """A monitor with several modes, newest-style dicts (see parse_monitors)."""
    modes = []
    for i, (w, h, refresh) in enumerate(sizes):
        modes.append({"id": f"{w}x{h}@{refresh:.3f}", "width": w, "height": h,
                      "refresh": refresh, "preferred_scale": 1.0,
                      "is_current": i == 0, "is_preferred": i == 0,
                      "interlace": False, "variable": False})
    return {"connector": connector, "vendor": vendor, "product": product,
            "serial": "0", "modes": modes,
            "builtin": connector.startswith("eDP"), "underscanning": False}


class ModePreference(unittest.TestCase):
    """A remembered mode has to win, or a layout comes back at the wrong rate."""

    def setUp(self):
        self.mon = multi_mon("HDMI-1", [(1920, 1080, 60.0), (1920, 1080, 74.973),
                                        (1280, 720, 60.0)])

    def test_no_preference_takes_the_current_mode(self):
        self.assertEqual(displayctl.pick_mode(self.mon)["refresh"], 60.0)

    def test_a_remembered_mode_is_matched_within_mutters_tolerance(self):
        prefer = monitors_xml.Mode(1920, 1080, 74.9732)
        self.assertEqual(displayctl.pick_mode(self.mon, prefer)["refresh"], 74.973)

    def test_a_vanished_rate_falls_back_to_the_best_at_that_size(self):
        prefer = monitors_xml.Mode(1280, 720, 144.0)
        picked = displayctl.pick_mode(self.mon, prefer)
        self.assertEqual((picked["width"], picked["height"]), (1280, 720))

    def test_a_vanished_size_falls_back_to_the_current_mode(self):
        prefer = monitors_xml.Mode(3840, 2160, 60.0)
        self.assertEqual(displayctl.pick_mode(self.mon, prefer)["refresh"], 60.0)

    def test_build_config_threads_the_preference_through(self):
        monitors = {"HDMI-1": self.mon}
        logicals = displayctl.build_config(
            monitors, [], PROPS, ["HDMI-1"],
            prefer_modes={"HDMI-1": monitors_xml.Mode(1920, 1080, 74.973)})
        self.assertEqual(logicals[0][5][0][1], "1920x1080@74.973")

    def test_mode_resolver_returns_a_real_mode_id(self):
        resolve = displayctl.mode_resolver({"HDMI-1": self.mon})
        self.assertEqual(resolve("HDMI-1", monitors_xml.Mode(1920, 1080, 74.973)),
                         "1920x1080@74.973")


class LayoutModes(unittest.TestCase):
    """The four Win+P layouts, named and detected the way Windows does."""

    def setUp(self):
        self.monitors = {TOP: mon(TOP), BOTTOM: mon(BOTTOM),
                         "HDMI-1": mon("HDMI-1", 1920, 1080, 1.0)}

    def test_docked_excludes_the_covered_panel_from_the_laptops_screens(self):
        self.assertEqual(displayctl.layout_sets(self.monitors, docked=True),
                         ([TOP], ["HDMI-1"]))
        self.assertEqual(displayctl.layout_sets(self.monitors, docked=False),
                         ([TOP, BOTTOM], ["HDMI-1"]))

    def test_detects_each_layout(self):
        cases = {
            "laptop": [TOP, BOTTOM],
            "external": ["HDMI-1"],
            "extend": [TOP, BOTTOM, "HDMI-1"],
        }
        for name, enabled in cases.items():
            live = [logical(0, i * 900, 2.0, [c]) for i, c in enumerate(enabled)]
            self.assertEqual(
                displayctl.detect_layout(self.monitors, live, enabled, docked=False),
                name, name)

    def test_a_clone_is_detected_as_mirror(self):
        live = [logical(0, 0, 1.0, [TOP, "HDMI-1"])]
        self.assertEqual(displayctl.detect_layout(
            self.monitors, live, [TOP, "HDMI-1"], docked=False), "mirror")

    def test_anything_else_is_custom(self):
        live = [logical(0, 0, 2.0, [BOTTOM])]
        self.assertIsNone(displayctl.detect_layout(
            self.monitors, live, [BOTTOM], docked=False))

    def test_laptop_while_docked_is_the_top_panel_alone(self):
        live = [logical(0, 0, 2.0, [TOP])]
        self.assertEqual(displayctl.detect_layout(
            self.monitors, live, [TOP], docked=True), "laptop")

    def test_the_cycle_follows_windows_order_and_wraps(self):
        self.assertEqual(displayctl.next_layout("laptop", True), "mirror")
        self.assertEqual(displayctl.next_layout("mirror", True), "extend")
        self.assertEqual(displayctl.next_layout("extend", True), "external")
        self.assertEqual(displayctl.next_layout("external", True), "laptop")

    def test_a_custom_layout_starts_the_cycle_over(self):
        self.assertEqual(displayctl.next_layout(None, True), "laptop")

    def test_nothing_to_cycle_without_an_external_monitor(self):
        self.assertIsNone(displayctl.next_layout("laptop", False))


class LayoutDispatch(unittest.TestCase):
    """A dry run must reach the handler as a dry run.

    run() used to strip --dry-run before dispatching, so the layout verbs
    never saw it and `duo layout laptop --dry-run` applied the layout for
    real. Nothing else in this file can catch that, because it is plumbing.
    """

    def dispatch(self, argv):
        seen = []
        saved = displayctl.cmd_layout
        displayctl.cmd_layout = lambda args: (seen.append(list(args)), 0)[1]
        try:
            self.assertEqual(displayctl.run(argv), 0)
        finally:
            displayctl.cmd_layout = saved
        return seen

    def test_the_verb_and_its_flags_arrive_intact(self):
        self.assertEqual(self.dispatch(["layout", "laptop", "--dry-run"]),
                         [["laptop", "--dry-run"]])

    def test_no_verb_is_still_dispatched(self):
        self.assertEqual(self.dispatch(["layout"]), [[]])

    def test_an_unknown_verb_is_a_usage_error_not_an_apply(self):
        with self.assertRaises(displayctl.DisplayCtlError) as caught:
            displayctl.cmd_layout(["sideways"])
        self.assertEqual(caught.exception.code, 64)

    def test_an_unknown_flag_is_a_usage_error(self):
        with self.assertRaises(displayctl.DisplayCtlError) as caught:
            displayctl.cmd_layout(["laptop", "--force"])
        self.assertEqual(caught.exception.code, 64)


class Mirror(unittest.TestCase):
    def test_picks_the_largest_resolution_every_monitor_has(self):
        monitors = {
            TOP: multi_mon(TOP, [(2880, 1800, 120.0), (1920, 1080, 60.0),
                                 (1280, 720, 60.0)]),
            "HDMI-1": multi_mon("HDMI-1", [(1920, 1080, 60.0), (1920, 1080, 74.973),
                                           (1280, 720, 60.0)], "ACR", "KA272"),
        }
        logicals = displayctl.build_mirror_config(monitors, [TOP, "HDMI-1"])
        self.assertEqual(len(logicals), 1, "one logical monitor drives both")
        x, y, scale, transform, primary, mons = logicals[0]
        self.assertEqual((x, y, scale, transform, primary), (0, 0, 1.0, 0, True))
        self.assertEqual([m[0] for m in mons], [TOP, "HDMI-1"])
        self.assertTrue(all("1920x1080" in m[1] for m in mons))

    def test_takes_the_highest_rate_at_that_resolution(self):
        monitors = {
            TOP: multi_mon(TOP, [(1920, 1080, 60.0), (1920, 1080, 120.0)]),
            "HDMI-1": multi_mon("HDMI-1", [(1920, 1080, 60.0)], "ACR", "KA272"),
        }
        logicals = displayctl.build_mirror_config(monitors, [TOP, "HDMI-1"])
        self.assertEqual(logicals[0][5][0][1], "1920x1080@120.000")

    def test_refused_when_no_resolution_is_shared(self):
        monitors = {TOP: multi_mon(TOP, [(2880, 1800, 120.0)]),
                    "HDMI-1": multi_mon("HDMI-1", [(1920, 1080, 60.0)], "ACR", "K")}
        with self.assertRaises(displayctl.DisplayCtlError) as caught:
            displayctl.build_mirror_config(monitors, [TOP, "HDMI-1"])
        self.assertEqual(caught.exception.code, 2)

    def test_refused_with_a_single_monitor(self):
        with self.assertRaises(displayctl.DisplayCtlError):
            displayctl.build_mirror_config({TOP: mon(TOP)}, [TOP])


class FromStored(unittest.TestCase):
    """Replaying a remembered layout, which is what a lid-open comes back to."""

    def setUp(self):
        self.monitors = {
            TOP: multi_mon(TOP, [(2880, 1800, 120.0), (1920, 1080, 60.0)]),
            BOTTOM: multi_mon(BOTTOM, [(2880, 1800, 120.0), (1920, 1080, 60.0)]),
            "HDMI-1": multi_mon("HDMI-1", [(1920, 1080, 60.0), (1920, 1080, 74.973)],
                                "ACR", "KA272"),
        }

    def stored(self, live):
        return monitors_xml.snapshot(self.monitors, live)

    def test_external_only_comes_back_with_its_own_mode_and_primary(self):
        live = [logical(0, 0, 1.0, ["HDMI-1"], primary=True)]
        stored = self.stored(live)
        logicals = displayctl.build_from_stored(stored, self.monitors, PROPS)
        self.assertEqual([m[0] for lm in logicals for m in lm[5]], ["HDMI-1"])
        self.assertTrue(logicals[0][4], "it stays the primary monitor")
        self.assertEqual(displayctl.logicals_shape(logicals), stored.shape())

    def test_a_remembered_scale_and_position_survive(self):
        live = [logical(0, 0, 2.0, [TOP], primary=True),
                logical(0, 900, 2.0, [BOTTOM]),
                logical(1440, 0, 1.0, ["HDMI-1"])]
        stored = self.stored(live)
        logicals = displayctl.build_from_stored(stored, self.monitors, PROPS)
        self.assertEqual(displayctl.logicals_shape(logicals), stored.shape())

    def test_the_dock_policy_drops_the_covered_panel_before_it_is_applied(self):
        # The remembered layout has both panels; docked, the bottom one must
        # never be handed over — not even for the frame it would take to
        # correct it afterwards.
        live = [logical(0, 0, 2.0, [TOP], primary=True), logical(0, 900, 2.0, [BOTTOM])]
        stored = self.stored(live)
        logicals = displayctl.build_from_stored(stored, self.monitors, PROPS,
                                                drop={BOTTOM})
        self.assertEqual([m[0] for lm in logicals for m in lm[5]], [TOP])

    def test_dropping_a_panel_leaves_the_layout_at_the_origin(self):
        live = [logical(0, 0, 2.0, [TOP], primary=True),
                logical(0, 900, 2.0, [BOTTOM]),
                logical(0, 1800, 1.0, ["HDMI-1"])]
        logicals = displayctl.build_from_stored(self.stored(live), self.monitors,
                                                PROPS, drop={TOP})
        self.assertEqual(min(lm[0] for lm in logicals), 0)
        self.assertEqual(min(lm[1] for lm in logicals), 0)

    def test_a_mirror_is_replayed_as_a_mirror(self):
        live = [(0, 0, 1.0, 0, True,
                 [(TOP, "SDC", "x", "0"), ("HDMI-1", "ACR", "KA272", "0")], {})]
        logicals = displayctl.build_from_stored(self.stored(live), self.monitors, PROPS)
        self.assertEqual(len(logicals), 1)
        self.assertEqual(sorted(m[0] for m in logicals[0][5]), sorted([TOP, "HDMI-1"]))

    def test_a_monitor_that_is_gone_is_simply_not_enabled(self):
        live = [logical(0, 0, 1.0, ["HDMI-1"], primary=True),
                logical(1920, 0, 2.0, [TOP])]
        stored = self.stored(live)
        del self.monitors["HDMI-1"]
        logicals = displayctl.build_from_stored(stored, self.monitors, PROPS)
        self.assertEqual([m[0] for lm in logicals for m in lm[5]], [TOP])

    def test_refused_when_nothing_it_enables_is_connected(self):
        live = [logical(0, 0, 1.0, ["HDMI-1"], primary=True)]
        stored = self.stored(live)
        del self.monitors["HDMI-1"]
        with self.assertRaises(displayctl.DisplayCtlError) as caught:
            displayctl.build_from_stored(stored, self.monitors, PROPS)
        self.assertEqual(caught.exception.code, 2)

    def test_shape_ignores_the_mode_but_not_the_geometry(self):
        live = [logical(0, 0, 1.0, ["HDMI-1"], primary=True)]
        stored = self.stored(live)
        moved = [logical(0, 100, 1.0, ["HDMI-1"], primary=True)]
        self.assertNotEqual(self.stored(moved).shape(), stored.shape())


if __name__ == "__main__":
    unittest.main()
