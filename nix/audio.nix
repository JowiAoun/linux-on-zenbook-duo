# Speaker voicing for the Duo's tiny built-in speakers.
#
# ── What the hardware actually does (MEASURED 2026-07-25) ─────────────────────
# Two Cirrus CS35L41 smart amps (L/R) behind the ALC294, running ASUS's
# `spk-prot` firmware with this unit's own calibration (R0=10223/10307). That
# firmware is *protection* — excursion and thermal limiting — not voicing. On
# Windows the tonal work is done above the driver, in ASUS/harman-kardon's APO:
# a high-pass, bass psychoacoustics, a corrective EQ and a limiter. Linux has no
# equivalent, so out of the box the speakers play the raw stream. That gap, not
# the amp, is why the machine sounds worse than it does under Windows.
#
# Acoustic response, third-octave pink noise through the speakers, captured on
# the internal DMIC array with the DMIC DRC off, EasyEffects bypassed, relative
# to the 630 Hz peak:
#
#     630 Hz   0.0 dB  ← peak        1.6k  −8.2      6.3k  −11.3
#     500     −1.4                   2k    −10.0     8k    −12.3
#     400     −4.4                   2.5k  −10.5     10k   −13.3
#     315     −8.9                   3.15k  −9.8
#     250    −13.7                   4k    −10.0
#     200    −18.3
#     160    −22.5
#     125    −26.6
#     100    −29.4  (at/below the measurement noise floor from here down)
#
# Read it as a shape, not an anechoic curve: the DMIC sits on the top bezel and
# the drivers fire away from it, so absolute level and especially the treble
# tilt are path- and mic-coloured. The bass end is trustworthy — low frequencies
# are omnidirectional, so mic placement barely matters — and it says the useful
# band starts around 300–400 Hz and everything below 200 Hz is >18 dB down.
# Content down there is inaudible but still costs cone excursion, which is what
# drags the CS35L41's protection DSP in and pulls the *whole* signal down with
# it. Removing it is the single largest available quality win.
#
# ── Why the previous revision of this file did nothing (MEASURED 2026-07-25) ──
# It ran one downward compressor: threshold −24, ratio 4:1, makeup 8. Sized, per
# its own note, so a 0 dBFS peak would land near −10 dBFS "well short of
# clipping, so no limiter is needed". That is the bug. Above the threshold the
# gain reduction grows three times faster than the fixed makeup can repay, so
# the net gain falls through zero and keeps going:
#
#     out = −24 + (in + 24)/4 + 8  =  in/4 − 10      →  unity at in = −13.3 dBFS
#
# Measured on the running graph, playing stepped pink noise into
# easyeffects_sink and capturing the ALSA sink monitor, against the same signal
# with the service stopped:
#
#     in dBFS   −40    −28    −24    −20    −16    −12    −8     −4
#     gain dB   +8.0   +7.2   +5.5   +2.9   −0.1   −3.1   −6.1   −8.3
#
# Streaming services normalise to about −14 LUFS, which lands within a decibel
# of that unity crossing — so on the material the machine actually plays, the
# "loudness fix" did nothing, and on anything louder it made the speakers
# *quieter*, by up to 8 dB at the top. Hence "nothing really changed".
#
# ── The fix: stage the gain so it can never go negative ───────────────────────
# A downward compressor is only a loudness tool if the makeup covers the worst
# case reduction; then a limiter, not a conservative makeup, keeps the peaks
# safe. With threshold −20, ratio 2:1 and makeup 8, the deepest reduction on
# real material (≈ −6 dBFS RMS) is 7 dB, so 8 dB of makeup keeps the curve
# positive everywhere — +8 dB where the slider is unusable today, still slightly
# positive where it used to lose 8 dB. The limiter then brickwalls what is left.
#
# Chain order matters: high-pass FIRST, so the compressor and limiter never
# spend their range on sub-bass the drivers cannot reproduce, and the bass
# enhancer sits behind the high-pass so it synthesises harmonics of the
# fundamentals that were just removed — the ear reconstructs the missing pitch
# from them. That is the same trick the Windows APO plays.
#
# Same measurement, same signal, this chain against the old one:
#
#     in dBFS   −24    −20    −16    −12    −8     −4
#     old       +5.5   +2.9   −0.1   −3.1   −6.1   −8.3
#     new       +5.3   +4.6   +3.2   +1.3   −1.5   −4.6
#     peak out  −6.9   −3.6   −1.0   −1.0   −1.0   −1.0
#
# Around −14 dBFS, where streaming actually lives, that is roughly +3.5 dB
# against the old chain, and the peak column is the other half of the point:
# the output is now bounded at the limiter's ceiling instead of wherever the
# programme happened to land. The two ends deserve their caveats. The quiet end
# reads lower than it could only because pink noise is roughly a third
# sub-120 Hz energy and the high-pass throws that away — energy the drivers
# were never reproducing. The loud end stays slightly negative because pink
# noise has a ~12 dB crest factor, so the limiter works far harder on it than
# on music; at −4 dBFS RMS no real master exists anyway.
#
# Starting point, not gospel. `speakerDsp = false` reverts cleanly. Voicing EQ
# is the knob left deliberately unset: the response above is not calibrated
# enough to derive a corrective curve from, so tune one by ear in the GUI and
# copy the numbers into lib/speaker_dsp.py rather than trusting the mic.
#
# ── THE TRAP: a db enum is an INTEGER, and the wrong value is SILENT ──────────
# EasyEffects has two serialisations of the same setting and they DO NOT AGREE.
# A preset JSON stores an enum as its label; the db stores it as the index.
# VERIFIED 2026-07-25 by loading a preset and reading back what EE persisted:
#
#     duo-v3.json   "filter#0": { "type": "High-pass" }
#     filterrc      [soe][Filter#0]  type=1
#
# Seed `type=High-pass` into the db and EE drops it and keeps the plugin's
# default — which for Filter is a LOW-pass. That is not a hypothetical: it was
# measured on this machine as a 24 dB cut at 1 kHz with the bass *boosted* 13 dB,
# and nothing anywhere logged a complaint. Every enum in the db is therefore
# an integer, with the label alongside it in lib/speaker_dsp.py, which is where
# the chain now lives. Filter's own type list is
#   0 Low-pass  1 High-pass  2 Low-shelf  3 High-shelf  4 Band-pass
#   5 Ladder-rejection  6 All-pass
# and note it is NOT the Equalizer's list, which spells the same concept
# "Hi-pass" — passing that spelling to Filter is rejected too, just as silently.
#
# ── How to check whether any of this is running (READ THIS FIRST) ─────────────
# EasyEffects creates one PipeWire filter node per plugin, ee_soe_<plugin>, but
# ON DEMAND: the node appears a second or two after a stream connects and is
# torn down again after the graph goes idle. VERIFIED 2026-07-23 — sampling
# every 2 s, `ee_soe_compressor` vanished ~8 s after the last sound and came
# back mid-playback. So this, run against a silent machine, proves nothing:
#
#     pw-dump | grep ee_soe_        # ← only meaningful while audio is PLAYING
#
# Check it with something playing, and confirm the routing rather than just the
# node, since that also rules out a half-connected chain:
#
#     pw-link -l | grep -A2 ee_soe_filter
#     # want: easyeffects_sink:monitor_F{L,R} -> ee_soe_filter:input_F{L,R}
#     #       ... -> ee_soe_limiter -> ... -> the alsa sink
#
# Measuring it, rather than trusting it, is two recordings — one through the
# chain, one with `systemctl --user stop easyeffects` — of the ALSA sink monitor
# while stepped pink noise plays. The monitor tap is upstream of the hardware
# `Speaker` control, so `amixer -c0 sset Speaker mute` keeps the test silent
# without changing a single measured number.
#
# ── How the settings actually get applied (VERIFIED ON HARDWARE) ──────────────
# EasyEffects 8 is the Qt rewrite, and its `--load-preset` flag does not do the
# job. What decides the running chain is EE's own mutable db in
# ~/.config/easyeffects/db/ — `plugins=...` in easyeffectsrc plus one rc file
# per plugin — which EE reads on start and rewrites on a clean exit. On a
# machine whose db has never seen the preset (a fresh install, i.e. exactly what
# this module exists to produce) `--load-preset` on the daemon's own argv is a
# silent no-op.
#
# So the db is seeded directly, before every start, by `duo speaker-dsp seed`
# (lib/speaker_dsp.py). That script is the ONE definition of the chain — the
# integer-enum db files and the label-enum preset JSON both come out of it, and
# a unit test asserts the committed preset matches. The chain, with the
# reasoning for every number, is in that file; the measurements are above.
#
# Consequence worth knowing: tweaking the chain in the EasyEffects GUI lasts for
# the session and EE will persist it to its db on a clean exit, but ExecStartPre
# overwrites that at the next start — so tune by ear in the GUI, then copy the
# numbers into lib/speaker_dsp.py and run `make preset`.
{ config, lib, pkgs, ... }:

let
  cfg = config.zenduo;

  presetName = "duo-speakers";

  # EasyEffects 8 is a Qt application even in service mode: with no display it
  # cannot initialise a platform plugin and aborts (SIGABRT, "Could not load the
  # Qt platform plugin"). WantedBy=graphical-session.target does not order us
  # after the session's environment import, so on a cold boot the first start
  # loses that race and survives only via Restart=on-failure. Waiting for the
  # display costs a second and makes the first start the successful one.
  waitForDisplay = pkgs.writeShellScript "zenduo-easyeffects-wait-display" ''
    set -u
    export PATH="${lib.makeBinPath [ pkgs.coreutils pkgs.gnugrep ]}:/usr/bin:/bin:''${PATH:-}"

    # The manager environment is what ExecStart will inherit, and systemd builds
    # each process's environment when it spawns it — so blocking here until
    # WAYLAND_DISPLAY has been imported means ExecStart actually receives it.
    for _ in $(seq 1 60); do
      if systemctl --user show-environment 2>/dev/null | grep -q '^WAYLAND_DISPLAY=\|^DISPLAY='; then
        exit 0
      fi
      sleep 0.5
    done

    # Best effort: Restart=on-failure is still the backstop if it never shows up.
    echo "no display in the user environment after 30 s — starting anyway" >&2
    exit 0
  '';

in
{
  options.zenduo.speakerDsp = (lib.mkEnableOption ''
    an EasyEffects voicing chain on the speaker output: a high-pass that stops
    the drivers wasting excursion below what they can reproduce, bass
    psychoacoustics to put the perceived low end back, a compressor staged so
    its net gain is positive at every level, and a limiter to keep the peaks
    safe. Stands in for the ASUS/harman-kardon APO that does this job on Windows
  '') // { default = false; };

  config = lib.mkIf (cfg.enable && cfg.speakerDsp) {
    services.easyeffects = {
      enable = true;
      # `preset` is deliberately NOT set: it only puts --load-preset on the
      # daemon's argv, and that flag is the bug documented in the header.
    };

    # The preset file is shipped so the tuning is visible in the EasyEffects
    # GUI and can be re-selected there by hand. Generated from the same
    # definition the db seed comes from (`make preset`).
    xdg.configFile."easyeffects/output/${presetName}.json".source =
      ../presets/easyeffects/${presetName}.json;

    systemd.user.services.easyeffects.Service = {
      # Order matters only in that both must finish before EE reads its db.
      ExecStartPre = [ "${cfg.duoBin} speaker-dsp seed" "${waitForDisplay}" ];
    };
  };
}
