# home-manager module: the user half of linux-on-zenbook-duo, declaratively.
#
#   inputs.zenbook-duo.url = "github:JowiAoun/linux-on-zenbook-duo";
#   ...
#   imports = [ inputs.zenbook-duo.homeManagerModules.default ];
#   zenduo = { enable = true; batteryLimit = 80; speakerDsp = true; };
#
# The ROOT half (udev, sudoers, the helper, the touchpad quirk, GRUB) is not
# something home-manager can do: run `sudo ./install.sh --system` from a
# checkout once (see nix/examples/host.nix for how a dotfiles repo wires both).
#
# This generates the same duo-* user units ./install.sh installs, and writes
# ~/.config/zenduo/zenduo.conf so `duo` on the command line agrees with them.
{ config, lib, pkgs, ... }:

let
  cfg = config.zenduo;

  bool01 = b: if b then "1" else "0";

  # The daemons read their knobs from the environment; the unit sets exactly
  # the values the module was given, so systemd never has to guess from a file.
  # ZENDUO_APPLY_METHOD in particular must agree between daemon and shell — a
  # daemon writing monitors.xml while a hand-run `duo both` only applied
  # temporarily would have Mutter undo the manual choice on the next resume.
  daemonEnv = [
    "ZENDUO_APPLY_METHOD=${cfg.applyMethod}"
    "ZENDUO_DOCK_POLICY=${bool01 cfg.dockPolicy}"
    "ZENDUO_KB_BACKLIGHT_RESTORE=${bool01 cfg.kbBacklightRestore}"
  ];

  watcher = sub: description: {
    Unit = {
      Description = "zenduo: ${description}";
      PartOf = [ "graphical-session.target" ];
      After = [ "graphical-session.target" ];
    };
    Service = {
      ExecStart = "${cfg.duoBin} ${sub}";
      Environment = daemonEnv;
      # Everything zenduo logs is under one journal identifier, so `duo log`
      # shows the daemons' output too (checked by the flake's hm-units check).
      SyslogIdentifier = "zenduo";
      Restart = "on-failure";
      RestartSec = 3;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };

  confText = ''
    # Written by the zenduo home-manager module — change the zenduo.* options
    # there, not here (this file is a read-only symlink into the Nix store).
    APPLY_METHOD=${cfg.applyMethod}
    BATTERY_LIMIT=${lib.optionalString (cfg.batteryLimit != null) (toString cfg.batteryLimit)}
    BACKLIGHT_SOURCE=${cfg.backlightSource}
    BACKLIGHT_TARGET=${cfg.backlightTarget}
    KB_BACKLIGHT_RESTORE=${bool01 cfg.kbBacklightRestore}
    DOCK_POLICY=${bool01 cfg.dockPolicy}
  '';
in
{
  imports = [ ./touchpad.nix ./audio.nix ];

  options.zenduo = {
    enable = lib.mkEnableOption "the zenduo user daemons for the ASUS Zenbook Duo (2024) UX8406MA";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The zenduo package the units run, unless repoPath is set.";
    };

    repoPath = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/home/me/p/linux-on-zenbook-duo";
      description = ''
        Absolute path of a checkout to run the daemons FROM instead of the
        package — for developing the tooling: edits are live after a
        `systemctl --user restart duo-*`. The checkout must have python3-gi
        available to /usr/bin/python3 (or DUO_PYGI set), which is what
        `sudo ./install.sh --system` arranges.
      '';
    };

    duoBin = lib.mkOption {
      type = lib.types.str;
      internal = true;
      readOnly = true;
      default = if cfg.repoPath != null then "${cfg.repoPath}/bin/duo" else "${cfg.package}/bin/duo";
      description = "The duo executable the units use (derived).";
    };

    writeConfig = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Write ~/.config/zenduo/zenduo.conf from these options, so `duo status`,
        `duo bat-limit` and friends on the command line use the same knobs as
        the units. Off if you would rather hand-edit that file.
      '';
    };

    watchDisplays = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Keep the bottom panel in step with the keyboard: off while docked (the
        keyboard is lying on it), back on when it comes off. The daemon
        re-checks after resume, monitor hotplug and any other Mutter
        reconfiguration, not just on dock/undock, so the bottom panel cannot
        stay lit under a docked keyboard. It governs that one panel only — the
        top panel, external monitors and their arrangement stay yours, so Win+P
        layouts like "External Only" survive; undocking on external-only leaves
        the bottom panel dark rather than lighting a screen you are not using.
        `duo apply-displays` enforces the policy once by hand.
      '';
    };

    dockPolicy = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enforce the dock policy at all. Off keeps the daemon running but makes it watch without acting (DOCK_POLICY=0).";
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
        resume buries you in confirmation dialogs.
      '';
    };

    watchFn = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Init the keyboard's hotkey mode on connect and act on its media keys (brightness, panel toggle, kb backlight). Mainline hid-asus lacks this device, so this daemon stands in for it.";
    };

    kbBacklightRestore = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Put the keyboard backlight back to its remembered level after the keyboard re-enumerates (dock, undock, resume all blank it in hardware).";
    };

    watchBacklight = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Keep the bottom panel backlight synced to the top panel continuously. Off by default: the brightness keys already mirror the level through watchFn.";
    };

    backlightSource = lib.mkOption {
      type = lib.types.str;
      default = "intel_backlight";
      description = "Backlight device the brightness is copied FROM.";
    };

    backlightTarget = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Backlight device the brightness is copied TO. Empty = the eDP-2 DRM backlight, auto-detected.";
    };

    watchRotation = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Experimental rotation watcher (logs only for now).";
    };

    batteryLimit = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 20 100);
      default = null;
      example = 80;
      description = "Battery charge-limit percentage re-applied at login (the sysfs threshold resets on reboot).";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.repoPath == null) cfg.package;
    home.sessionPath = lib.optional (cfg.repoPath != null) "${cfg.repoPath}/bin";

    # So a hand-run `duo top/bottom/both/toggle` applies the same way the
    # daemons do (systemd user services do not see the shell's environment,
    # which is why the units carry it too).
    home.sessionVariables.ZENDUO_APPLY_METHOD = cfg.applyMethod;

    xdg.configFile."zenduo/zenduo.conf" = lib.mkIf cfg.writeConfig { text = confText; };

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
            ExecStart = "${cfg.duoBin} bat-limit ${toString cfg.batteryLimit}";
            SyslogIdentifier = "zenduo";
          };
          Install.WantedBy = [ "default.target" ];
        };
      };
  };
}
