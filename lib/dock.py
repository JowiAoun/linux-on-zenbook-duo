#!/usr/bin/env python3
"""Keyboard dock state + the manual display-override marker.

Shared by `displayctl` (the CLI) and `watch_displays` (the daemon) so both
agree on two questions:

  * **Is the keyboard docked?** — only the pogo-pin USB link counts. Paired
    over Bluetooth the keyboard is physically OFF the bottom panel, which is
    exactly the state that should light that panel up.
  * **Did the user override the dock policy?** — every manual `duo
    top/bottom/both/toggle/only` records the dock state it was issued under.
    While that marker matches the current dock state, `watch-displays` stops
    enforcing the policy, so `duo bottom` (or the second-screen Fn key) is not
    undone a fraction of a second later. Docking or undocking retires the
    marker: the user's last explicit choice was made for the *other* state.

The marker lives in $XDG_RUNTIME_DIR, so it never survives a logout or reboot —
a fresh session always starts under the automatic policy.

Set ZENDUO_MANAGED=1 to suppress writing the marker (what the daemon does for
its own applies, and what a script should do when it is automating `duo`).
"""

import glob
import json
import os
import tempfile

KBD_VID = "0b05"
KBD_PID = "1b2c"


def keyboard_docked():
    """True when the keyboard is on the pogo pins (USB 0b05:1b2c)."""
    for vid_path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        pid_path = vid_path[: -len("idVendor")] + "idProduct"
        try:
            with open(vid_path) as f:
                if f.read().strip().lower() != KBD_VID:
                    continue
            with open(pid_path) as f:
                if f.read().strip().lower() == KBD_PID:
                    return True
        except OSError:
            continue  # device disappeared mid-scan (undock races the glob)
    return False


def _override_dir():
    # Fall back to a per-uid /tmp path for the TTY/live-USB case where the
    # session's runtime directory is not exported.
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(
        tempfile.gettempdir(), f"zenduo-{os.getuid()}")
    return os.path.join(base, "zenduo")


def override_path():
    return os.path.join(_override_dir(), "display-override.json")


def write_override(docked, want):
    """Record a deliberate layout choice made under dock state `docked`."""
    if os.environ.get("ZENDUO_MANAGED") == "1":
        return False
    path = override_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        # Write-then-rename: the daemon reads this file from another process
        # and must never see a half-written document.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".override.")
        with os.fdopen(fd, "w") as f:
            json.dump({"docked": bool(docked), "want": list(want)}, f)
        os.replace(tmp, path)
        return True
    except OSError:
        return False  # best effort: an unwritable runtime dir must not fail the apply


def read_override():
    """The recorded choice, or None when there is none / it is unreadable."""
    try:
        with open(override_path()) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "docked" not in doc:
        return None
    return doc


def clear_override():
    """Drop the marker. True if one was actually there."""
    try:
        os.unlink(override_path())
        return True
    except OSError:
        return False
