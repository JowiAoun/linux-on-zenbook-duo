# Speaker loudness fix for the Duo's tiny built-in speakers.
#
# The problem (measured on this machine): WirePlumber drives the ALSA `Speaker`
# control directly, and that control spans ~65 dB — 0..87 in clean 0.75 dB steps,
# −65 dB → 0 dB. The volume slider maps position p onto it as 60·log₁₀(p) dB,
# i.e. the cubic PulseAudio curve (VERIFIED 2026-07-23: slider 0.48 → −18.75 dB,
# slider 0.30 → −30.75 dB, while `Master` stays pinned at 0 dB). So the bottom
# 40% of slider travel is spent on −65…−24 dB. A palm-sized laptop speaker
# cannot audibly reproduce that band, so 10%→20% (−60→−42 dB) sounds identical
# and everything perceptible is crammed into the top 60%. Nothing is broken — a
# 65 dB range is just wrong for this transducer.
#
# The curve itself is not adjustable: it lives in the volume client, and it is
# the same 60·log₁₀(p) whether WirePlumber uses the hardware mixer or a software
# one, so there is no setting to flatten. A fixed gain does not help either — it
# shifts the top of the range up into clipping by exactly as much as it lifts the
# bottom. Changing the *shape* of the range is the only lever, and that means
# compression: a downward compressor with makeup gain pulls peaks down and lifts
# the average, so a given slider position produces a denser, louder signal and
# the useful range slides down into reach. EasyEffects runs it as a PipeWire
# output filter (a user systemd service). This is Duo-hardware-specific tuning,
# so it lives with the other zenduo bits rather than in the generic profile, and
# is off by default — flip it on per host.
#
# The SOF topology's own `Post Mixer Analog Playback DRC switch` looks like it
# should do this in hardware, and costs nothing to try, but it is inaudible on
# this ALC294 topology (VERIFIED 2026-07-23) — hence the software filter.
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
#     pw-link -l | grep -A2 ee_soe_compressor
#     # want: easyeffects_sink:monitor_F{L,R} -> ee_soe_compressor:input_F{L,R}
#     #       ee_soe_compressor:output_F{L,R} -> ... -> the alsa sink
#
# ── How the preset actually gets applied (VERIFIED ON HARDWARE) ───────────────
# EasyEffects 8 is the Qt rewrite, and its `--load-preset` flag does not do the
# job. What decides the running chain is EE's own mutable db in
# ~/.config/easyeffects/db/ — `plugins=compressor#0` in easyeffectsrc plus a
# per-plugin compressorrc — which EE reads on start and rewrites on a clean exit.
# On a machine whose db has never seen the preset (a fresh install, i.e. exactly
# what this repo exists to produce) `--load-preset` on the daemon's own argv is
# a silent no-op: it leaves `easyeffects -a output` empty and the chain unbuilt.
# A client-side `easyeffects -l <preset>` against the already-running daemon does
# work, which is why this file used to carry an ExecStartPost that waited for the
# daemon's socket and then issued one.
#
# Seeding the db directly is strictly better and is what happens now: it is one
# mechanism that works on a fresh machine and an established one alike, it needs
# no daemon-readiness polling or Qt client round-trip, and it makes this file the
# source of truth on *every* start instead of only the first.
#
# Consequence worth knowing: tweaking the chain in the EasyEffects GUI lasts for
# the session and EE will persist it to its db on a clean exit, but ExecStartPre
# overwrites that at the next start — so tune by ear in the GUI, then copy the
# numbers into `compressorDb` below.
#
# Starting point, not gospel: more `makeup` / lower `threshold` = louder low end.
# The makeup here is sized so even a 0 dBFS peak lands near −10 dBFS, well short
# of clipping, so no limiter is needed. `speakerDsp = false` reverts cleanly.
{ config, lib, pkgs, ... }:

let
  cfg = config.zenduo;

  presetName = "duo-speakers";

  # Each entry becomes one PipeWire filter node named ee_soe_<plugin>
  # (stream-output-effects, instance suffix dropped) when the chain is up, which
  # is how you check whether any of this is actually running:
  #   pw-dump | grep ee_soe_
  outputPlugins = [ "compressor#0" ];

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
  # camelCase property names, and only non-defaults need to be listed.
  compressorDb = {
    attack = 15;                # ms — fast enough to catch transients
    release = 120;              # ms — smooth, avoids obvious pumping
    threshold = -24;            # dB — start compressing well below peak
    ratio = 4;                  # 4:1 — firm but musical
    knee = -6;                  # soft knee (6 dB) for a gentle onset
    makeup = 8;                 # dB — the lift that makes low volumes usable
    # -80, not -100: the plugin's floor is -80.01 and EE rejects anything below
    # it ("setReleaseThreshold: value -100 is less than the minimum value of
    # -80.01"). This is the minimum in range, i.e. the feature effectively off.
    releaseThreshold = -80;
  };

  # EE's db groups are written as two bracketed parts, e.g. "[soe][Compressor#0]"
  # — soe = stream-output-effects. Passed in whole rather than assembled here so
  # the string in this file matches the string in the file on disk verbatim.
  renderIni = header: attrs:
    header + "\n"
    + lib.concatStrings (lib.mapAttrsToList (k: v: "${k}=${toString v}\n") attrs);

  seedDb = pkgs.writeShellScript "zenduo-easyeffects-seed-db" ''
    set -u
    export PATH="${lib.makeBinPath [ pkgs.coreutils pkgs.gnugrep pkgs.gnused ]}:/usr/bin:/bin:''${PATH:-}"

    db="''${XDG_CONFIG_HOME:-$HOME/.config}/easyeffects/db"
    mkdir -p "$db"

    # EasyEffects owns these files at runtime and rewrites them on a clean exit,
    # so they cannot be /nix/store symlinks — it would either fail to save or
    # replace the link with a regular file and desync the generation. Seeding
    # them instead keeps Nix the source of truth while leaving EE able to write.
    cat > "$db/compressorrc" <<'EOF'
${renderIni "[soe][Compressor#0]" compressorDb}EOF

    # easyeffectsrc also holds the input/output device EE picked, which is
    # runtime state we have no business overwriting — so only the plugin list is
    # asserted here, in place, leaving the rest of the file alone.
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
    an EasyEffects compressor on the speaker output so the bottom of the volume
    slider is usable. The Duo's amp has a ~65 dB range and the volume slider is
    cubic, which strands the low 40% of the slider below what the tiny speakers
    can reproduce; the compressor lifts the average level so those settings
    become audible
  '') // { default = false; };

  config = lib.mkIf (cfg.enable && cfg.speakerDsp) {
    services.easyeffects = {
      enable = true;
      # `preset` is deliberately NOT set: it only puts --load-preset on the
      # daemon's argv, and that flag is the bug documented in the header.
      #
      # The preset file itself is still shipped so the tuning is visible in the
      # EasyEffects GUI and can be re-selected there by hand. It mirrors
      # compressorDb above; keep the two in step if you change either.
      extraPresets.${presetName} = {
        output = {
          blocklist = [ ];
          plugins_order = outputPlugins;
          "compressor#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            mode = "Downward";
            attack = 15.0;
            release = 120.0;
            "release-threshold" = -80.0;
            threshold = -24.0;
            ratio = 4.0;
            knee = -6.0;
            makeup = 8.0;
            "boost-threshold" = -72.0;
            "boost-amount" = 6.0;
            "stereo-split" = false;
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
