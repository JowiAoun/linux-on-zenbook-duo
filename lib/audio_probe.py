#!/usr/bin/env python3
"""What the audio session looks like right now, for `duo doctor` and the screen.

Two questions, answered from what PipeWire and the kernel already expose:

  * which profile each Bluetooth audio device is on. A headset on a
    "headset-head-unit" profile (HFP) plays every application in mono at
    16 kHz, which is the "sound went static and low quality" report;
    config/wireplumber/11-zenduo-bluetooth-stereo.lua says why that happens.
  * whether PipeWire's data loops hold realtime priority. They ask rtkit once,
    at start, and a login quick enough to start PipeWire before rtkit leaves
    them at normal priority for the session; config/systemd/user/
    10-zenduo-rtkit.conf has the measurements.

    audio_probe.py                  both, one line each
    audio_probe.py bluetooth        <device.name> <description> <profile> <profile description>
    audio_probe.py realtime [--grant]
                                    <unit> <pid> <tid> <policy> [<what --grant did>]

Fields are tab-separated. --grant asks rtkit (MakeThreadRealtimeWithPID) for
priority 20 on every loop that has none, which is what PipeWire itself would
have asked for; it needs no root, only the same user.

Exit 0 with nothing printed when there is nothing to report: no PipeWire, no
Bluetooth device, no user session.
"""

import json
import os
import subprocess
import sys

UNITS = ("pipewire", "pipewire-pulse", "wireplumber")
LOOP_COMM = "pw-data-loop"
RT_PRIORITY = 20        # rtkit's MaxRealtimePriority; PipeWire asks for 88 and gets this
POLICY = {0: "other", 1: "fifo", 2: "rr", 3: "batch", 5: "idle", 6: "deadline"}


def run(argv, timeout=10):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return p.returncode, p.stdout


# ── Bluetooth ────────────────────────────────────────────────────────────────

def read_pw_dump():
    """Every PipeWire object as pw-dump prints it, or [] without a server."""
    rc, out = run(["pw-dump"])
    if rc != 0:
        return []
    try:
        objs = json.loads(out)
    except ValueError:
        return []
    return objs if isinstance(objs, list) else []


def bluetooth_profiles(objs):
    """[{name, description, profile, profile_description, stereo, headset}]
    for each bluez5 device in a pw-dump listing."""
    out = []
    for o in objs:
        if not isinstance(o, dict) or not str(o.get("type", "")).endswith("Interface:Device"):
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("device.api") != "bluez5":
            continue
        profile = ""
        desc = ""
        for p in (info.get("params") or {}).get("Profile") or []:
            profile = str(p.get("name", ""))
            desc = str(p.get("description", ""))
            break
        out.append({
            "name": str(props.get("device.name", "")),
            "description": str(props.get("device.description") or props.get("device.name", "")),
            "profile": profile,
            "profile_description": desc,
            # a2dp-sink* and bap-sink* carry stereo at the graph rate;
            # headset-head-unit* is HFP/HSP, mono, 8 or 16 kHz
            "stereo": profile.startswith(("a2dp-sink", "bap-sink")),
            "headset": profile.startswith("headset-head-unit"),
        })
    return out


# ── realtime ─────────────────────────────────────────────────────────────────

def unit_pids(units=UNITS):
    """{unit: MainPID} for the user services that are running."""
    pids = {}
    for u in units:
        rc, out = run(["systemctl", "--user", "show", "-p", "MainPID", "--value", f"{u}.service"])
        if rc == 0 and out.strip().isdigit() and int(out) > 0:
            pids[u] = int(out)
    return pids


def thread_policy(proc, pid, tid):
    """(policy name, rt priority) from /proc/<pid>/task/<tid>/stat."""
    try:
        with open(os.path.join(proc, str(pid), "task", str(tid), "stat")) as f:
            line = f.read()
    except OSError:
        return "", 0
    # The comm field is in parentheses and may hold spaces, so split after it:
    # field 40 is rt_priority and 41 the policy, counting from 1 with the pid.
    rest = line.rpartition(")")[2].split()
    try:
        return POLICY.get(int(rest[38]), rest[38]), int(rest[37])
    except (IndexError, ValueError):
        return "", 0


def data_loops(pids, proc="/proc"):
    """[(unit, pid, tid, policy, rt priority)] for every data loop thread."""
    out = []
    for unit, pid in pids.items():
        task_dir = os.path.join(proc, str(pid), "task")
        try:
            tids = sorted(int(t) for t in os.listdir(task_dir) if t.isdigit())
        except OSError:
            continue
        for tid in tids:
            try:
                with open(os.path.join(task_dir, str(tid), "comm")) as f:
                    comm = f.read().strip()
            except OSError:
                continue
            if comm != LOOP_COMM:
                continue
            policy, prio = thread_policy(proc, pid, tid)
            out.append((unit, pid, tid, policy, prio))
    return out


def grant_realtime(pid, tid, priority=RT_PRIORITY):
    """Ask rtkit for realtime on one thread; '' on success, else why not."""
    rc, out = run(["busctl", "--system", "--timeout=5", "call",
                   "org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1",
                   "org.freedesktop.RealtimeKit1", "MakeThreadRealtimeWithPID",
                   "ttu", str(pid), str(tid), str(priority)])
    return "" if rc == 0 else (out.strip().splitlines() or ["busctl failed"])[-1]


# ── the command line ─────────────────────────────────────────────────────────

def print_bluetooth():
    for d in bluetooth_profiles(read_pw_dump()):
        print("\t".join((d["name"], d["description"], d["profile"], d["profile_description"])))


def print_realtime(grant=False):
    for unit, pid, tid, policy, _prio in data_loops(unit_pids()):
        cols = [unit, str(pid), str(tid), policy]
        if grant:
            if policy in ("fifo", "rr"):
                cols.append("kept")
            else:
                err = grant_realtime(pid, tid)
                cols.append("granted" if not err else f"refused: {err}")
        print("\t".join(cols))


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    what = [a for a in argv if not a.startswith("-")]
    grant = "--grant" in argv
    if not what or what[0] == "bluetooth":
        print_bluetooth()
    if not what or what[0] == "realtime":
        print_realtime(grant)
    if what and what[0] not in ("bluetooth", "realtime"):
        print(f"audio_probe: unknown command {what[0]!r} (bluetooth | realtime)", file=sys.stderr)
        return 64
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
