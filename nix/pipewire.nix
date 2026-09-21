# The PipeWire and WirePlumber settings the project ships: a floor under the
# audio buffer, Bluetooth headsets kept in stereo, and PipeWire's realtime
# priority at login. Each one is a file under config/, the same file
# ./install.sh --user drops on a non-Nix machine, so there is one definition
# of each and the file itself carries the measurements.
{ config, lib, ... }:

let
  cfg = config.zenduo;
  rtkitDropIn = ../config/systemd/user/10-zenduo-rtkit.conf;
in
{
  options.zenduo.audioBufferFloor = (lib.mkEnableOption ''
    a floor under the audio buffer, equal to PipeWire's own default quantum, so
    one application asking for a small buffer cannot wedge the sound device and
    silence everything else on it. On by default: the floor IS the default
    size, so nothing runs with a smaller buffer than it already did. Turn it off
    for recording or DAW work, which need a small buffer
  '') // { default = true; };

  options.zenduo.bluetoothStereo = (lib.mkEnableOption ''
    keeping a Bluetooth headset on its stereo (A2DP) profile when a voice app
    opens the microphone. WirePlumber's stock policy moves the headset to its
    mono 16 kHz headset profile, for every application's sound, the moment
    Discord, a browser call or Zoom starts capturing, and back two seconds
    after it stops: that is the "sound went static and low quality" report.
    On by default. The headset's own microphone is then a manual choice in
    Settings > Sound, as it is on Windows
  '') // { default = true; };

  options.zenduo.audioRealtime = (lib.mkEnableOption ''
    a drop-in for pipewire, pipewire-pulse and wireplumber that waits for
    rtkit before they start, so their data loops get the realtime priority
    they ask for. A login quick enough to start PipeWire before rtkit leaves
    them at normal priority for the whole session. On by default
  '') // { default = true; };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    (lib.mkIf cfg.audioBufferFloor {
      # PipeWire merges every *.conf in this directory over its own config, and
      # reads them when it starts, so a change here needs a re-login, or the
      # pw-metadata line documented in the file to apply it to a running server.
      xdg.configFile."pipewire/pipewire.conf.d/10-zenduo-min-quantum.conf".source =
        ../config/pipewire/10-zenduo-min-quantum.conf;
    })
    (lib.mkIf cfg.bluetoothStereo {
      # WirePlumber 0.4 reads the Lua file, 0.5 and later the .conf; each
      # ignores the other's directory. Both are read at start, so a change
      # needs `systemctl --user restart wireplumber`.
      xdg.configFile."wireplumber/policy.lua.d/11-zenduo-bluetooth-stereo.lua".source =
        ../config/wireplumber/11-zenduo-bluetooth-stereo.lua;
      xdg.configFile."wireplumber/wireplumber.conf.d/zenduo-bluetooth-stereo.conf".source =
        ../config/wireplumber/zenduo-bluetooth-stereo.conf;
    })
    (lib.mkIf cfg.audioRealtime {
      xdg.configFile = lib.listToAttrs (map (unit: lib.nameValuePair
        "systemd/user/${unit}.service.d/10-zenduo-rtkit.conf" { source = rtkitDropIn; })
        [ "pipewire" "pipewire-pulse" "wireplumber" ]);
    })
  ]);
}
