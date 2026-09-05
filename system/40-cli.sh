#!/usr/bin/env bash
# 40-cli.sh — put the `duo` command on the system.
#
# Layout: $PREFIX/lib/zenduo/{bin,lib,helper,config,presets,VERSION} plus the symlink
# $PREFIX/bin/duo -> $PREFIX/lib/zenduo/bin/duo. A system-wide `duo` works from
# any shell AND under sudo (sudo resets PATH to secure_path, which includes
# /usr/local/bin but never the user's home).
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
BINLINK="$ZENDUO_PREFIX/bin/duo"

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

if [ "$(readlink -f "$BINLINK" 2>/dev/null || true)" = "$(readlink -f "$LIBDIR/bin/duo" 2>/dev/null || true)" ] && [ -e "$BINLINK" ]; then
  log "duo symlink up to date: $BINLINK"
else
  log "linking $BINLINK -> $LIBDIR/bin/duo"
  run install -d -o root -g root -m 0755 "$ZENDUO_PREFIX/bin"
  run ln -sfn "$LIBDIR/bin/duo" "$BINLINK"
fi
