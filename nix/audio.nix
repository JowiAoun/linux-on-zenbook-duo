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
# copy the numbers here rather than trusting the mic.
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
# and nothing anywhere logged a complaint. Every enum below is therefore an
# integer, with the label in a comment, and `filterType` names the one that
# matters. Filter's own type list is
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
# this repo exists to produce) `--load-preset` on the daemon's own argv is a
# silent no-op. A client-side `easyeffects -l <preset>` against the already
# running daemon does work, which is why this file used to carry an
# ExecStartPost that waited for the daemon's socket and then issued one.
#
# Seeding the db directly is strictly better and is what happens now: one
# mechanism that works on a fresh machine and an established one alike, no
# daemon-readiness polling or Qt client round-trip, and it makes this file the
# source of truth on *every* start instead of only the first.
#
# Consequence worth knowing: tweaking the chain in the EasyEffects GUI lasts for
# the session and EE will persist it to its db on a clean exit, but ExecStartPre
# overwrites that at the next start — so tune by ear in the GUI, then copy the
# numbers into `pluginDb` below.
{ config, lib, pkgs, ... }:

let
  cfg = config.zenduo;

  presetName = "duo-speakers";

  # Order IS the signal chain. Each entry becomes one PipeWire filter node named
  # ee_soe_<plugin> when the chain is up, which is how you check it is running:
  #   pw-dump | grep ee_soe_
  outputPlugins = [ "filter#0" "bass_enhancer#0" "compressor#0" "limiter#0" ];

  # Filter type. INTEGER in the db, label in the preset — see THE TRAP above.
  filterType = { highPass = 1; };

  # Filter slope, also an integer, and the one setting here whose label spelling
  # could not be established: the binary carries no x1..x4 strings, and putting
  # "24 dB/oct" in a preset made EE drop the key rather than store it (frequency
  # and type from the same object persisted fine). So this value is measured,
  # not read off a label — 0 is the default and is a NO-OP, and 2 gives the
  # skirt tabulated below. That is also why the shipped preset cannot express
  # it: load the preset in the GUI and you get a flat filter. The db is
  # authoritative; the preset is illustrative.
  filterSlope = 2;

  # Corner of the high-pass, in Hz. Chosen against BOTH measured curves, not
  # picked off the acoustic one alone, because this filter's skirt is broad and
  # the compressor behind it partially fills the skirt back in.
  #
  # At 180 Hz the chain was still 8.0 dB down at 250 Hz and 4.7 dB down at
  # 400 Hz — well inside the band where the drivers do work (250 Hz is only
  # −13.7 dB acoustically, 400 Hz −4.4 dB), so it audibly thins the warmth
  # region. At 120 Hz, measured through the full chain relative to its own
  # passband:
  #
  #      50 Hz  −23.6      120 Hz   −7.6      315 Hz   −2.9
  #      63     −17.5      160      −4.5      400      −2.3
  #      80     −13.0      200      −3.2      630      −1.0
  #     100      −9.8      250      −2.9      1k       −0.4
  #
  # i.e. the sub-bass the drivers cannot reproduce is gone while 250 Hz and up
  # is within 3 dB. Broadband output is unchanged by the move (+3.25 dB vs
  # +3.60 dB at typical program level), so the mid-bass is bought for nothing.
  #
  # Honest caveat: freeing excursion is meant to keep the CS35L41 protection DSP
  # out of the signal, and THAT part is standard practice plus theory — an A/B
  # on the internal mic could not resolve it above the noise, so do not treat it
  # as measured here. The corner choice itself is.
  highPassHz = 120;

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

  # The db files EasyEffects restores its chain from. These, not the preset
  # JSON, are the working mechanism — see the header. Keys are the plugin's
  # camelCase property names (the preset's kebab-case names with the hyphens
  # dropped), and only non-defaults need to be listed. The group header and the
  # rc file name were both read back off a real EE clean exit rather than
  # guessed; EE writes `bassEnhancerrc`, not `bass_enhancerrc`.
  pluginDb = {
    # 1. High-pass. Everything below is excursion the drivers spend for nothing.
    #    `slope` is not optional here: leave it out and the filter is a no-op
    #    that measures FLAT — which is exactly how the first cut of this chain
    #    shipped a high-pass that did nothing at all.
    filterrc = {
      group = "[soe][Filter#0]";
      settings = {
        type = filterType.highPass;
        frequency = highPassHz;
        slope = filterSlope;
      };
    };

    # 2. Bass psychoacoustics. Sits AFTER the high-pass on purpose: it adds
    #    harmonics of the fundamentals just removed, and the ear reconstructs
    #    the missing pitch from them. `scope` is the band it works on, so it
    #    tracks highPassHz; `floor` stops it chasing rumble.
    bassEnhancerrc = {
      group = "[soe][BassEnhancer#0]";
      settings = {
        amount = 6;
        scope = 200;
        floor = 40;
        floorActive = true;
      };
    };

    # 3. Downward compressor, staged so the net gain is positive EVERYWHERE.
    #    makeup (8) >= the worst-case reduction on real material (7 dB at
    #    −6 dBFS RMS in), which is the property the old settings violated.
    #    More makeup / lower threshold = louder low end; the limiter below is
    #    what makes raising it safe.
    compressorrc = {
      group = "[soe][Compressor#0]";
      settings = {
        attack = 10;              # ms — fast enough to catch transients
        release = 150;            # ms — smooth, avoids obvious pumping
        threshold = -20;          # dB
        ratio = 2;                # 2:1 — gentle; 4:1 is what over-compressed it
        knee = -6;                # soft knee (6 dB) for a gentle onset
        makeup = 9;               # dB — must cover the worst-case reduction
        # -80, not -100: the plugin's floor is -80.01 and EE rejects anything
        # below it ("setReleaseThreshold: value -100 is less than the minimum
        # value of -80.01"). This is the minimum in range, i.e. off.
        releaseThreshold = -80;
      };
    };

    # 4. Brickwall. This is the piece whose absence forced the old revision to
    #    keep its makeup too small to be worth anything.
    #
    #    gainBoost is the second silent default that bit this file, and it is
    #    not obvious from the name: LSP's gain boost adds back exactly the
    #    amount the threshold was lowered by, so `threshold = -1` with the
    #    default `gainBoost = true` is not a -1 dBFS ceiling at all — it is a
    #    0 dBFS one. MEASURED 2026-07-25, stepped pink noise, float capture of
    #    the sink so nothing could be blamed on the capture format:
    #
    #      gainBoost (default true)   peak out 0.000 dBFS, max sample 0.999999
    #      gainBoost = false          peak out -1.000 dBFS at every level
    #
    #    Both read as "the limiter is working" unless you look at the peak, and
    #    the first one hands the DAC a signal with no true-peak headroom at all.
    #    The decibel it gives back is bought properly in the compressor's makeup
    #    instead, which the limiter can then actually hold.
    limiterrc = {
      group = "[soe][Limiter#0]";
      settings = {
        threshold = -1;           # dBFS — a REAL ceiling, given gainBoost off
        gainBoost = false;
        lookahead = 5;            # ms
        attack = 5;               # ms
        release = 50;             # ms
      };
    };
  };

  # `toString true` is "1" in Nix and `toString false` is "" — either would be
  # written to the db as a number and silently ignored, so booleans go through
  # lib.boolToString.
  renderValue = v: if lib.isBool v then lib.boolToString v else toString v;

  renderIni = group: attrs:
    group + "\n"
    + lib.concatStrings (lib.mapAttrsToList (k: v: "${k}=${renderValue v}\n") attrs);

  seedDb = pkgs.writeShellScript "zenduo-easyeffects-seed-db" ''
    set -u
    export PATH="${lib.makeBinPath [ pkgs.coreutils pkgs.gnugrep pkgs.gnused ]}:/usr/bin:/bin:''${PATH:-}"

    db="''${XDG_CONFIG_HOME:-$HOME/.config}/easyeffects/db"
    mkdir -p "$db"

    # EasyEffects owns these files at runtime and rewrites them on a clean exit,
    # so they cannot be /nix/store symlinks — it would either fail to save or
    # replace the link with a regular file and desync the generation. Seeding
    # them instead keeps Nix the source of truth while leaving EE able to write.
    ${lib.concatStrings (lib.mapAttrsToList (file: spec: ''
      cat > "$db/${file}" <<'EOF'
      ${renderIni spec.group spec.settings}EOF
    '') pluginDb)}

    # easyeffectsrc also holds the input/output device EE picked and its preset
    # bookkeeping, which is runtime state we have no business overwriting — so
    # only the plugin list is asserted here, in place, leaving the rest alone.
    rc="$db/easyeffectsrc"
    [ -f "$rc" ] || printf '[StreamOutputs]\n' > "$rc"
    if grep -q '^\[StreamOutputs\]' "$rc"; then
      if grep -q '^plugins=' "$rc"; then
        sed -i 's|^plugins=.*|plugins=${lib.concatStringsSep "," outputPlugins}|' "$rc"
      else
        sed -i 's|^\[StreamOutputs\]|[StreamOutputs]\nplugins=${lib.concatStringsSep "," outputPlugins}|' "$rc"
      fi
    else
      printf '\n[StreamOutputs]\nplugins=%s\n' '${lib.concatStringsSep "," outputPlugins}' >> "$rc"
    fi
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
      #
      # The preset file itself is still shipped so the tuning is visible in the
      # EasyEffects GUI and can be re-selected there by hand. It mirrors
      # pluginDb above; keep the two in step if you change either — and note the
      # enums are spelled as LABELS here and as INTEGERS in the db.
      extraPresets.${presetName} = {
        output = {
          blocklist = [ ];
          plugins_order = outputPlugins;
          # NOTE: no `slope` — EE 8 drops the key from a preset (see filterSlope
          # above), so loading this preset in the GUI gives a FLAT filter, not
          # the shipped one. It is here to show the chain, not to reproduce it.
          "filter#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            type = "High-pass";
            frequency = highPassHz * 1.0;
          };
          "bass_enhancer#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            amount = 6.0;
            scope = 200.0;
            floor = 40.0;
            "floor-active" = true;
          };
          "compressor#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            mode = "Downward";
            attack = 10.0;
            release = 150.0;
            "release-threshold" = -80.0;
            threshold = -20.0;
            ratio = 2.0;
            knee = -6.0;
            makeup = 9.0;
            "boost-threshold" = -72.0;
            "boost-amount" = 6.0;
            "stereo-split" = false;
          };
          "limiter#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            threshold = -1.0;
            "gain-boost" = false;
            lookahead = 5.0;
            attack = 5.0;
            release = 50.0;
          };
        };
      };
    };

    systemd.user.services.easyeffects.Service = {
      # Order matters only in that both must finish before EE reads its db.
      ExecStartPre = [ "${seedDb}" "${waitForDisplay}" ];
    };
  };
}
