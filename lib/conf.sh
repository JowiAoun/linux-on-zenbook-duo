#!/usr/bin/env bash
# lib/conf.sh — read ~/.config/zenduo/zenduo.conf. Sourced by bin/duo.
#
# The file is `KEY=value` lines, `#` comments, nothing else. It is parsed, not
# sourced: a config file must never be able to run code, and a value is only
# accepted if it is made of [A-Za-z0-9_./:@,-] — anything else reads as unset
# so a stray quote or space cannot smuggle a shell word into a daemon.
#
#   conf_path            the file that is (or would be) read
#   conf_get KEY [dflt]  the value, or the default, or empty
#   conf_set KEY VALUE   rewrite (or append) KEY in the file, creating it from
#                        the shipped example when absent
#   conf_defaults        print the built-in defaults as KEY=value lines
#   nix_managed PATH     true when PATH is a symlink into the Nix store, i.e.
#                        home-manager owns it (the config, or a duo-* unit)

conf_path() { echo "${ZENDUO_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/zenduo/zenduo.conf}"; }

# One hop of readlink, not -f: /nix/store need not exist on the machine that
# runs the tests, and home-manager's first hop already lands in the store.
nix_managed() { # <path>
  [ -L "$1" ] || return 1
  case "$(readlink "$1" 2>/dev/null)" in /nix/store/*) return 0 ;; *) return 1 ;; esac
}

# Built-in defaults. Keep in step with config/zenduo.conf.example.
conf_defaults() {
  cat <<'DEFAULTS'
APPLY_METHOD=temporary
BATTERY_LIMIT=
BACKLIGHT_SOURCE=intel_backlight
BACKLIGHT_TARGET=
KB_BACKLIGHT_RESTORE=1
DOCK_POLICY=1
REMEMBER_LAYOUT=1
LOGIN_SCREEN_LAYOUT=1
DEFAULTS
}

conf_default_of() { # <KEY>
  conf_defaults | sed -nE "s/^$1=(.*)$/\1/p" | head -n1
}

conf_get() { # <KEY> [default]
  local key="$1" dflt="${2-}" f v
  f="$(conf_path)"
  if [ -r "$f" ]; then
    v="$(sed -nE "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*([^#]*).*$/\1/p" "$f" | head -n1 | sed -E 's/[[:space:]]+$//')"
    v="${v%\"}"; v="${v#\"}"
    if [ -n "$v" ]; then
      case "$v" in
        *[!A-Za-z0-9_./:@,-]*) printf 'zenduo: ignoring %s in %s: value contains characters that are not allowed\n' "$key" "$f" >&2; v="" ;;
      esac
    fi
    if [ -n "$v" ]; then
      echo "$v"
      return 0
    fi
  fi
  if [ -n "$dflt" ]; then
    echo "$dflt"
  else
    conf_default_of "$key"
  fi
}

conf_set() { # <KEY> <VALUE>
  local key="$1" val="$2" f dir
  case "$val" in
    *[!A-Za-z0-9_./:@,-]*) echo "zenduo: refusing to write $key: value may only contain [A-Za-z0-9_./:@,-]" >&2; return 1 ;;
  esac
  f="$(conf_path)"
  dir="$(dirname "$f")"
  mkdir -p "$dir"
  if [ -L "$f" ] && [ ! -w "$f" ]; then
    echo "zenduo: $f is a read-only symlink (managed by home-manager?) — change the setting there instead" >&2
    return 1
  fi
  if [ ! -f "$f" ]; then
    if [ -n "${ZENDUO_CONF_EXAMPLE:-}" ] && [ -r "$ZENDUO_CONF_EXAMPLE" ]; then
      cp "$ZENDUO_CONF_EXAMPLE" "$f"
    else
      conf_defaults > "$f"
    fi
  fi
  if grep -qE "^[[:space:]]*#?[[:space:]]*${key}[[:space:]]*=" "$f"; then
    # Replace the first (possibly commented-out) occurrence in place, so the
    # explanatory comment above it keeps describing the setting.
    sed -i -E "0,/^[[:space:]]*#?[[:space:]]*${key}[[:space:]]*=.*/s//${key}=${val}/" "$f"
  else
    printf '%s=%s\n' "$key" "$val" >> "$f"
  fi
}
