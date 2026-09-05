#!/usr/bin/env bash
# tests/test-lib.sh — behavioural tests for system/lib.sh and lib/conf.sh.
#
# Run with `make test`, or `sudo make test` to include the tests that need root
# (install_conf writes root-owned files). CI runs it under sudo so nothing is
# skipped. Deliberately no test framework: this has to run on a fresh machine
# before anything is installed, so bash and coreutils are the whole dependency
# list.
#
# Why it exists: `cmd | grep -q` under pipefail returns 141 on a big enough
# writer, so a successful match reads as a failure. shellcheck passes on it,
# the script exits 0 and logs a plausible reason. That bug shipped twice in the
# repo this one was split from. These are tests of the helpers it lived in.

set -uo pipefail   # NOT -e: an assertion failure must be recorded, not fatal

cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck source=../system/lib.sh
source ./system/lib.sh
# shellcheck source=../lib/conf.sh
source ./lib/conf.sh
set +e

PASSED=0 FAILED=0 SKIPPED=0
ok()   { PASSED=$((PASSED + 1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
no()   { FAILED=$((FAILED + 1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
skip() { SKIPPED=$((SKIPPED + 1)); printf '  \033[33m–\033[0m %s (skipped: %s)\n' "$1" "$2"; }
group(){ printf '\n\033[1m%s\033[0m\n' "$1"; }
is()   { if [ "$2" = "$3" ]; then ok "$1"; else no "$1 — want '$3', got '$2'"; fi; }
succeeds() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else no "$name — expected exit 0, got $?"; fi; }
fails()    { local name="$1"; shift; if "$@" >/dev/null 2>&1; then no "$name — expected non-zero, got 0"; else ok "$name"; fi; }

# ── out_matches ──────────────────────────────────────────────────────────────
group "out_matches"
succeeds "matches a plain substring"            out_matches $'alpha\nbeta\ngamma' beta
fails    "reports no match"                     out_matches $'alpha\nbeta' delta
succeeds "-E extended regex"                    out_matches $'  Candidate: 1.1.2-3' -E '^[[:space:]]+Candidate: [^([:space:]]'
fails    "-E rejects Candidate: (none)"         out_matches $'  Candidate: (none)' -E '^[[:space:]]+Candidate: [^([:space:]]'
succeeds "-x whole-line match"                  out_matches $'docker\nsudo' -x docker
fails    "empty text never matches"             out_matches '' -E '.'

group "out_matches — the pipefail/SIGPIPE regression"
big="$(seq 1 200000)"
succeeds "matches line 1 of 200k without SIGPIPE" out_matches "$big" -E '^1$'
succeeds "matches the last line too"              out_matches "$big" -E '^200000$'
naive_pipeline_status() { ( set -euo pipefail; printf '%s\n' "$big" | grep -qE '^1$' ); echo $?; }
naive="$(naive_pipeline_status)"
if [ "$naive" = 141 ]; then ok "the naive 'printf | grep -q' pipeline still returns 141 (why this helper exists)"
elif [ "$naive" = 0 ]; then skip "naive pipeline returns 141" "this bash/grep did not raise SIGPIPE; helper is still correct"
else no "naive pipeline returned $naive — expected 141 or 0"; fi

# ── feature_on / hardware ────────────────────────────────────────────────────
group "feature_on"
unset ZENDUO_TESTFEAT
succeeds "unset + default 1 is on"   feature_on TESTFEAT 1
fails    "unset + default 0 is off"  feature_on TESTFEAT 0
ZENDUO_TESTFEAT=1; succeeds "=1 is on"                    feature_on TESTFEAT 0
ZENDUO_TESTFEAT=0; fails    "=0 is off even with default 1" feature_on TESTFEAT 1
# shellcheck disable=SC2034  # read by feature_on through indirect expansion
ZENDUO_TESTFEAT=yes; fails  "anything but 1 is off"       feature_on TESTFEAT 1
unset ZENDUO_TESTFEAT

group "is_duo_hardware"
dmi="$(mktemp)"
printf 'Zenbook Duo UX8406MA_UX8406MA\n' > "$dmi"
ZENDUO_DMI_PRODUCT="$dmi" succeeds "matches the UX8406MA" is_duo_hardware
printf 'ROG Zephyrus G14\n' > "$dmi"
ZENDUO_DMI_PRODUCT="$dmi" fails "rejects another ASUS" is_duo_hardware
ZENDUO_DMI_PRODUCT=/nonexistent fails "rejects a machine with no DMI" is_duo_hardware
rm -f "$dmi"

# ── GRUB helpers on a scratch file ───────────────────────────────────────────
group "ensure_grub_param / remove_grub_param"
GRUB_FILE="$(mktemp)"
printf 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n' > "$GRUB_FILE"
# shellcheck disable=SC2034  # both are read inside lib.sh
DRY_RUN=0 GRUB_CHANGED=0
ensure_grub_param i915.enable_psr=0 >/dev/null
is "adds the param"            "$(grep GRUB_CMDLINE_LINUX_DEFAULT "$GRUB_FILE")" 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash i915.enable_psr=0"'
is "flags the change"          "$GRUB_CHANGED" 1
GRUB_CHANGED=0
ensure_grub_param i915.enable_psr=0 >/dev/null
is "does not add it twice"     "$(grep -c 'enable_psr' "$GRUB_FILE")" 1
is "no change flagged when present" "$GRUB_CHANGED" 0
remove_grub_param i915.enable_psr=0 >/dev/null
is "removes the param"         "$(grep GRUB_CMDLINE_LINUX_DEFAULT "$GRUB_FILE")" 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"'
printf 'GRUB_CMDLINE_LINUX_DEFAULT=""\n' > "$GRUB_FILE"
ensure_grub_param i915.enable_psr=0 >/dev/null
is "adds to an empty cmdline without a leading space" "$(cat "$GRUB_FILE")" 'GRUB_CMDLINE_LINUX_DEFAULT="i915.enable_psr=0"'
rm -f "$GRUB_FILE"
GRUB_FILE=/etc/default/grub

# ── ensure_line ──────────────────────────────────────────────────────────────
group "ensure_line"
tmpf="$(mktemp)"
printf 'existing\n' > "$tmpf"
ensure_line "$tmpf" 'added' >/dev/null 2>&1
is "appends a missing line"        "$(grep -c '^added$' "$tmpf")" "1"
ensure_line "$tmpf" 'added' >/dev/null 2>&1
is "does not append it twice"      "$(grep -c '^added$' "$tmpf")" "1"
rm -f "$tmpf"

# ── install_conf ─────────────────────────────────────────────────────────────
group "install_conf"
if [ "$(id -u)" != 0 ]; then
  skip "install_conf writes a new file"    "needs root (run: sudo make test)"
  skip "install_conf is idempotent"        "needs root"
  skip "install_conf honours DRY_RUN"      "needs root"
else
  confdir="$(mktemp -d)"
  target="$confdir/nested/dir/test.conf"
  DRY_RUN=0
  if install_conf "$target" "first" >/dev/null 2>&1; then ok "install_conf writes a new file (returns 0 = changed)"; else no "install_conf writes a new file"; fi
  is "content is correct" "$(cat "$target" 2>/dev/null)" "first"
  if install_conf "$target" "first" >/dev/null 2>&1; then no "install_conf is idempotent (should return 1)"; else ok "install_conf is idempotent (returns 1 = unchanged)"; fi
  if install_conf "$target" "second" >/dev/null 2>&1; then ok "install_conf rewrites when content differs"; else no "install_conf rewrites when content differs"; fi
  DRY_RUN=1
  install_conf "$confdir/dry.conf" "x" >/dev/null 2>&1
  is "DRY_RUN writes nothing" "$([ -e "$confdir/dry.conf" ] && echo created || echo absent)" "absent"
  # shellcheck disable=SC2034  # read by install_conf inside lib.sh
  DRY_RUN=0
  rm -rf "$confdir"
fi

# ── conf.sh ──────────────────────────────────────────────────────────────────
group "conf_get / conf_set (lib/conf.sh)"
ZENDUO_CONF="$(mktemp -d)/zenduo.conf"
export ZENDUO_CONF
is "missing file -> built-in default"     "$(conf_get APPLY_METHOD)" "temporary"
is "missing file -> empty default"        "$(conf_get BATTERY_LIMIT)" ""
is "explicit default wins over built-in"  "$(conf_get BATTERY_LIMIT 80)" "80"
cat > "$ZENDUO_CONF" <<'CONF'
# a comment
APPLY_METHOD=persistent   # trailing comment
BATTERY_LIMIT = 75
BACKLIGHT_TARGET="card1-eDP-2-backlight"
DOCK_POLICY=0; rm -rf /
CONF
is "reads a plain value"                  "$(conf_get APPLY_METHOD)" "persistent"
is "tolerates spaces around ="            "$(conf_get BATTERY_LIMIT)" "75"
is "strips surrounding quotes"            "$(conf_get BACKLIGHT_TARGET)" "card1-eDP-2-backlight"
is "rejects a value with shell metacharacters (falls back to default)" "$(conf_get DOCK_POLICY 2>/dev/null)" "1"
conf_set BATTERY_LIMIT 80
is "conf_set rewrites in place"           "$(conf_get BATTERY_LIMIT)" "80"
is "conf_set keeps one line for the key"  "$(grep -c '^BATTERY_LIMIT' "$ZENDUO_CONF")" "1"
conf_set NEW_KEY value
is "conf_set appends an unknown key"      "$(conf_get NEW_KEY)" "value"
fails "conf_set refuses metacharacters"   conf_set APPLY_METHOD 'x;y'
rm -f "$ZENDUO_CONF"
conf_set APPLY_METHOD temporary
is "conf_set creates the file from defaults" "$(grep -c '^APPLY_METHOD=temporary' "$ZENDUO_CONF")" "1"
rm -rf "$(dirname "$ZENDUO_CONF")"

# ── summary ──────────────────────────────────────────────────────────────────
printf '\n%s\n' "────────────────────────────────────────"
printf '%d passed, %d failed, %d skipped\n' "$PASSED" "$FAILED" "$SKIPPED"
[ "$FAILED" -eq 0 ] || exit 1
printf '\033[32mall good\033[0m\n'
