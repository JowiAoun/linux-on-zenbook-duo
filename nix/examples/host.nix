# Example: the Zenbook Duo host profile of a home-manager flake.
#
# flake.nix:
#   inputs.zenbook-duo = {
#     url = "github:JowiAoun/linux-on-zenbook-duo";
#     inputs.nixpkgs.follows = "nixpkgs";
#   };
#   ...
#   homeConfigurations.laptop = home-manager.lib.homeManagerConfiguration {
#     inherit pkgs;
#     extraSpecialArgs = { inherit inputs; };
#     modules = [ ./home.nix ./hosts/zenbook-duo.nix ];
#   };
#
# hosts/zenbook-duo.nix (this file):
{ inputs, ... }:

{
  imports = [ inputs.zenbook-duo.homeManagerModules.default ];

  # Nix-installed GUI apps get icons/.desktop/XDG integration on Ubuntu.
  targets.genericLinux.enable = true;

  zenduo = {
    enable = true;
    # 80 is a good default for a mostly-plugged-in laptop.
    batteryLimit = 80;
    # The built-in speakers have a ~65 dB range fed by a cubic volume slider, so
    # the bottom 40% of the slider is inaudible. The EasyEffects chain lifts the
    # average level so low/mid settings are usable — see nix/audio.nix.
    speakerDsp = true;
    # Developing the tooling? Point the units at a live checkout:
    # repoPath = "/home/me/p/linux-on-zenbook-duo";
  };
}
