# home-manager module wiring the zenduo tooling (duo/) into the session.
# Imported only by hosts/zenbook-duo — generic machines never evaluate it.
{ config, lib, ... }:

let
  cfg = config.zenduo;

  watcher = sub: description: {
    Unit = {
      Description = "zenduo: ${description}";
      PartOf = [ "graphical-session.target" ];
      After = [ "graphical-session.target" ];
    };
    Service = {
      ExecStart = "${cfg.repoPath}/duo/bin/duo ${sub}";
      Restart = "on-failure";
      RestartSec = 3;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
in
{
  imports = [ ./touchpad.nix ];

  options.zenduo = {
    enable = lib.mkEnableOption "zenduo tooling for the ASUS Zenbook Duo (2024) UX8406MA";

    repoPath = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.dotfiles";
      description = "Absolute path of the dome checkout; the units run duo/ from here, so the tooling stays live-editable.";
    };

    watchDisplays = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Auto-toggle the bottom panel when the keyboard docks/undocks.";
    };

    watchBacklight = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Keep the bottom panel backlight synced to the top panel. Off until verified on hardware (PLAN.md v0.3).";
    };

    watchRotation = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Experimental rotation watcher (logs only for now).";
    };

    watchFn = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Init the keyboard's hotkey mode on connect and act on its media keys (brightness, panel toggle, kb backlight). Mainline hid-asus lacks this device, so this daemon stands in for it.";
    };

    batteryLimit = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 20 100);
      default = null;
      description = "Battery charge-limit percentage re-applied at login (the sysfs threshold resets on reboot).";
    };
  };

  config = lib.mkIf cfg.enable {
    home.sessionPath = [ "${cfg.repoPath}/duo/bin" ];

    systemd.user.services =
      lib.optionalAttrs cfg.watchDisplays {
        duo-watch-displays = watcher "watch-displays" "toggle bottom panel on keyboard dock/undock";
      }
      // lib.optionalAttrs cfg.watchBacklight {
        duo-watch-backlight = watcher "watch-backlight" "sync bottom panel backlight to top";
      }
      // lib.optionalAttrs cfg.watchRotation {
        duo-watch-rotation = watcher "watch-rotation" "follow accelerometer orientation (experimental)";
      }
      // lib.optionalAttrs cfg.watchFn {
        duo-watch-fn = watcher "watch-fn" "init keyboard hotkey mode + act on media keys";
      }
      // lib.optionalAttrs (cfg.batteryLimit != null) {
        duo-bat-limit = {
          Unit.Description = "zenduo: apply battery charge limit";
          Service = {
            Type = "oneshot";
            ExecStart = "${cfg.repoPath}/duo/bin/duo bat-limit ${toString cfg.batteryLimit}";
          };
          Install.WantedBy = [ "default.target" ];
        };
      };
  };
}
