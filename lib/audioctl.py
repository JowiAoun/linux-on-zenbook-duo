#!/usr/bin/env python3
"""duo audio: what plays where, and which profile a Bluetooth headset is on.

    audio [status]              the default output, each Bluetooth device with
                                its profile, and PipeWire's realtime state
    audio stereo [DEVICE]       put the headset on its best A2DP profile:
                                stereo, 48 kHz; calls use the laptop's mic
    audio headset [DEVICE]      put it on its headset profile: its own mic,
                                and mono 16 kHz for everything that plays
    audio profiles [DEVICE]     every profile the device offers, the one in use marked
    audio profile NAME [DEVICE] any of those, by name or by index

DEVICE is part of the device's name; case does not matter. With one Bluetooth
audio device connected it can be left out. The choice sticks across reconnects,
the way a choice in Settings > Sound does, because WirePlumber saves it.

Why two verbs: WirePlumber's stock policy moved a headset to its headset
profile whenever a voice app captured, for every application's sound, and the
shipped policy (config/wireplumber/) turns that off. From then on the profile
is yours to pick: stereo for listening, headset for the times the earbuds'
own microphone is wanted. The switch itself is `wpctl set-profile`; this
command picks the profile by what it is for, and reads the device back
afterwards, because a switch that "succeeded" proves nothing until the
device reports the new profile.

Exit: 0 done · 1 the device did not take the profile · 2 no such device or
profile · 64 usage.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_probe  # noqa: E402

TIMEOUT = 6.0        # a Bluetooth profile switch takes a second or two
POLL = 0.5
POLICY_FILES = ("wireplumber/policy.lua.d/11-zenduo-bluetooth-stereo.lua",
                "wireplumber/wireplumber.conf.d/zenduo-bluetooth-stereo.conf")


class Problem(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def log(msg):
    print(f"audio: {msg}", file=sys.stderr, flush=True)


# ── reading ──────────────────────────────────────────────────────────────────

def bluetooth_devices(objs):
    """[{id, name, description, active, profiles}] for each bluez5 device.
    `active` is the Profile param (a dict or None); `profiles` the EnumProfile
    list, each with index, name, description, priority and available."""
    out = []
    for o in objs:
        if not isinstance(o, dict) or not str(o.get("type", "")).endswith("Interface:Device"):
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("device.api") != "bluez5":
            continue
        params = info.get("params") or {}
        active = next(iter(params.get("Profile") or []), None)
        out.append({
            "id": o.get("id"),
            "name": str(props.get("device.name", "")),
            "description": str(props.get("device.description") or props.get("device.name", "")),
            "active": active if isinstance(active, dict) else None,
            "profiles": [p for p in (params.get("EnumProfile") or []) if isinstance(p, dict)],
        })
    return out


def default_sink(objs):
    """(node name, description) of the default output, or ('', '')."""
    name = ""
    for o in objs:
        if not isinstance(o, dict) or not str(o.get("type", "")).endswith("Interface:Metadata"):
            continue
        if (o.get("props") or {}).get("metadata.name") != "default":
            continue
        for m in o.get("metadata") or []:
            if m.get("key") == "default.audio.sink":
                value = m.get("value")
                name = str(value.get("name", "")) if isinstance(value, dict) else str(value or "")
    if not name:
        return "", ""
    for o in objs:
        if isinstance(o, dict) and str(o.get("type", "")).endswith("Interface:Node"):
            props = (o.get("info") or {}).get("props") or {}
            if props.get("node.name") == name:
                return name, str(props.get("node.description") or props.get("node.nick") or name)
    return name, name


def pick_device(devs, hint=""):
    """The one device meant: by a case-insensitive part of its name, or the
    only one there is."""
    if hint:
        h = hint.lower()
        found = [d for d in devs if h in d["description"].lower() or h in d["name"].lower()]
        if not found:
            raise Problem(f"no Bluetooth audio device matches {hint!r}"
                          + (": " + ", ".join(d["description"] for d in devs) if devs else ""))
        if len(found) > 1:
            raise Problem(f"{hint!r} matches more than one device: " + ", ".join(d["description"] for d in found))
        return found[0]
    if not devs:
        raise Problem("no Bluetooth audio device is connected")
    if len(devs) > 1:
        raise Problem("more than one Bluetooth audio device; name one: " + ", ".join(d["description"] for d in devs))
    return devs[0]


def is_stereo(name):
    return name.startswith(("a2dp-sink", "bap-sink"))


def is_headset(name):
    return name.startswith("headset-head-unit")


def best_profile(dev, kind):
    """The highest-priority profile of that kind the device says it can do."""
    want = is_stereo if kind == "stereo" else is_headset
    usable = [p for p in dev["profiles"] if want(str(p.get("name", ""))) and p.get("available") != "no"]
    if not usable:
        return None
    return max(usable, key=lambda p: (p.get("priority", 0), p.get("index", 0)))


def profile_by(dev, key):
    """A profile by exact name or by index; None when there is no such one."""
    for p in dev["profiles"]:
        if str(p.get("name")) == key or (key.isdigit() and p.get("index") == int(key)):
            return p
    return None


def policy_installed(config_home=None):
    home = config_home or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return any(os.path.exists(os.path.join(home, f)) for f in POLICY_FILES)


# ── switching ────────────────────────────────────────────────────────────────

def set_profile(dev_id, index):
    """'' on success, else what wpctl said."""
    rc, out = audio_probe.run(["wpctl", "set-profile", str(dev_id), str(index)])
    return "" if rc == 0 else (out.strip().splitlines() or ["wpctl set-profile failed"])[-1]


def switch(dev, prof, setter=set_profile, reader=None, sleep=time.sleep, timeout=TIMEOUT):
    """Ask for the profile and wait until the device reports it. Returns the
    profile the device ended on; raises Problem when it never got there."""
    reader = reader or (lambda: bluetooth_devices(audio_probe.read_pw_dump()))
    label = f"{prof.get('name')} ({prof.get('description')})"
    cur = dev["active"] or {}
    if cur.get("index") == prof.get("index"):
        log(f"{dev['description']} is already on {label}")
        return cur
    log(f"{dev['description']}: {cur.get('name', 'off')} -> {label}")
    err = setter(dev["id"], prof.get("index"))
    if err:
        raise Problem(f"wpctl refused: {err}", 1)
    deadline = time.monotonic() + timeout
    while True:
        sleep(POLL)
        now = next((d for d in reader() if d["name"] == dev["name"]), None)
        active = (now or {}).get("active") or {}
        if active.get("index") == prof.get("index"):
            return active
        if time.monotonic() >= deadline:
            break
    why = f"asked for {prof.get('name')}, {dev['description']} is still on {active.get('name') or 'nothing'} after {timeout:g}s"
    if not policy_installed():
        why += ("; WirePlumber's headset switch is still on (no policy file), so a voice app that is"
                " capturing puts the headset profile back: ./install.sh --user turns it off")
    raise Problem(why, 1)


# ── the command line ─────────────────────────────────────────────────────────

def cmd_status(objs):
    name, desc = default_sink(objs)
    print(f"default output : {desc or 'none'}" + (f"  ({name})" if name and name != desc else ""))
    devs = bluetooth_devices(objs)
    if not devs:
        print("bluetooth      : no audio device connected")
    for d in devs:
        a = d["active"] or {}
        pname = str(a.get("name") or "off")
        line = f"bluetooth      : {d['description']}  on {pname}"
        if a.get("description"):
            line += f": {a['description']}"
        print(line)
        if is_headset(pname):
            print("                 mono 16 kHz for every app; `duo audio stereo` puts it back")
    loops = audio_probe.data_loops(audio_probe.unit_pids())
    if loops:
        print("realtime       : " + " · ".join(f"{u} {pol}" for u, _p, _t, pol, _r in loops))
    if policy_installed():
        print("headset switch : off (a voice app no longer moves a headset to mono)")
    else:
        print("headset switch : on, Ubuntu's default: a voice app moves a headset to mono 16 kHz; ./install.sh --user turns it off")


def cmd_profiles(dev):
    cur = (dev["active"] or {}).get("index")
    print(f"{dev['description']}:")
    for p in sorted(dev["profiles"], key=lambda p: p.get("index", 0)):
        mark = "*" if p.get("index") == cur else " "
        avail = "" if p.get("available") in ("yes", None) else f"  [{p.get('available')}]"
        kind = "stereo" if is_stereo(str(p.get("name", ""))) else ("headset" if is_headset(str(p.get("name", ""))) else "")
        print(f" {mark} {p.get('index', '?'):>3}  {p.get('name', '?'):<26} {p.get('description', '')}{avail}"
              + (f"  ({kind})" if kind else ""))


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    verb = argv[0] if argv else "status"
    rest = argv[1:]
    try:
        if verb == "status":
            if rest:
                raise Problem("status takes no argument", 64)
            cmd_status(audio_probe.read_pw_dump())
            return 0
        if verb == "profile":
            if not rest:
                raise Problem("profile needs a name or an index (see `duo audio profiles`)", 64)
            key, hint = rest[0], " ".join(rest[1:])
        elif verb in ("stereo", "headset", "profiles"):
            key, hint = "", " ".join(rest)
        else:
            raise Problem(f"unknown verb {verb!r}: status | stereo | headset | profiles | profile NAME", 64)
        dev = pick_device(bluetooth_devices(audio_probe.read_pw_dump()), hint)
        if verb == "profiles":
            cmd_profiles(dev)
            return 0
        if verb == "profile":
            prof = profile_by(dev, key)
            if prof is None:
                raise Problem(f"{dev['description']} has no profile {key!r}; `duo audio profiles` lists them")
        else:
            prof = best_profile(dev, verb)
            if prof is None:
                raise Problem(f"{dev['description']} offers no {verb} profile; `duo audio profiles` lists what it has")
        ended = switch(dev, prof)
        kind = "stereo" if is_stereo(str(ended.get("name", ""))) else ("headset: its mic, mono 16 kHz" if is_headset(str(ended.get("name", ""))) else "")
        log(f"{dev['description']} is on {ended.get('name')} ({ended.get('description')})" + (f"; {kind}" if kind else ""))
        return 0
    except Problem as e:
        log(str(e))
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
