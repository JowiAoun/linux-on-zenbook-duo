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

    checks.${system} = let
      # The module must evaluate with every feature on. This is what catches a
      # broken option or attribute before a user's `home-manager switch` does.
      hm = home-manager.lib.homeManagerConfiguration {
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
      };
    in {
      package = self.packages.${system}.zenduo;
      hm-module = hm.activationPackage;
      # Every generated unit logs under the zenduo identifier, or `duo log`
      # misses the daemons (that was the case until 2026-09-05).
      hm-units = pkgs.runCommand "zenduo-hm-units" { } ''
        n=0
        for u in ${hm.config.home-files}/.config/systemd/user/duo-*.service; do
          grep -q '^SyslogIdentifier=zenduo$' "$u" || { echo "$u lacks SyslogIdentifier=zenduo" >&2; exit 1; }
          n=$((n + 1))
        done
        [ "$n" -eq 5 ] || { echo "expected 5 duo-* units, found $n" >&2; exit 1; }
        touch "$out"
      '';
    };

    devShells.${system}.default = pkgs.mkShell {
      packages = [ pkgs.shellcheck (pkgs.python3.withPackages (ps: [ ps.pygobject3 ])) ];
    };
  };
}
