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
      # The daemons must agree with the shell about how layouts are applied —
      # a daemon writing monitors.xml while a hand-run `duo both` only applied
      # temporarily would have Mutter undo the manual choice on the next resume.
      Environment = [ "ZENDUO_APPLY_METHOD=${cfg.applyMethod}" ];
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
      description = ''
        Keep the panel layout matching the keyboard: docked -> top panel only,
        undocked -> both. The daemon re-checks after resume, monitor hotplug and
        any other Mutter reconfiguration, not just on dock/undock, so the bottom
        panel cannot stay lit under a docked keyboard. `duo apply-displays`
        enforces it once by hand.
      '';
    };

    applyMethod = lib.mkOption {
      type = lib.types.enum [ "temporary" "persistent" ];
      default = "temporary";
      description = ''
        How layout changes are handed to Mutter. Leave this at "temporary"
        unless you know exactly why you want otherwise.

        "temporary" never touches monitors.xml, so nothing zenduo does survives
        a session restart. The cost is that Mutter re-reads monitors.xml
        whenever it re-detects the connectors — notably on some resumes — which
        lights the bottom panel up under a docked keyboard until the daemon
        corrects it a fraction of a second later.

        "persistent" writes monitors.xml, so Mutter restores the docked layout
        itself and that flash never happens. VERIFIED ON HARDWARE 2026-07-23
        AND REJECTED: gnome-shell treats a persistent ApplyMonitorsConfig as a
        user-initiated change and pops its "Keep display settings?" countdown
        every single time, so a daemon that applies on every dock, undock and
        resume buries you in confirmation dialogs. The brief flash is by far
        the lesser evil. It also outlives zenduo — stop the daemon while docked
        and the bottom panel stays off until `duo both` turns it back on.
      '';
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

    # So a hand-run `duo top/bottom/both/toggle` applies the same way the
    # daemons do (the units set this themselves; systemd user services do not
    # pick up the shell's environment).
    home.sessionVariables.ZENDUO_APPLY_METHOD = cfg.applyMethod;

    systemd.user.services =
      lib.optionalAttrs cfg.watchDisplays {
        duo-watch-displays = watcher "watch-displays" "keep the panel layout matching the keyboard dock state";
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
