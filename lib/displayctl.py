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

Every layout-changing command records a manual override (see dock.py) so the
watch-displays daemon stops enforcing the dock policy until the keyboard is
docked or undocked. Set ZENDUO_MANAGED=1 to suppress that — the daemon does,
for its own applies.

Also importable: watch_displays drives the helpers below in-process, so
failures raise DisplayCtlError (carrying the exit code) instead of exiting.

Exit codes: 0 ok · 1 D-Bus/environment failure · 2 refused by invariant ·
64 usage error.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dock  # noqa: E402  (same directory; shares dock state + override marker)

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


class DisplayCtlError(Exception):
    """A failure that carries the exit code the CLI should report.

    The daemon catches these and retries; running as a script, main() turns
    them back into the documented exit codes.
    """

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def proxy():
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
            BUS_NAME, OBJ_PATH, BUS_NAME, None)
    except GLib.Error as e:
        raise DisplayCtlError(f"cannot reach Mutter on the session bus: {e.message}", 1)


def get_state(p):
    """Return (serial, monitors, logical_monitors, properties).

    GetCurrentState signature:
      monitors:         a((ssss)a(siiddada{sv})a{sv})
      logical_monitors: a(iiduba(ssss)a{sv})
    """
    try:
        return p.call_sync("GetCurrentState", None, Gio.DBusCallFlags.NONE, -1, None).unpack()
    except GLib.Error as e:
        raise DisplayCtlError(f"GetCurrentState failed: {e.message}", 1)


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


def logical_size(mode, scale, layout_mode, transform=0):
    """Size a logical monitor occupies, honoring Mutter's layout mode
    (1 = logical/scaled coordinates, 2 = physical pixels).

    Odd transforms (1/3/5/7 = 90°/270° and their flipped variants) rotate the
    panel, so Mutter derives the logical size with width and height swapped —
    ignoring that produced overlapping layouts that ApplyMonitorsConfig rejects.
    """
    w, h = mode["width"], mode["height"]
    if transform % 2:
        w, h = h, w
    if layout_mode == 2:
        return w, h
    return round(w / scale), round(h / scale)


def overlaps(a, b):
    """True if two (x, y, w, h) rectangles intersect."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def touches(a, b):
    """True if two rectangles share a border of non-zero length, or overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if overlaps(a, b):
        return True
    if (ax + aw == bx or bx + bw == ax) and min(ay + ah, by + bh) > max(ay, by):
        return True
    if (ay + ah == by or by + bh == ay) and min(ax + aw, bx + bw) > max(ax, bx):
        return True
    return False


def contiguous(rects):
    """True if every rectangle is reachable from the first by shared borders.

    Mutter rejects a layout whose logical monitors are not all adjacent
    ("Logical monitors not adjacent"), which is easy to produce by accident:
    keep an external monitor at the coordinates it had while two panels were
    stacked above it, then disable one of those panels, and the gap left
    behind strands it.
    """
    if len(rects) < 2:
        return True
    seen = {0}
    queue = [0]
    while queue:
        i = queue.pop()
        for j in range(len(rects)):
            if j not in seen and touches(rects[i], rects[j]):
                seen.add(j)
                queue.append(j)
    return len(seen) == len(rects)


def order_connectors(want, internal=(TOP, BOTTOM)):
    """Internal panels first, top above bottom, externals after.

    build_config stacks internal panels in the order it is handed them, and
    Mutter reports enabled connectors in no particular order, so any list
    assembled from live state has to be put back into physical order first.
    """
    return ([c for c in internal if c in want]
            + [c for c in want if c not in internal])


def build_config(monitors, logical_monitors, properties, want, internal=(TOP, BOTTOM)):
    """Build the ApplyMonitorsConfig logical-monitor list enabling exactly
    the connectors in `want`.

    Internal panels are stacked top-to-bottom at x=0. External monitors keep
    the position they already had (so a desk arrangement survives every
    dock/undock), unless that position would collide with the new internal
    stack — then they are appended below it.

    Two rules Mutter enforces on the result, both of which it rejects outright:
    the layout must start at the origin, and every monitor must be adjacent to
    another. Preserved external coordinates can violate the second one whenever
    the internal stack shrinks, so a layout that comes out disconnected is
    rebuilt as a plain vertical stack rather than handed over to be refused.
    """
    if not want:
        raise DisplayCtlError("REFUSED — zero enabled panels is never allowed (R10)", 2)
    missing = [c for c in want if c not in monitors]
    if missing:
        raise DisplayCtlError(f"unknown connector(s): {', '.join(missing)} "
                              f"(have: {', '.join(monitors)})", 64)

    layout_mode = int(properties.get("layout-mode", 1))
    layout = current_layout(logical_monitors)

    # Keep the user's primary monitor primary as long as it stays enabled;
    # only fall back to the first panel when the old primary is being disabled.
    prev_primary = next((c for c in want
                         if layout.get(c) and layout[c]["primary"]), None)
    primary_connector = prev_primary or want[0]

    placed = []      # (x, y, w, h) rectangles already committed
    logicals = []
    y = 0
    for connector in [c for c in want if c in internal]:
        mon = monitors[connector]
        mode = pick_mode(mon)
        prev = layout.get(connector)
        scale = prev["scale"] if prev else mode["preferred_scale"]
        transform = prev["transform"] if prev else 0
        w, h = logical_size(mode, scale, layout_mode, transform)
        logicals.append((0, y, scale, transform, connector == primary_connector,
                         [(connector, mode["id"], {})]))
        placed.append((0, y, w, h))
        y += h

    for connector in [c for c in want if c not in internal]:
        mon = monitors[connector]
        mode = pick_mode(mon)
        prev = layout.get(connector)
        scale = prev["scale"] if prev else mode["preferred_scale"]
        transform = prev["transform"] if prev else 0
        w, h = logical_size(mode, scale, layout_mode, transform)
        x = prev["x"] if prev else 0
        ext_y = prev["y"] if prev else y
        if any(overlaps((x, ext_y, w, h), r) for r in placed):
            x, ext_y = 0, y  # its old spot now collides with the panel stack
            y += h
        logicals.append((x, ext_y, scale, transform, connector == primary_connector,
                         [(connector, mode["id"], {})]))
        placed.append((x, ext_y, w, h))

    if not contiguous(placed):
        # A preserved external position left a hole. Relative placement cannot
        # be salvaged in general, so fall back to the one arrangement that is
        # always valid: everything stacked at x=0, in `want` order.
        logicals = []
        y = 0
        for connector in ([c for c in want if c in internal]
                          + [c for c in want if c not in internal]):
            mon = monitors[connector]
            mode = pick_mode(mon)
            prev = layout.get(connector)
            scale = prev["scale"] if prev else mode["preferred_scale"]
            transform = prev["transform"] if prev else 0
            _w, h = logical_size(mode, scale, layout_mode, transform)
            logicals.append((0, y, scale, transform, connector == primary_connector,
                             [(connector, mode["id"], {})]))
            y += h

    # Mutter refuses any layout whose top-left corner is not the origin
    # ("Logical monitors positions are offset"). Externals keep the coordinates
    # they already had, so disabling whatever sat at 0,0 — turning the panels
    # off and leaving an external that lives at x=1920 — would strand the whole
    # layout off-origin. Translate it back as a block, which preserves every
    # monitor's position *relative* to the others.
    min_x = min(lm[0] for lm in logicals)
    min_y = min(lm[1] for lm in logicals)
    if min_x or min_y:
        logicals = [(lx - min_x, ly - min_y, scale, transform, primary, mons)
                    for (lx, ly, scale, transform, primary, mons) in logicals]
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
        raise DisplayCtlError(f"ApplyMonitorsConfig failed: {e.message}", 1)


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


def run(argv):
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
        # Toggles the BOTTOM panel and nothing else — whatever is already on
        # stays on. Asserting [TOP, BOTTOM] here meant the second-screen Fn key
        # also switched the laptop display on, which is wrong when the user is
        # running external-only.
        want = [c for c in enabled if c != BOTTOM]
        if BOTTOM not in enabled:
            want.append(BOTTOM)
        elif not want:
            want = [TOP]  # R10: toggling off the only enabled panel would blank it
    elif cmd == "only":
        want = args
    else:
        print(__doc__, file=sys.stderr)
        return 64

    # External monitors are left alone: keep any currently-enabled connector
    # that is not one of the two internal panels. NOT for `only`, whose
    # documented contract is "enable exactly these connectors" — re-adding
    # externals there meant no command could ever turn an external off.
    if cmd != "only":
        external = [c for c in enabled if c not in (TOP, BOTTOM) and c not in want]
        want = want + external

    want = order_connectors(want)
    logicals = build_config(monitors, logical_raw, properties, want)
    apply_config(p, serial, logicals, dry_run=dry_run)
    if not dry_run:
        # A hand-issued layout outranks the dock policy until the keyboard is
        # docked or undocked — otherwise `duo bottom` (or the second-screen Fn
        # key) while docked would be reverted by watch-displays within a frame.
        dock.write_override(dock.keyboard_docked(), want)
        print(f"displayctl: enabled {', '.join(want)}")
    return 0


def main(argv):
    try:
        return run(argv)
    except DisplayCtlError as e:
        print(f"displayctl: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
