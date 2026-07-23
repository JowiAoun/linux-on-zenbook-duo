# Speaker loudness fix for the Duo's tiny built-in speakers.
#
# The problem (measured on this machine): the internal amp (Realtek ALC294 via
# SOF) exposes a ~65 dB volume range — Master runs 0..87 in clean 0.75 dB steps,
# −65 dB → 0 dB. GNOME's volume slider is *cubic* (slider position p maps to
# amplitude ≈ p³, i.e. roughly 60·log₁₀(p) dB), so it spends its bottom ~40% of
# travel on −65…−24 dB. A palm-sized laptop speaker cannot audibly reproduce
# that band, so 10%→20% (−60→−42 dB) sounds identical and everything perceptible
# is crammed into the top 60% of the slider. Nothing is broken — a 65 dB range
# is just wrong for this transducer.
#
# You cannot reconfigure GNOME's cubic slider math, so the fix is to compress the
# signal's dynamic range: a downward compressor with makeup gain pulls the loud
# peaks down and lifts the average level, so a given slider position produces a
# louder, denser signal and the useful range slides down into reach. EasyEffects
# runs the compressor as a PipeWire output filter (a user systemd service). This
# is Duo-hardware-specific tuning, so it lives with the other zenduo bits rather
# than in the generic profile, and is off by default — flip it on per host.
#
# The SOF topology's own `Post Mixer Analog Playback DRC switch` looks like it
# should do this in hardware, and costs nothing to try, but it is inaudible on
# this ALC294 topology (VERIFIED 2026-07-23) — hence the software filter.
#
# ── Why ExecStartPost exists (EasyEffects 8 hardware fact) ───────────────────
# EasyEffects 8 is the Qt rewrite. Its live pipeline is NOT driven by the
# `--load-preset` it is started with: that flag is a no-op at startup because the
# preset manager is not up yet. What actually decides the running chain is
# mutable state in ~/.config/easyeffects/db/ (`plugins=compressor#0` in
# easyeffectsrc, plus a per-plugin compressorrc), which EE restores on start and
# rewrites on clean shutdown. VERIFIED ON HARDWARE 2026-07-23: a first start with
# `--load-preset duo-speakers` produced no `ee_soe_compressor` node at all and
# left `easyeffects -a output` empty; issuing the very same load as a *client*
# call against the running daemon created the node immediately. So on any machine
# whose db has never seen this preset — i.e. a fresh install, exactly the case
# this repo exists to serve — the declared preset would silently do nothing.
#
# Re-issuing the load once the daemon is listening makes the declarative preset
# the source of truth on every start, and is idempotent when it is already
# loaded. Note the consequence: tweaking the chain in the EasyEffects GUI lasts
# for the session but is re-applied from here at the next login, so tune by ear
# in the GUI and then copy the numbers into the preset below.
#
# Starting point, not gospel: more `makeup` / lower `threshold` = louder low end.
# The makeup here is sized so even a 0 dBFS peak lands near −10 dBFS, well short
# of clipping, so no limiter is needed. `speakerDsp = false` reverts cleanly.
{ config, lib, pkgs, ... }:

let
  cfg = config.zenduo;

  presetName = "duo-speakers";
  eePkg = config.services.easyeffects.package;

  applyPreset = pkgs.writeShellScript "zenduo-easyeffects-preset" ''
    set -u
    export PATH="${lib.makeBinPath [ pkgs.coreutils ]}:/usr/bin:/bin:''${PATH:-}"

    sock="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/EasyEffectsServer"

    # NEVER call easyeffects before the daemon is listening. With no primary
    # instance the client invocation becomes the primary itself and never
    # returns, which would hang ExecStartPost until the unit's start timeout.
    # The single-instance socket appearing is the precise "primary is up"
    # signal; it takes ~2 s on this machine.
    for _ in $(seq 1 60); do
      [ -S "$sock" ] && break
      sleep 0.5
    done
    if [ ! -S "$sock" ]; then
      echo "easyeffects never started listening — '${presetName}' not applied" >&2
      exit 0
    fi

    # Bounded: a socket left behind by an unclean exit must not wedge the unit.
    timeout 15 ${eePkg}/bin/easyeffects --load-preset ${presetName} \
      || echo "could not load preset '${presetName}'" >&2

    # Best effort by design — a preset that failed to apply is a quiet laptop,
    # not a reason to leave the audio daemon marked failed.
    exit 0
  '';
in
{
  options.zenduo.speakerDsp = (lib.mkEnableOption ''
    an EasyEffects compressor on the speaker output so the bottom of the volume
    slider is usable. The Duo's amp has a ~65 dB range and GNOME's slider is
    cubic, which strands the low 40% of the slider below what the tiny speakers
    can reproduce; the compressor lifts the average level so those settings
    become audible
  '') // { default = false; };

  config = lib.mkIf (cfg.enable && cfg.speakerDsp) {
    services.easyeffects = {
      enable = true;
      # Kept even though EE 8 ignores it at startup (see the header): it costs
      # nothing and is the documented way to express intent, while
      # ExecStartPost below is what actually makes it take effect.
      preset = presetName;
      extraPresets.${presetName} = {
        output = {
          blocklist = [ ];
          plugins_order = [ "compressor#0" ];
          "compressor#0" = {
            bypass = false;
            "input-gain" = 0.0;
            "output-gain" = 0.0;
            mode = "Downward";
            attack = 15.0;              # ms — fast enough to catch transients
            release = 120.0;            # ms — smooth, avoids obvious pumping
            # -80.0, not -100.0: the plugin's floor is -80.01 and EE rejects
            # anything below it outright ("setReleaseThreshold: value -100 is
            # less than the minimum value of -80.01"). This is the minimum in
            # range, i.e. the feature effectively off.
            "release-threshold" = -80.0;
            threshold = -24.0;          # dB — start compressing well below peak
            ratio = 4.0;                # 4:1 — firm but musical
            knee = -6.0;                # soft knee (6 dB) for a gentle onset
            makeup = 8.0;               # dB — the lift that makes low volumes usable
            "boost-threshold" = -72.0;
            "boost-amount" = 6.0;
            "stereo-split" = false;
          };
        };
      };
    };

    systemd.user.services.easyeffects.Service.ExecStartPost = "${applyPreset}";
  };
}
