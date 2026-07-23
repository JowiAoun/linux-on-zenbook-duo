# Host profile: the ASUS Zenbook Duo (2024) UX8406MA running Ubuntu 24.04.
# Pairs with the system layer: sudo make system HOST=zenbook-duo
{ ... }:

{
  imports = [ ../../modules/zenbook-duo ];

  # Nix-installed GUI apps get icons/.desktop/XDG integration on Ubuntu.
  targets.genericLinux.enable = true;

  zenduo = {
    enable = true;
    # watchBacklight / watchRotation stay off until each passes the on-hardware
    # test protocol (docs/PLAN.md §11.5); flip them here when they graduate.
    batteryLimit = 80;
    # The built-in speakers have a ~65 dB range fed by a cubic volume slider, so
    # the bottom 40% of the slider is inaudible. An EasyEffects compressor lifts
    # the average level so low/mid settings are usable — see modules/zenbook-duo/audio.nix.
    speakerDsp = true;
    # applyMethod stays "temporary" — see the option's warning: a persistent
    # apply makes gnome-shell prompt "Keep display settings?" every time, which
    # is unusable for a daemon that applies on every dock, undock and resume.
  };
}
