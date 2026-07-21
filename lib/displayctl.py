#!/usr/bin/env python3
"""Mutter DisplayConfig client for the ASUS Zenbook Duo (zenduo).

Talks to org.gnome.Mutter.DisplayConfig over the session D-Bus — the same
API GNOME Settings uses — instead of the unpackaged gnome-monitor-config
tool or xrandr (useless on Wayland).

Commands:
    state [--json]     print connectors, modes, and the current layout
    top                enable the top panel (eDP-1) only
    bottom             enable the bottom panel (eDP-2) only
    both               enable both panels, bottom stacked below top
    toggle             bottom panel on <-> off
    only C1 [C2 ...]   enable exactly these connectors

Safety invariant (PLAN.md R10): any configuration that would leave ZERO
enabled panels is refused with exit code 2.

Applies with Mutter's "temporary" method by default, so a broken layout
never persists across a session restart; set ZENDUO_APPLY_METHOD=persistent
to write monitors.xml instead.

Exit codes: 0 ok · 1 D-Bus/environment failure · 2 refused by invariant ·
64 usage error.
"""

import json
import os
import sys

try:
    import gi  # noqa: F401  (python3-gi, installed by system/40-duo-deps.sh)
    from gi.repository import Gio, GLib
except ImportError:
    print("displayctl: python3-gi missing (run: sudo make system HOST=zenbook-duo)", file=sys.stderr)
    sys.exit(1)

TOP = "eDP-1"
BOTTOM = "eDP-2"

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJ_PATH = "/org/gnome/Mutter/DisplayConfig"

METHOD_VERIFY = 0
METHOD_TEMPORARY = 1
METHOD_PERSISTENT = 2


def proxy():
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
            BUS_NAME, OBJ_PATH, BUS_NAME, None)
    except GLib.Error as e:
        print(f"displayctl: cannot reach Mutter on the session bus: {e.message}", file=sys.stderr)
        sys.exit(1)


def get_state(p):
    """Return (serial, monitors, logical_monitors, properties).

    GetCurrentState signature:
      monitors:         a((ssss)a(siiddada{sv})a{sv})
      logical_monitors: a(iiduba(ssss)a{sv})
    """
    try:
        return p.call_sync("GetCurrentState", None, Gio.DBusCallFlags.NONE, -1, None).unpack()
    except GLib.Error as e:
        print(f"displayctl: GetCurrentState failed: {e.message}", file=sys.stderr)
        sys.exit(1)


def parse_monitors(monitors):
    """Flatten Mutter's monitor structs into dicts keyed by connector."""
    out = {}
    for (spec, modes, props) in monitors:
        connector, vendor, product, serial = spec
        parsed_modes = []
        for (mode_id, width, height, refresh, pref_scale, scales, mprops) in modes:
            parsed_modes.append({
                "id": mode_id, "width": width, "height": height,
                "refresh": refresh, "preferred_scale": pref_scale,
                "is_current": bool(mprops.get("is-current", False)),
                "is_preferred": bool(mprops.get("is-preferred", False)),
            })
        out[connector] = {
            "connector": connector, "vendor": vendor,
            "product": product, "serial": serial,
            "modes": parsed_modes,
            "builtin": bool(props.get("is-builtin", False)),
        }
    return out


def enabled_connectors(logical_monitors):
    found = []
    for (_x, _y, _scale, _transform, _primary, assigned, _props) in logical_monitors:
        for (connector, _v, _p, _s) in assigned:
            found.append(connector)
    return found


def current_layout(logical_monitors):
    """connector -> {x, y, scale, transform, primary} for enabled monitors."""
    layout = {}
    for (x, y, scale, transform, primary, assigned, _props) in logical_monitors:
        for (connector, _v, _p, _s) in assigned:
            layout[connector] = {"x": x, "y": y, "scale": scale,
                                 "transform": transform, "primary": primary}
    return layout


def pick_mode(mon):
    for m in mon["modes"]:
        if m["is_current"]:
            return m
    for m in mon["modes"]:
        if m["is_preferred"]:
            return m
    return mon["modes"][0]


def logical_size(mode, scale, layout_mode):
    """Size a logical monitor occupies, honoring Mutter's layout mode
    (1 = logical/scaled coordinates, 2 = physical pixels)."""
    if layout_mode == 2:
        return mode["width"], mode["height"]
    return round(mode["width"] / scale), round(mode["height"] / scale)


def build_config(monitors, logical_monitors, properties, want):
    """Build the ApplyMonitorsConfig logical-monitor list enabling exactly
    the connectors in `want` (ordered top-to-bottom stacking)."""
    if not want:
        print("displayctl: REFUSED — zero enabled panels is never allowed (R10)", file=sys.stderr)
        sys.exit(2)
    missing = [c for c in want if c not in monitors]
    if missing:
        print(f"displayctl: unknown connector(s): {', '.join(missing)} "
              f"(have: {', '.join(monitors)})", file=sys.stderr)
        sys.exit(64)

    layout_mode = int(properties.get("layout-mode", 1))
    layout = current_layout(logical_monitors)

    logicals = []
    y = 0
    primary_assigned = False
    for connector in want:
        mon = monitors[connector]
        mode = pick_mode(mon)
        prev = layout.get(connector)
        scale = prev["scale"] if prev else mode["preferred_scale"]
        transform = prev["transform"] if prev else 0
        primary = not primary_assigned
        primary_assigned = True
        _w, h = logical_size(mode, scale, layout_mode)
        logicals.append((0, y, scale, transform, primary,
                         [(connector, mode["id"], {})]))
        y += h
    return logicals


def apply_config(p, serial, logicals, dry_run=False):
    method = METHOD_TEMPORARY
    if os.environ.get("ZENDUO_APPLY_METHOD") == "persistent":
        method = METHOD_PERSISTENT
    if dry_run:
        print(f"displayctl: DRY RUN (method={method}):")
        for lm in logicals:
            print(f"  pos=({lm[0]},{lm[1]}) scale={lm[2]} transform={lm[3]} "
                  f"primary={lm[4]} monitors={[m[0] for m in lm[5]]}")
        return
    variant = GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})",
        (serial, method,
         [(x, y, scale, transform, primary,
           [(c, mode_id, props) for (c, mode_id, props) in mons])
          for (x, y, scale, transform, primary, mons) in logicals],
         {}))
    try:
        p.call_sync("ApplyMonitorsConfig", variant, Gio.DBusCallFlags.NONE, -1, None)
    except GLib.Error as e:
        print(f"displayctl: ApplyMonitorsConfig failed: {e.message}", file=sys.stderr)
        sys.exit(1)


def cmd_state(as_json):
    p = proxy()
    serial, monitors_raw, logical_raw, properties = get_state(p)
    monitors = parse_monitors(monitors_raw)
    enabled = enabled_connectors(logical_raw)
    if as_json:
        print(json.dumps({
            "serial": serial,
            "enabled": enabled,
            "layout_mode": int(properties.get("layout-mode", 1)),
            "monitors": monitors,
            "layout": current_layout(logical_raw),
        }, indent=2))
        return
    for connector, mon in monitors.items():
        mode = pick_mode(mon)
        state = "ENABLED" if connector in enabled else "disabled"
        print(f"{connector:8s} {state:8s} {mode['width']}x{mode['height']}@{mode['refresh']:.0f} "
              f"vendor={mon['vendor']} product={mon['product']}")


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 64
    cmd, args = argv[0], argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if cmd == "state":
        cmd_state(as_json="--json" in args)
        return 0

    p = proxy()
    serial, monitors_raw, logical_raw, properties = get_state(p)
    monitors = parse_monitors(monitors_raw)
    enabled = enabled_connectors(logical_raw)

    if cmd == "top":
        want = [TOP]
    elif cmd == "bottom":
        want = [BOTTOM]
    elif cmd == "both":
        want = [TOP, BOTTOM]
    elif cmd == "toggle":
        want = [TOP] if BOTTOM in enabled else [TOP, BOTTOM]
    elif cmd == "only":
        want = args
    else:
        print(__doc__, file=sys.stderr)
        return 64

    # External monitors are left alone: keep any currently-enabled connector
    # that is not one of the two internal panels.
    external = [c for c in enabled if c not in (TOP, BOTTOM) and c not in want]
    want = want + external

    logicals = build_config(monitors, logical_raw, properties, want)
    apply_config(p, serial, logicals, dry_run=dry_run)
    if not dry_run:
        print(f"displayctl: enabled {', '.join(want)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
