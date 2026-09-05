# The `duo` CLI and its daemons as a Nix package. The home-manager module uses
# it by default; `nix run github:JowiAoun/linux-on-zenbook-duo -- doctor` works
# on any machine with Nix.
#
# What the wrapper does, and why:
#   DUO_PYGI   the display code talks to Mutter over D-Bus through PyGObject.
#              On Ubuntu `duo` pins /usr/bin/python3 for that (apt python3-gi);
#              in the store we ship a python that has it instead.
#   PATH       the few non-systemd tools the scripts call (gdbus, dconf,
#              inotifywait, lspci, lsusb, logger). systemctl/journalctl are the
#              host's and are deliberately not wrapped.
{ lib, stdenvNoCC, makeWrapper, python3, glib, gobject-introspection, dconf
, inotify-tools, pciutils, usbutils, util-linux }:

let
  pyGi = python3.withPackages (ps: [ ps.pygobject3 ]);
in
stdenvNoCC.mkDerivation {
  pname = "zenduo";
  version = lib.fileContents ../VERSION;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../bin ../lib ../helper ../config ../presets ../VERSION
    ];
  };

  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib/zenduo $out/bin
    cp -r bin lib helper config presets VERSION $out/lib/zenduo/
    chmod +x $out/lib/zenduo/bin/duo $out/lib/zenduo/helper/zenduo-helper
    makeWrapper $out/lib/zenduo/bin/duo $out/bin/duo \
      --set-default DUO_PYGI ${pyGi}/bin/python3 \
      --prefix GI_TYPELIB_PATH : ${lib.makeSearchPath "lib/girepository-1.0" [ glib gobject-introspection ]} \
      --prefix PATH : ${lib.makeBinPath [ python3 glib dconf inotify-tools pciutils usbutils util-linux ]}
    runHook postInstall
  '';

  meta = with lib; {
    description = "Dual-screen, keyboard, audio and power support for the ASUS Zenbook Duo (2024) UX8406MA";
    homepage = "https://github.com/JowiAoun/linux-on-zenbook-duo";
    license = licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "duo";
  };
}
