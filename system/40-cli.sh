#!/usr/bin/env bash
# 40-cli.sh — put the `duo` and `duo-cli` commands on the system.
#
# Layout: $PREFIX/lib/zenduo/{bin,lib,helper,config,presets,VERSION} plus the
# symlinks $PREFIX/bin/duo and $PREFIX/bin/duo-cli into $PREFIX/lib/zenduo/bin.
# A system-wide `duo` works from any shell AND under sudo (sudo resets PATH to
# secure_path, which includes /usr/local/bin but never the user's home).
#
# Two modes:
#   default   COPY the tree. Survives the checkout moving or being deleted.
#   --dev     SYMLINK $PREFIX/lib/zenduo to the checkout, so edits are live
#             (the daemons still need `systemctl --user restart duo-*` to pick
#             them up — a running python process has already loaded its code).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

require_root

LIBDIR="$ZENDUO_PREFIX/lib/zenduo"

if [ "${ZENDUO_DEV:-0}" = 1 ]; then
  if [ "$(readlink -f "$LIBDIR" 2>/dev/null || true)" = "$(readlink -f "$ZENDUO_SRC")" ]; then
    log "dev mode: $LIBDIR already points at $ZENDUO_SRC"
  else
    log "dev mode: linking $LIBDIR -> $ZENDUO_SRC"
    if [ -d "$LIBDIR" ] && [ ! -L "$LIBDIR" ]; then
      run rm -rf "$LIBDIR"
    fi
    run install -d -o root -g root -m 0755 "$ZENDUO_PREFIX/lib"
    run ln -sfn "$ZENDUO_SRC" "$LIBDIR"
  fi
else
  # Copy mode. Compare before copying so a re-run reports "up to date".
  same=1
  for part in bin lib helper config presets VERSION; do
    if ! diff -rq --exclude=__pycache__ "$ZENDUO_SRC/$part" "$LIBDIR/$part" >/dev/null 2>&1; then
      same=0
      break
    fi
  done
  if [ -L "$LIBDIR" ]; then
    same=0  # switching from dev mode to a real copy
  fi
  if [ "$same" = 1 ]; then
    log "CLI up to date: $LIBDIR"
  else
    log "installing the CLI into $LIBDIR"
    if [ "$DRY_RUN" = 1 ]; then
      log "DRY RUN: would copy bin/ lib/ helper/ VERSION to $LIBDIR"
      mark_change
    else
      rm -rf "$LIBDIR"
      install -d -o root -g root -m 0755 "$LIBDIR" "$LIBDIR/bin" "$LIBDIR/lib" "$LIBDIR/helper"
      install -o root -g root -m 0755 "$ZENDUO_SRC/bin/duo" "$LIBDIR/bin/duo"
      install -o root -g root -m 0755 "$ZENDUO_SRC/bin/duo-cli" "$LIBDIR/bin/duo-cli"
      install -o root -g root -m 0755 "$ZENDUO_SRC/helper/zenduo-helper" "$LIBDIR/helper/zenduo-helper"
      for f in "$ZENDUO_SRC"/lib/*.py "$ZENDUO_SRC"/lib/*.sh; do
        [ -e "$f" ] || continue
        install -o root -g root -m 0644 "$f" "$LIBDIR/lib/$(basename "$f")"
      done
      install -o root -g root -m 0644 "$ZENDUO_SRC/VERSION" "$LIBDIR/VERSION"
      install -d -o root -g root -m 0755 "$LIBDIR/config" "$LIBDIR/presets/easyeffects"
      install -o root -g root -m 0644 "$ZENDUO_SRC/config/zenduo.conf.example" "$LIBDIR/config/zenduo.conf.example"
      install -o root -g root -m 0644 "$ZENDUO_SRC/presets/easyeffects/duo-speakers.json" "$LIBDIR/presets/easyeffects/duo-speakers.json"
      mark_change
    fi
  fi
fi

for name in duo duo-cli; do
  binlink="$ZENDUO_PREFIX/bin/$name"
  if [ "$(readlink -f "$binlink" 2>/dev/null || true)" = "$(readlink -f "$LIBDIR/bin/$name" 2>/dev/null || true)" ] && [ -e "$binlink" ]; then
    log "$name symlink up to date: $binlink"
  else
    log "linking $binlink -> $LIBDIR/bin/$name"
    run install -d -o root -g root -m 0755 "$ZENDUO_PREFIX/bin"
    run ln -sfn "$LIBDIR/bin/$name" "$binlink"
  fi
done
