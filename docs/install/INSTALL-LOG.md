# ZenDuo install log (as-built)

Dated journal of what **actually happened** during the Ubuntu 24.04.4 dual-boot
install on the UX8406MA, wherever reality diverged from or refined
[PLAN.md](PLAN.md). A future reinstall should read this file alongside the plan
— the plan says what to do, this file says what it really looks like.

## 2026-07-21 — Phase A (Windows prep)

- **A1–A5 completed.** A5 (UTC RTC registry switch) produces an expected
  one-time skew: the clock shows N hours behind until one manual resync.
  `w32tm /resync` alone failed ("no time data") — the working sequence was:
  ```powershell
  net start w32time
  w32tm /config /syncfromflags:manual /manualpeerlist:"time.windows.com,0x9" /update
  net stop w32time; net start w32time
  w32tm /resync /rediscover
  ```
- **Pagefile trap (cost ~an hour):** in the Virtual Memory dialog, selecting
  "No paging file" and clicking OK does **nothing** unless you click **Set**
  first. The defrag event log (`Microsoft-Windows-Defrag`, the "last unmovable
  file" line) is the ground truth for what is actually blocking a shrink.
- **⚠ OPEN ITEM: the Windows pagefile is currently left disabled** (Windows
  refused to auto-recreate it even with `PagingFiles = ?:\pagefile.sys`).
  Harmless for a soon-to-be-retired Windows. If Windows is kept long-term:
  Virtual memory dialog → untick automatic → C: → "System managed size" →
  **Set** → OK → reboot.
- **A7/A8 — the shrink wall (major deviation):** after removing pagefile,
  hibernation, and shadow copies, the shrink limit was **53,046 MB**, capped by
  `\$Mft::$BITMAP` at cluster `0xe104d99` (~921.7 GB mark) — **NTFS core
  metadata that Windows tooling can never move.** Decision (Option B, ratified):
  - Take the ~52 GB and install Ubuntu small: `/boot` 2 GiB + LUKS ≈ 49.8 GiB.
  - Swapfile reduced from 8 GB to **4 GB** (D8 amendment).
  - Consider disabling the `cloud` module initially (multi-GB Nix closures);
    run `nix-collect-garbage -d` habitually.
  - **Endgame:** Windows is expected to be retired soon. The freed ~900 GB sits
    *before* the Ubuntu partitions and cannot simply grow the root; the planned
    path is a **clean full-disk reinstall** via this repo once Windows goes
    (cheap by design), or alternatively a second LUKS volume mounted at /home.
  - The not-taken alternative (documented for completeness): fully decrypt
    BitLocker (`manage-bde -off C:`), then `ntfsresize`/GParted from the live
    session *can* relocate $MFT and shrink to any size; re-encrypt afterward
    (new recovery key!).
- **Install media (A6/A10–A12 as-built):** a single **128 GB USB-C stick**
  replaced the two-stick plan. Ventoy (GPT, Secure Boot support on) carrying:
  the Ubuntu 24.04.4 ISO (SHA256 verified), the **official Windows 11 ISO**
  (replaces the A6 recovery drive — its Repair → Command Prompt provides
  `diskpart`/`bcdboot` for §14.4), and the repo as a folder. USB-C boots
  identically to USB-A on this machine; charger occupies the other TB4 port.

## 2026-07-22 — Phase B (BIOS)

BIOS 312 confirmed; all pages photographed; Secure Boot left ON; VMD setting
recorded, untouched (Advanced Mode → F7 → Advanced tab → "VMD setup menu");
Fast Boot disabled; TPM untouched.

## 2026-07-22 — Phase C (live-USB gate): **GO** ⛔→✅

- **Ventoy + Secure Boot first boot:** shows `Verification failed: (0x1A)
  Security Violation` — **expected**, not a fault. OK → MOK Manager →
  "Enroll key from disk" → `VTOYEFI` partition →
  `ENROLL_THIS_KEY_IN_MOKMANAGER.cer` → Continue → Yes → reboot. One-time.
- Booted the Ubuntu ISO in Ventoy **normal mode**; "Try Ubuntu" reached the
  desktop with **both panels live**.
- **Ventoy data partition is unmountable from its own live session** ("already
  mounted or mount point busy" — Ventoy's device-mapper holds it). Fallback
  that works, given Wi-Fi:
  ```bash
  wget https://github.com/JowiAoun/dome/archive/refs/heads/main.tar.gz
  tar xf main.tar.gz
  bash ~/dome-main/duo/bin/duo doctor | tee ~/doctor-live.txt
  ```
  Remember the live home is RAM — export results (photo/gist) before shutdown.

### doctor results (2026-07-22T04:09Z) — the V-table ground truth

| Finding | Verdict |
|---|---|
| Kernel 6.17.0-14-generic, GNOME Shell 46, Ubuntu 24.04.4 | As planned (V1) |
| Live session ran **X11**, not Wayland | Note: check session type on the installed system; zenduo targets Wayland (D10) but Mutter D-Bus works on both |
| NVMe `nvme0n1` visible; Intel VMD controller present | **V16 resolved** — VMD is a non-issue |
| iGPU 8086:7d55, driver i915; **eDP-1 and eDP-2 both connected+enabled** | **V9 resolved — no i915 second-screen regression on 6.17** |
| Backlight devices: `intel_backlight`, `card1-eDP-2-backlight`, **`asus_screenpad`** | `asus_screenpad` is the likely bottom-panel target for `sync-backlight` (VERIFY-ON-HW) |
| Keyboard 0b05:1b2c on USB; **hid_asus not loaded**; **no native kbd-backlight LED**; hidraw4–9 present | **V8 confirmed on hardware** — HID fallback is the operative path |
| Both ELAN digitizers present (04f3:4259 / 04f3:42ec) | V10 confirmed |
| 3 IIO sensors, iio-sensor-proxy active | Rotation feasible |
| SOF audio card registered | V11 good on 6.17 |
| Wi-Fi enumerates as Meteor Lake PCH CNVi `8086:7e40` | RF module (AX211 vs BE200) not determined from PCI ID alone — works; check `dmesg \| grep iwlwifi` on installed system (V15) |
| `charge_control_end_threshold` present (100) | V12 confirmed — `duo bat-limit` viable |
| **`platform_profile` native: quiet/balanced/performance** | Better than researched — no ACPI patching needed for profiles (§15 item partially moot) |
| `mem_sleep`: `[s2idle] deep` | `deep` unexpectedly listed — worth a Phase I experiment, but s2idle stays default (V13) |

Doctor summary: **13 OK / 1 warning (hid_asus) / 0 failures — gate passed.**
Cosmetic doctor bug found (impossible "55657%" for `asus_screenpad`) — fixed in
the same PR as this log.

### Manual gate checks

- Wi-Fi survives keyboard detach (ping kept flowing) ✅ (V6 confirmed)
- Touch works on both panels ✅
- 5× attach/detach — no crash, no flicker storm ✅ (V14 design vindicated)
- Audio/camera/Fn-key inventory: not formally recorded this session — re-run
  during Phase I acceptance tests.

### Bluetooth keyboard

Keyboard never appeared in scans from the live session — flipping the power
switch alone does **not** advertise the keyboard (research had implied it
would). Two things changed before success: the stale Windows pairing was
removed (Settings → Bluetooth & devices → Remove device), and — the key
discovery — **pairing mode must be forced with an F10 long-press**. (The F10
long-press is likely sufficient on its own, since pairing mode normally
advertises regardless of old bonds — unverified.)

**Exact working sequence (Jay, 2026-07-22):**

1. **Detach the keyboard** — physically slide it off the laptop chassis.
2. **Enable Bluetooth on the keyboard** — slide the physical switch on the
   left side (near the front edge) to on (green marker visible).
3. **Enter pairing mode** — **press and hold `F10` on the detached keyboard
   for 4–5 seconds** until the indicator light flashes blue rapidly.
4. **Pair on Ubuntu** — Settings → Bluetooth → Add/Pair New Device → select
   the keyboard → a PIN appears on the laptop screen → **type the PIN on the
   detached keyboard** and press Enter.

## 2026-07-22 — Phase D (partitioning + install): completed, with amendments

Disk: WD PC SN560 1TB (A14). Findings, in order encountered:

- **The factory layout has FIVE partitions, not four** — an extra hidden
  273 MB fat32 recovery partition sits at the very end as `p5`. The plan's
  "typical ASUS ship state" (p1–p4) was wrong for this unit. Consequences:
  - New partitions were numbered **`p6` (/boot, 2 GiB ext4 `duo-boot`)** and
    **`p7` (root, ~49.8 GiB)** — every §7 command shifts by one.
  - **Trap: `p1` and `p5` are near-identical fat32 twins** (~273 MB each). The
    real ESP is `p1` — flags `boot, esp`, at the *start* of the disk. Never
    pick `p5` in an installer.
- The freed space sits **between `p3` and `p4`**, not at the disk end. Plain
  `parted print` hides gaps — `parted /dev/nvme0n1 print free` shows it.
- **GParted only created the first of two queued partitions** on the first
  Apply. Lesson: after Apply, verify with `lsblk` that *everything* you queued
  exists — and check numbering *before* running any `cryptsetup` command.
  (A `luksFormat` briefly aimed at `p6` during the confusion — zero damage,
  the partition was brand-new and empty; `mkfs.ext4` restored intent.)
- **MAJOR: Ubuntu 24.04.4's desktop installer cannot install into an existing
  LUKS container in manual mode.** It lists the raw `crypto_LUKS` partition
  but never offers the opened `/dev/mapper/*` device as a target, and the
  Change dialog has no unlock. The plan's §7.3 pre-made-LUKS approach is a
  dead end on this installer generation.
  - **Amendment ratified (Plan E): the interim install is unencrypted** —
    `p7` reformatted plain ext4, installed directly. D3 (LUKS root) is
    deferred, not abandoned: it returns at the endgame full-disk reinstall
    (the installer's own whole-disk LUKS flow works fine), or earlier via
    in-place `cryptsetup reencrypt --encrypt` from a live USB (~20 min for
    50 GB) if encryption becomes pressing. The chosen LUKS passphrase stays
    stored for that day.
  - Silver lining: with no crypttab needed, the **§7.6 chroot fix became
    unnecessary** — the installer's stock output boots directly. os-prober
    enablement moves to `make system` (already part of the system layer).
- Installer UI notes: the format checkboxes in the partition list are not
  directly clickable — all editing goes through the per-row **Change** dialog.
  Formatting in-installer is redundant when the filesystems were freshly made
  in the terminal moments before; assigning mount points suffices. The
  installer auto-assigned `p1` → `/boot/efi` (unformatted) correctly.

**Install completed; system boots.** Phase E (system layer, Nix, dual-boot
proof, keyboard re-pair) is next.

## 2026-07-22 — Phase E (first run of the setup pipeline): two bugs found + fixed

First real end-to-end run of `setup.sh` → `install.sh` on the installed OS
surfaced two defects (fixed in the same PR):

- **`install.sh` invoked `sudo make system`, but `make` is not installed on a
  fresh Ubuntu desktop** (it ships in `build-essential`, which the system layer
  itself installs — chicken-and-egg). The first install command failed with
  "make: command not found" before anything ran. **Fix:** `install.sh` now calls
  `sudo bash system/run.sh --host <profile>` directly; `make system` remains a
  convenience alias for later interactive re-runs.
- **`setup.sh` used `exec ./install.sh`**, so when that command failed under
  `set -e`, the shell was replaced-then-gone and the terminal window closed with
  no message ("pressed OK, window just closed"). **Fix:** `setup.sh` runs the
  installer as a child process, tees output to `~/dome-install.log`, and prints
  the last lines on failure — the window survives and errors are visible.
- Also hardened: `install.sh` primes sudo up front with a clear banner, re-sources
  the Nix profile so home-manager runs in the same shell, and prints phase
  banners so progress is legible.

Config written by setup was correct (host=zenbook-duo, cloud off, ai on) — only
the install invocation was broken. Re-run after pulling the fix.

### Round 2 (same day): system layer + Nix green; two more defects at the end

The re-run proved the pipeline: preflight → snapshot → apt → kernels → GRUB
(all idempotent, "already present/set" on second pass) → Nix → home-manager.
Two new failures, both fixed:

- **Timeshift picked `/boot` as its snapshot destination.** `timeshift
  --create` in first-run mode auto-selects a device; on this disk it chose the
  2 GiB `p6` (/boot) and hit ENOSPC (it cleaned up its partial snapshot
  itself). **Fix:** `90-timeshift.sh` now passes
  `--snapshot-device "$(findmnt -n -o SOURCE /)" --scripted`, pinning
  snapshots to the root filesystem. **Post-mortem check on the machine:**
  `df -h /boot` and remove a stray `timeshift/` directory from /boot if one
  remains.
- **`vscode-extensions.postman.postman-for-vscode` is undefined in the pinned
  nixpkgs** (Dec 2025). The line was latent-broken forever but unreachable:
  WSL sets `programs.vscode.enable = !isWSL` → off, and Codespaces never
  enabled node. The Duo is the first host with VS Code on — and home-manager's
  vscode module forces every module's extension list **even when that module
  is disabled** (`node = false` does not protect you). Removed the extension.
  **Lesson recorded:** a bad `vscode-extensions.*` attr anywhere breaks every
  vscode-enabled host; container-side validation against mirror inputs can
  miss pin-specific removals — the laptop run is the only true test of the
  lock file.

### Round 3: Timeshift snapshot made opt-in

Even pinned to the root device (round 2 fix), `timeshift --create` sat at
`0.00% complete` — a full rsync of the ~15 GB rootfs onto the same ~50 GB disk
is slow, transiently doubles disk usage, and blocked the otherwise-idempotent
install. **Fix:** the pre-change snapshot is now **opt-in** (`SNAPSHOT=1`;
default off). Rationale in `system/90-timeshift.sh`: on this disk the snapshot
is low-value (doesn't survive disk failure) and the real rollback nets are the
GA fallback kernel + git + home-manager generations. `install.sh` forwards
`SNAPSHOT` through sudo so `SNAPSHOT=1 ./install.sh ...` still works on roomy
machines. **Unblock used:** the system layer had already fully applied in round
2, so the install was finished by running just the user layer directly:
`nix run home-manager/master -- switch --flake "path:.#zenbook-duo" -b backup`.

### Round 4: node buildEnv collision (two Node versions)

home-manager downloaded everything then failed at the final `home-manager-path`
derivation: `two given paths contain a conflicting subpath: nodejs-22.../node.bash
and nodejs-20.../node.bash`. `modules/node.nix` pinned `nodejs_20` explicitly
while `nodePackages.pnpm`/`typescript` propagated the default `nodejs_22` —
two versions in one buildEnv collide on shared files (and would also collide on
`bin/npm`). **Fix:** one Node version (`nodejs_22`) with **top-level** `pnpm`
and `typescript` — `nodePackages.*` is additionally removed in newer nixpkgs,
so this also prevents a future-update breakage. Verified by building
`home.path` (node on, cloud/ai off, matching the laptop) to completion in the
work session against current nixpkgs.

### Round 5: clear the home-manager activation warnings

The install succeeded (duo watchers started, layout toggled); cleanup pass to
silence the deprecation traces:
- `programs.git.{userName,userEmail,extraConfig}` → `programs.git.settings.*`
- `programs.vscode.{extensions,userSettings}` → `programs.vscode.profiles.default.*`
  in modules/{node,python,cloud}.nix (home.nix already used profiles.default)
- `news.display = "silent"` to drop the "N unread news items" line
Verified by evaluating both host profiles against a home-manager new enough that
the old names hard-error — no git/vscode warnings remain. The `xorg.*` rename
warnings are deliberately left (they appear only on newer nixpkgs, not the
current pin — renaming now would break the pin; deferred to a flake-update, G2).
The apt "could not resolve" line was a transient DNS blip (packages already
present) and the non-NixOS GPU notice is informational — run
`non-nixos-gpu-setup` once to clear it.

### Round 6: first post-install login loop — the SHELL export (Wayland GDM)

After reboot, correct password bounced back to GDM (wrong password was still
rejected — auth worked, the *session* died). Console login (Ctrl+Alt+F3) fine.
Moving `~/.profile` aside let GNOME start, isolating home-manager's login-time
env as the cause. Discriminators: `~/.nix-profile/share/glib-2.0/schemas` was
empty (ruled out the XDG_DATA_DIRS schema-shadowing trap); the journal showed
the user session cleanly reaching `exit.target` ~16 s after login (gnome-session
*quit*, not crashed); the session is **Wayland**, so GDM sources `~/.profile`.
Prime suspect: `home.sessionVariables.SHELL = "<nix-store>/bin/zsh"` — a SHELL
outside `/etc/shells` makes Wayland GDM eject the session.
**Fix:** drop the SHELL export from home.nix; install `zsh` in the system layer
(so it's in /etc/shells) and `chsh` the login user to it the OS-correct way.
(The ❯ prompt seen with .profile moved aside was starship-on-bash, not zsh —
starship uses ❯ for both, so the machine was actually on bash.)

### Round 7: chsh set, but terminals still opened bash — VTE reads `$SHELL`

After Round 6 login worked, `getent passwd $USER` correctly showed `/usr/bin/zsh`
(the `chsh` took), yet every terminal was still bash. The trap: **`$SHELL` is not
your current shell** — it's a login-time tag the GNOME session captures once and
hands to every child unchanged; neither bash nor zsh rewrites it. So `echo $SHELL`
reading `/bin/bash` proves nothing. Ground-truth probes instead:
```sh
echo "zsh=${ZSH_VERSION:-no} bash=${BASH_VERSION:-no}"  # which shell parameters exist
command ps -p $$ -o comm=                               # the real running binary
```
These confirmed the running shell genuinely was **bash** (not a stale tag).
Root cause: **gnome-terminal (VTE) picks the shell it spawns from `$SHELL`, not
from the passwd entry** — so `chsh` alone never reaches new terminals; VTE saw
`$SHELL=/bin/bash` and launched bash. (`/proc/$PPID/comm` = `gnome-terminal-`,
bash invoked *non-login*.)
**Fix:** re-add `home.sessionVariables.SHELL`, but to the **apt** path
`/usr/bin/zsh` — which `grep zsh /etc/shells` confirms is a registered valid
shell, so it will *not* re-trigger the Round-6 GDM loop (that was caused by a
`/nix/store` path, which is not in /etc/shells). Now passwd shell and `$SHELL`
agree, and VTE spawns zsh.
- Bonus: a stray `alias ps='pnpm start'` in the user's own `~/.bashrc` shadowed
  `ps` — a pure red herring that vanishes on zsh (zsh never reads `~/.bashrc`).
