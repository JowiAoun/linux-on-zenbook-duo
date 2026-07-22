# Touchpad disable-while-typing for the Duo's detachable touchpad.
#
# Pairs with system/55-touchpad-quirks.sh: that libinput quirk is what actually
# lets disable-while-typing apply to this EXTERNAL combo touchpad; this half just
# makes sure GNOME's DWT switch is on. It's on by default, but GNOME's UI does
# not expose the toggle, so declaring it keeps the behavior explicit and
# reproducible (and survives a machine where it got turned off).
{ config, lib, ... }:

let
  cfg = config.zenduo;
in
{
  options.zenduo.palmRejection = (lib.mkEnableOption
    "Windows-like touchpad disable-while-typing / palm rejection")
    // { default = true; };

  config = lib.mkIf (cfg.enable && cfg.palmRejection) {
    dconf.settings."org/gnome/desktop/peripherals/touchpad".disable-while-typing = true;
  };
}
