{
  description = "Linux on the ASUS Zenbook Duo (2024) UX8406MA: dual-screen dock policy, keyboard hotkeys and backlight, speaker voicing, battery limit";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # Only used by the flake check that evaluates the home-manager module.
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, home-manager }:
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
  in {
    packages.${system} = rec {
      zenduo = pkgs.callPackage ./nix/package.nix { };
      default = zenduo;
    };

    # import this into a home-manager configuration, then set `zenduo.*`:
    #   inputs.zenbook-duo.homeManagerModules.default
    homeManagerModules = rec {
      zenduo = import ./nix/home-manager.nix;
      default = zenduo;
    };

    checks.${system} = {
      package = self.packages.${system}.zenduo;
      # The module must evaluate with every feature on. This is what catches a
      # broken option or attribute before a user's `home-manager switch` does.
      hm-module = (home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        modules = [
          self.homeManagerModules.default
          {
            home.username = "duo";
            home.homeDirectory = "/home/duo";
            home.stateVersion = "24.05";
            zenduo = {
              enable = true;
              batteryLimit = 80;
              speakerDsp = true;
              watchBacklight = true;
              watchRotation = true;
            };
          }
        ];
      }).activationPackage;
    };

    devShells.${system}.default = pkgs.mkShell {
      packages = [ pkgs.shellcheck (pkgs.python3.withPackages (ps: [ ps.pygobject3 ])) ];
    };
  };
}
