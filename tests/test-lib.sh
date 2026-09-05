#!/usr/bin/env bash
# tests/test-lib.sh — behavioural tests for system/lib.sh, lib/conf.sh and
# the argument plumbing of install.sh / uninstall.sh.
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
# What the naive pipeline returns depends on the parent's SIGPIPE disposition:
#   141  printf was killed by SIGPIPE (a terminal, a plain shell)
#     1  SIGPIPE is ignored, so the write fails with EPIPE and printf exits 1.
#        GitHub's runner starts every job that way (measured 2026-09-05: the
#        first two CI runs on main failed here with "returned 1").
# Both are the hazard — a successful match reported as failure. Only 0 means
# this bash/grep never hit it, which makes the helper merely unnecessary here.
case "$naive" in
  141) ok "the naive 'printf | grep -q' pipeline returns 141 — SIGPIPE (why this helper exists)" ;;
  1)   ok "the naive 'printf | grep -q' pipeline returns 1 — EPIPE with SIGPIPE ignored (why this helper exists)" ;;
  0)   skip "naive pipeline fails under pipefail" "this bash/grep did not hit SIGPIPE or EPIPE; helper is still correct" ;;
  *)   no "naive pipeline returned $naive — expected 141, 1 or 0" ;;
esac

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

# ── nix_managed ──────────────────────────────────────────────────────────────
group "nix_managed"
nm_dir="$(mktemp -d)"
touch "$nm_dir/plain.service"
ln -s /nix/store/0000000000000000000000000000000-home-manager-files/.config/systemd/user/duo-watch-fn.service "$nm_dir/hm.service"
ln -s "$nm_dir/plain.service" "$nm_dir/local-link.service"
fails    "a regular file is not managed"            nix_managed "$nm_dir/plain.service"
succeeds "a symlink into /nix/store is managed"     nix_managed "$nm_dir/hm.service"
fails    "a symlink elsewhere is not managed"       nix_managed "$nm_dir/local-link.service"
fails    "a missing path is not managed"            nix_managed "$nm_dir/none.service"
rm -rf "$nm_dir"

# ── systemd unit templates ────────────────────────────────────────────────────
# Without SyslogIdentifier the daemons' stdout is filed under the executable's
# name ("duo") and `duo log` (-t zenduo) showed none of it (2026-09-05: 600
# watch-fn lines under "duo", zero under "zenduo"). The home-manager module is
# covered by the flake's hm-units check.
group "systemd unit templates"
for f in systemd/user/duo-*.service; do
  is "$(basename "$f") logs under the zenduo identifier" "$(grep -c '^SyslogIdentifier=zenduo$' "$f")" 1
done

# ── install.sh: flags must survive the runuser round trip ────────────────────
# As root, install.sh re-runs itself under runuser for the user half. Its
# parser starts from the defaults, so the flags have to travel as arguments:
# 2026-09-05 `sudo ./install.sh --dry-run` ran the user half FOR REAL and
# --battery-limit / --speaker-dsp / --prefix never reached it.
group "install.sh argument plumbing"
plan()  { ZENDUO_INSTALL_PLAN=1 ./install.sh "$@" 2>/dev/null; }
field() { printf '%s\n' "$1" | sed -n "s/^$2=//p"; }
p="$(plan --dry-run --dev --prefix /opt/z --no-watch-fn --watch-rotation --battery-limit 80 --apply-method persistent --speaker-dsp --user bob)"
is "--user NAME names the target account"     "$(field "$p" TARGET_USER)" bob
is "--user NAME keeps both halves"            "$(field "$p" DO_SYSTEM),$(field "$p" DO_USER)" "1,1"
is "--dry-run is parsed"                      "$(field "$p" DRY_RUN)" 1
is "system flags exclude the user-only ones"  "$(field "$p" SYSTEM_FLAGS)" "--dry-run --dev --prefix /opt/z"
fwd="$(field "$p" USER_FLAGS)"
is "every user-half flag is forwarded"        "$fwd" "--dry-run --prefix /opt/z --no-watch-fn --watch-rotation --battery-limit 80 --apply-method persistent --speaker-dsp"
# The round trip the root path performs: re-parse exactly what it forwards.
# shellcheck disable=SC2086  # word-splitting the forwarded flags is the point
c="$(plan $fwd --user)"
is "child: user half only"                    "$(field "$c" DO_SYSTEM),$(field "$c" DO_USER)" "0,1"
is "child: dry run survives"                  "$(field "$c" DRY_RUN)" 1
is "child: --prefix survives"                 "$(field "$c" PREFIX)" /opt/z
is "child: --no-watch-fn survives"            "$(field "$c" WATCH_FN)" 0
is "child: --watch-rotation survives"         "$(field "$c" WATCH_ROTATION)" 1
is "child: --battery-limit survives"          "$(field "$c" BATTERY_LIMIT)" 80
is "child: --apply-method survives"           "$(field "$c" APPLY_METHOD)" persistent
is "child: --speaker-dsp survives"            "$(field "$c" SPEAKER_DSP)" 1
is "no flags forwards nothing"                "$(field "$(plan)" USER_FLAGS)" ""
is "--user alone means the user half only"    "$(field "$(plan --user)" DO_SYSTEM)" 0
is "--system alone skips the user half"       "$(field "$(plan --system)" DO_USER)" 0
fails "--battery-limit out of range is refused" plan --battery-limit 10
fails "--apply-method never is refused"        plan --apply-method never
fails "an unknown flag is refused"             plan --bogus
succeeds "--help exits 0"                      ./install.sh --help

group "uninstall.sh argument plumbing"
is "--prefix without a value is a usage error (64), not an unbound variable" "$(./uninstall.sh --prefix >/dev/null 2>&1; echo $?)" 64
is "an unknown flag is a usage error (64)"     "$(./uninstall.sh --bogus >/dev/null 2>&1; echo $?)" 64
succeeds "--help exits 0"                      ./uninstall.sh --help

# ── summary ──────────────────────────────────────────────────────────────────
printf '\n%s\n' "────────────────────────────────────────"
printf '%d passed, %d failed, %d skipped\n' "$PASSED" "$FAILED" "$SKIPPED"
[ "$FAILED" -eq 0 ] || exit 1
printf '\033[32mall good\033[0m\n'
