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


if __name__ == "__main__":
    unittest.main()
