# A floor under the audio graph's buffer size.
#
# Without it, any application that asks PipeWire for a small buffer resizes the
# ALSA device too, and on this machine's SOF pipeline that underruns into a
# wedge it never recovers from: every stream on the device goes silent until
# something re-opens it. Roblox is the one that does it in practice, asking for
# 240 frames. The measurements, and what to do if you actually want a small
# buffer, are in the config file this installs.
#
# Nothing here is Nix-specific: ./install.sh --user drops the same file for a
# non-Nix machine, and both read it from config/pipewire/, which is the one
# definition.
{ config, lib, ... }:

let
  cfg = config.zenduo;
in
{
  options.zenduo.audioBufferFloor = (lib.mkEnableOption ''
    a floor under the audio buffer, equal to PipeWire's own default quantum, so
    one application asking for a small buffer cannot wedge the sound device and
    silence everything else on it. On by default: the floor IS the default
    size, so nothing runs with a smaller buffer than it already did. Turn it off
    for recording or DAW work, which need a small buffer
  '') // { default = true; };

  config = lib.mkIf (cfg.enable && cfg.audioBufferFloor) {
    # PipeWire merges every *.conf in this directory over its own config, and
    # reads them when it starts, so a change here needs a re-login, or the
    # pw-metadata line documented in the file to apply it to a running server.
    xdg.configFile."pipewire/pipewire.conf.d/10-zenduo-min-quantum.conf".source =
      ../config/pipewire/10-zenduo-min-quantum.conf;
  };
}
