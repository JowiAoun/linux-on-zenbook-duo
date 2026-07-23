# ZenDuo Master Plan

## Dual-booting Ubuntu 24.04 LTS on the ASUS Zenbook Duo (2024) UX8406MA — and evolving `dome` to make it reproducible

> **Status:** v1.1 — 2026-07-21 (supersedes [v1.0](research/2026-07-21-zenduo-master-plan-v1.0.md))
> **Scope:** From a working Windows 11 machine (backed up, BitLocker key saved) to a safe, fully-tooled Ubuntu 24.04 dual boot, with the `dome` repo evolved to reproduce the whole setup, including our **own** Duo hardware tooling (**`zenduo`**, living in `duo/`).
> **Prime directive:** *Never take a step that can't be undone.* Every phase has an explicit verification gate and a rollback path. All destructive operations happen as late as possible, after the hardware has proven itself on a live USB.
>
> **Changes v1.0 → v1.1:**
> - Repo inventory corrected against the actual tree (5 modules incl. `cloud`, Node 20, bash+zsh both configured — see §0.1).
> - alesya-h's repo license **verified: BSD-2-Clause** → licensing rules relaxed (§11.2).
> - Mainline `hid-asus.c` checked directly: **no `0b05:1b2c` entry exists upstream** → native Fn-keys/backlight are confirmed absent; our fallback path is the plan of record, not a contingency (§2 V8).
> - The scaffolding referenced throughout (`system/`, `duo/`, `hosts/`, `Makefile`, `install.sh`) now actually exists in this repo.

---

## 0. How to read this plan

- Phases **A–E** get Ubuntu installed safely (one to two evenings).
- Phases **F–H** build out `dome` (system layer, Nix user layer, `zenduo` tooling) — iterative, low risk, reversible with `git` + Timeshift.
- Phase **I** is the acceptance test matrix; Phase **J** is day-2 maintenance.
- ⛔ marks **hard gates**: do not continue past them until the gate criteria pass.
- 🔧 marks steps automated by scripts in this repo (`system/`, `duo/`).
- **VERIFY-ON-HW** marks claims we could not fully confirm from sources; they must be tested on the machine before being relied on.

### 0.1 Repo state snapshot (read directly, 2026-07-21)

What `dome` contained before this evolution began:

| Path | Contents |
|------|----------|
| `flake.nix` | Standalone home-manager flake; `nixpkgs` = nixos-unstable; impure `builtins.getEnv "USER"`; `homeConfigurations` keyed by username (`default`, `user`, `jaoun`, `codespace`, + `vscode`/`codespaces` aliases); hardcoded `x86_64-linux` |
| `home.nix` | ~516 lines: core packages (git, gh, fzf, ripgrep, bat, lazygit, tmux, jq, age, swi-prolog, manim/C build deps…), **bash AND zsh** (oh-my-zsh + Starship), VS Code (Tokyo Night, per-module extensions), git, tmux, vim dotfile, lazygit config, LD_LIBRARY_PATH/PKG_CONFIG_PATH plumbing for pip binary wheels |
| `modules/` | **Five** toggleable modules + option declarations in `default.nix`: `python` (py3+pyenv+pipx), `node` (Node **20**+nodenv+pnpm), `java` (JDK21), `ai` (Claude Code via official installer, self-updating + Gemini CLI via npm), `cloud` (terraform, pulumi, aws/azure/gcloud/oci CLIs, kubectl, helm, docker) |
| `bootstrap.sh` | Interactive installer: env detection (Codespaces/WSL), `sed`-mutates `user-config.nix`, installs Nix, runs `home-manager switch --flake .#$USER` |
| `user-config.template.nix` | name/email, 5 module booleans, environment (isCodespaces/isWSL/username/homeDirectory), git + shell prefs |
| Hygiene issues | `node_modules/` (containing only a stray `.package-lock.json`), `package-lock.json`, `.node-version` committed — removed in this evolution |

What this evolution **adds** (Phases F–H artifacts): `docs/` (this plan + research archive), `system/` (root layer), `duo/` (zenduo tooling), `hosts/` (per-machine profiles), `modules/zenbook-duo/` (home-manager wiring), `Makefile`, `install.sh`. Nothing existing was removed or behaviorally changed except the node artifacts above; `bootstrap.sh` continues to work for WSL/Codespaces.

---

## 1. Decisions (locked) and assumptions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Distribution | **Vanilla Ubuntu 24.04.4 LTS** (GNOME, Wayland) | See §1.1 — ratified over Arch |
| D2 | Disk split | ~~200 GB~~ → **as-built: ~52 GB for Ubuntu** (Windows' `$MFT` metadata capped the shrink; Option B ratified 2026-07-22 — see [INSTALL-LOG.md](INSTALL-LOG.md)). Endgame: full-disk clean reinstall via this repo once Windows is retired | Jay's choice; conservative shrink, Windows stays the BIOS-update/fallback OS until retirement |
| D3 | Encryption | **LUKS2 + passphrase** for Ubuntu root; separate unencrypted 2 GB `/boot`; Windows keeps BitLocker | Theft protection on both OSes; §7 handles the installer's LUKS gap |
| D4 | Repo architecture | **Hybrid**: keep home-manager flake (user layer) + idempotent bash **system layer** + `hosts/` profiles | Ratified; WSL/Codespaces flows keep working |
| D5 | Duo tooling | **Write our own (`zenduo`)**, using alesya-h & Fmstrat as prior art | Control + maintenance. Licensing in §11.2 — now *relaxed* for alesya-h (BSD-2-Clause verified), still strict for Fmstrat (GPL-3.0) |
| D6 | Boot chain | **GRUB on the existing Windows ESP** (no format!), Secure Boot **stays ON**, `os-prober` enabled | Ubuntu's signed shim works with Secure Boot; one ESP avoids firmware confusion |
| D7 | Kernel policy | **HWE 6.17 stack** (default on 24.04.4) + **GA 6.8 installed as fallback** | Newest well-tested kernel for this hardware; known-good escape hatch in GRUB |
| D8 | Swap | ~~8 GB~~ → **4 GB swapfile inside encrypted root** (as-built, small-disk Option B); no hibernation | Machine is s2idle-only; hibernate isn't worth the complexity |
| D9 | Clock | Windows switched to **UTC RTC** via registry | More robust than making Linux use local time |
| D10 | Desktop | **GNOME on Wayland** (Ubuntu default) | All Duo display tooling depends on Mutter's D-Bus API; KDE/X11 out of scope |

### 1.1 Arch vs vanilla Ubuntu — recommendation: **vanilla Ubuntu 24.04.4**

1. **The kernel-freshness argument for Arch has mostly expired.** In 2024–2025, Arch's edge was getting Duo enablement (the 6.11 Wi-Fi-detach fix, HID keyboard work) months early. As of Feb 2026, Ubuntu 24.04.4 ships the **6.17 HWE kernel + Mesa 25.2** out of the box — at or past the point where the UX8406MA's known kernel-side fixes landed. The remaining gaps (auto display toggle, rotation, brightness sync, tablet mapping) are **userspace** problems `zenduo` solves identically on any distro.
2. **The stated constraint is "be extremely careful and break nothing."** Arch is a rolling target: kernel bumps arrive weekly and *this exact machine* has already been burned by one (the i915 6.9-line second-screen regression hit Arch users first). On LTS, kernels move only when *you* move them, Timeshift snapshots bracket every change, and a known-good kernel stays installed.
3. **The whole stack is already Ubuntu-shaped.** `dome` targets WSL + Codespaces (both Ubuntu), and the hybrid architecture (D4) delivers fresh userspace tools through Nix anyway — Arch-like tool freshness on an LTS base.
4. **Community path is widest here.** The reference implementations and most UX8406 success reports are GNOME-first; Fmstrat validates specifically against Ubuntu releases.

**What you give up (honestly):** day-0 mainline kernels (mitigation: Ubuntu mainline-kernel PPA on demand), the AUR (Nix covers this), the Arch wiki (still readable from Ubuntu). **Middle path if ever wanted:** Fedora Workstation. Not needed today.

---

## 2. Verified research baseline

Every load-bearing claim from the research reports, re-checked. ✅ = independently re-verified (date noted), 📄 = well-sourced in the research and consistent with other evidence (not independently re-verified), ❓ = could not confirm — the plan treats it as unknown and gates on hardware.

> **Phase C gate ran 2026-07-22 — hardware ground truth is in.** V6, V9, V10, V12, V14 and V16 are confirmed ✅ on the machine (both panels work on 6.17; NVMe visible behind VMD; Wi-Fi survives detach). V8 confirmed in the expected direction (no native kbd-backlight, `hid_asus` not binding → the HID fallback is the operative path). Bonus findings beyond the table: native `platform_profile` support, an `asus_screenpad` backlight device, and `deep` listed in `mem_sleep`. Full readout: [INSTALL-LOG.md](INSTALL-LOG.md).

| # | Claim | Status | Consequence for the plan |
|---|-------|--------|--------------------------|
| V1 | Ubuntu 24.04.4 (Feb 2026) ships **6.17 HWE + Mesa 25.2.x** | ✅ 2026-07-21 (Phoronix, OMG!Ubuntu, UbuntuHandbook) | Install 24.04.4 directly; **no post-install kernel dance needed** |
| V2 | Latest UX8406MA BIOS = **312, 2026-03-10** | ✅ 2026-07-21 (ASUS support) | Phase A updates BIOS from Windows before anything else |
| V3 | `dome` repo inventory | ✅ 2026-07-21 (read directly — see §0.1; **corrects v1.0**: five modules incl. `cloud`, Node 20 not 24, bash+zsh both managed, `node_modules/` near-empty) | Migration plan §10 matches reality |
| V4 | alesya-h repo: `duo` script feature set + deps (`gnome-monitor-config`, `usbutils`, `inotify-tools`, `iio-sensor-proxy`, python3+pyusb); GNOME-specific | ✅ 2026-07-21 (README re-fetched) — **NEW: license is BSD-2-Clause** | `zenduo` reimplements the feature set with Mutter D-Bus instead of `gnome-monitor-config`; BSD-2 permits adapting code with attribution if we ever want to (§11.2) |
| V5 | Fmstrat repo: GPL-3.0, systemd-based, tested Ubuntu 25.10/UX8406CA; **Fn keys still partial and detached-keyboard backlight broken even there** | ✅ 2026-07-21 (README re-fetched) | Temper expectations: even on 6.17, assume Fn keys/backlight need userspace help (**VERIFY-ON-HW** via `duo doctor` + `duo fn-probe`) |
| V6 | Keyboard-detach kills Wi-Fi; fixed by asus-wmi quirk in **kernel ≥ 6.11** | 📄 (patch author + user confirmation cited in research) | 6.17 inherits the fix; live-USB gate explicitly tests detach → Wi-Fi survives |
| V7 | Touch/pen per-panel mapping needs Mutter MR 3556 + libwacom #640, both merged; GNOME 46+ | 📄 | Ubuntu 24.04 = GNOME 46 → should work; acceptance test I-11/I-12 confirms |
| V8 | Native (in-kernel) Duo kb backlight/Fn keys | ✅ 2026-07-21 **checked mainline `hid-asus.c` directly: device `0b05:1b2c` has NO entry** — the driver has generic `QUIRK_HID_FN_LOCK` and kbd-backlight machinery (`asus_kbd_backlight_work`, buffer `{0x5a, 0xba, 0xc5, 0xc4, <level>}`) but not for this device | Native support is **absent upstream today**, not merely unconfirmed. `zenduo` still probes native first (`/sys/class/leds/asus::kbd_backlight`) so we auto-upgrade when it lands, but the HID fallback is the expected daily path. Payload bytes for the fallback are confirmed from kernel source |
| V9 | i915 second-screen regression (6.9+ line) — status on 6.17 | ❓ | ⛔ Live-USB gate (Phase C) proves both panels **before any disk change**; `i915.enable_psr=0` kept; GA 6.8 fallback kernel installed |
| V10 | Hardware IDs: kbd USB `0b05:1b2c`; digitizers ELAN9008 `04F3:4259` (top) / ELAN9009 `04F3:42EC` (bottom); iGPU `8086:7d55`; panels eDP-1/eDP-2 | 📄 (inxi dumps in research) | Baked into `duo doctor` checks and tablet-mapping config; doctor prints actuals so mismatches surface immediately |
| V11 | Audio: SOF `sof-audio-pci-intel-mtl`; early-kernel "dummy output"; one woofer pair enabled by quirk, second needs SPI/_DSD work | 📄 | On 6.17 + current firmware expect working audio slightly below Windows speaker fullness; test in gate; known limitation, not a blocker |
| V12 | Battery charge limit via `/sys/class/power_supply/BAT?/charge_control_end_threshold` | 📄 (standard asus-wmi) | `duo bat-limit` uses it; doctor verifies the node exists |
| V13 | Suspend: **s2idle only**, historical MTL drain issues | 📄 | Accept; measure overnight drain in Phase I; no hibernation (D8) |
| V14 | Raw udev rules on the pogo keyboard cause an **event storm** — poll instead | 📄 (both upstreams converged on polling) | `duo watch-displays` polls sysfs at 1 Hz with 2-cycle debounce; no udev triggers on attach/detach. The poll is one of three wake-ups — Mutter's `MonitorsChanged` and logind's resume signal are the other two — and each only *re-derives* the correct layout, so a keyboard edge is never the sole trigger (✅ 2026-07-23: an edge-only watcher left the bottom panel lit under a docked keyboard after every resume, because waking makes Mutter re-read `monitors.xml`) |
| V15 | Wi-Fi typically **Intel AX211**; some units BE200 (suspend quirks) | 📄 | `duo doctor` reports which card is present; contingency §14.6 |
| V16 | Intel VMD/RST could hide the NVMe from the installer | ❓ | Phase B *looks but does not touch* the BIOS storage setting; Phase C checks `lsblk` sees the disk; **never toggle the BIOS storage mode** (breaks Windows) |
| V17 | ASUS on LVFS/fwupd: limited coverage; BIOS via MyASUS (Windows) or EZ-Flash (USB) | 📄 | Windows partition stays as the firmware-update OS (D2); never flash EC/keyboard/panel firmware from Linux |
| V18 | Upstream repos abandoned (assumption behind D5) | ⚠ Partially true at best (Fmstrat has 25.10-era updates; alesya-h at 53 commits, activity dates unconfirmed) | D5 stands on its own merits (control + maintenance); both repos stay on the watch list (§13.4) |

---

## 3. Risk register and safety rails

| # | Risk | L×I | Prevention | Detection | Response |
|---|------|-----|------------|-----------|----------|
| R1 | Windows unbootable after partitioning | Low × Critical | Shrink **only** from Windows Disk Management; never move/resize NTFS from Linux; never touch p1–p4 | Windows boot test in Phase E | §14.3 boot-order repair; recovery USB; restore image |
| R2 | BitLocker recovery loop after GRUB install | Med × High | **Suspend BitLocker** (`-RebootCount 3`) before install; Secure Boot left ON; key saved ✅ | First Windows boot after GRUB | Enter recovery key once; resume protectors; §14.5 |
| R3 | Data loss during shrink | Low × Critical | Backup done ✅; BitLocker suspended; shrink leaves NTFS internally consistent | chkdsk after shrink | Restore from backup |
| R4 | **ESP accidentally formatted** in installer (the #1 dual-boot killer) | Med × Critical | Manual-partitioning walkthrough §7 with explicit "do **not** tick format on p1"; mandatory pause at the summary screen | Installer summary review | If formatted: §14.4 rebuild Windows boot files (`bcdboot`) from recovery USB |
| R5 | Second screen dead on 6.17 (V9 unknown) | Low-Med × Med | ⛔ Phase C proves panels on live USB **before** install | `duo doctor` panel check | No-go → investigate (mainline-PPA live test) with zero disk changes made |
| R6 | LUKS system unbootable on first boot (installer doesn't write `crypttab` for pre-made LUKS) | **High** × Med | §7.6 chroot step adds `crypttab` + rebuilds initramfs **before** first reboot — mandatory | First-boot passphrase prompt appears | §14.2 live-USB unlock + chroot repair (exact commands provided) |
| R7 | Secure Boot blocks something | Low × Med | Stock Ubuntu shim/kernels are signed; no DKMS modules planned | Boot failure w/ SB error | Temporarily disable SB to diagnose; MOK enrollment only if DKMS ever added |
| R8 | Laptop cooks in a bag (s2idle wake) | Med × Med | Test suspend in Phase I; lid-close = suspend; check `/sys/power/mem_sleep` | Warm-bag test; overnight drain % | Tune wakeup sources (`/proc/acpi/wakeup`); worst case power off before transport |
| R9 | A Windows or GRUB update breaks the boot menu | Med × Low | Windows keeps its own bootmgr entry (chainloaded); firmware Esc menu always works | Boot menu missing an OS | §14.3 `efibootmgr`/BIOS fix; `update-grub` re-detects Windows |
| R10 | **Our own tooling turns both screens off** | Med × Med | Hard invariant in `zenduo`: `displayctl` refuses any config with zero enabled panels; keyboard-attach always converges to a working state; Ctrl+Alt+F3 TTY as last resort | Two black screens | Attach keyboard (poller re-enables top); TTY → `duo both`; `loginctl terminate-session` worst case |
| R11 | License contamination in `zenduo` | Low × Med | §11.2 rules: no code from GPL-3.0 Fmstrat; alesya-h (BSD-2) adaptation allowed **with attribution** but default remains original implementation; kernel constants are facts | Code review before each commit | Rewrite tainted code clean-room; add attribution where BSD-2 code was adapted |
| R12 | Bricking via firmware flashing from Linux | — | **Out of scope, forever**: no EC, keyboard-MCU, or panel-firmware flashing from Linux. BIOS via MyASUS/EZ-Flash only | — | — |

**Standing safety rails through every phase:**

1. BitLocker recovery key + Windows recovery USB exist *off-machine* before Phase A completes.
2. Nothing writes to disk until the ⛔ Phase C gate passes.
3. The installer summary screen gets a full stop-and-read before clicking Install (R4).
4. No reboot after install until the §7.6 chroot fix is done (R6).
5. Timeshift snapshot before every `make system` run once Ubuntu is up (automated: `system/90-timeshift.sh` runs first).
6. Windows partitions are sacred: never resize, move, defragment, or "clean up" p1–p4 from Linux.

---

## 4. Phase A — Windows-side preparation (~1–2 h active)

**Goal:** Windows fully prepared, firmware current, ~205 GB carved out, install media ready. Everything here is done *in Windows*.
**Preconditions:** Backup verified restorable ✅; BitLocker recovery key saved off-machine ✅ (double-check legibility + match: `manage-bde -protectors -get C:`).

| Step | Action | Command / location | Verify |
|------|--------|--------------------|--------|
| A1 | Confirm BitLocker key matches this volume | Admin PowerShell: `manage-bde -protectors -get C:` → compare the Numerical Password **ID** with the saved key's ID | ID matches saved key |
| A2 | **Update BIOS to 312** (2026-03-10) | MyASUS → Customer Support → Live Update (or download UX8406MA BIOS 312 from ASUS support) | BIOS shows 312 after reboot. ⚠ On AC power; do not interrupt |
| A3 | Update other firmware/drivers offered by MyASUS (ME, touchpad…) | MyASUS Live Update | No pending critical updates |
| A4 | Disable Fast Startup (prevents dirty NTFS + hibernation state) | Admin PowerShell: `powercfg /h off` | `powercfg /a` no longer lists Hibernate/Fast Startup |
| A5 | Set hardware clock to UTC (D9) | Admin PowerShell: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f` then reboot | Windows clock still correct after reboot |
| A6 | Create a **Windows recovery USB** (≥16 GB stick #1) | Search "Create a recovery drive", include system files | Stick boots (test via Esc boot menu) |
| A7 | Shrink C: by **~205 GB** | `diskmgmt.msc` → right-click C: → Shrink Volume → `209920` MB | ~205 GB shows as *Unallocated* |
| A8 | If shrink offers less (unmovable files) | Temporarily disable pagefile + System Restore on C:, reboot, retry. **Re-enable pagefile after.** No third-party partition tools on a BitLocker volume | Shrink succeeds |
| A9 | Disk health check | `chkdsk C: /scan` | No errors |
| A10 | Download **Ubuntu 24.04.4 desktop ISO** + verify | ubuntu.com/download; `certutil -hashfile ubuntu-24.04.4-desktop-amd64.iso SHA256` vs SHA256SUMS | Hash matches exactly |
| A11 | Write ISO to USB stick #2 (≥8 GB) | Rufus (GPT / UEFI non-CSM, default ISO mode) or Ventoy | Stick boots to Ubuntu menu |
| A12 | Stage this repo where the live session can reach it | Clone/copy `dome` onto stick #2's data partition (Ventoy makes this trivial) | `duo/bin/duo` present on the stick |
| A13 | **Suspend BitLocker** (immediately before Phases B/C/D, one sitting) | Admin PowerShell: `manage-bde -protectors -disable C: -RebootCount 3` | `manage-bde -status C:` → "Protection Off (3 reboots remaining)" — auto-re-arms: a deliberate dead-man switch |
| A14 | Record machine specifics | `msinfo32`: SSD model, RAM, BIOS mode (UEFI), Secure Boot (On) | Values land in `docs/hardware.md` later |

**Rollback:** everything in Phase A is non-destructive. The shrink is undone by extending C: back; BitLocker re-arms after 3 reboots (or `manage-bde -protectors -enable C:`).

---

## 5. Phase B — BIOS configuration (~10 min)

**Goal:** know the firmware state; change the minimum possible.

1. Reboot; **F2** at the ASUS logo → BIOS setup. (**Esc** = one-time boot menu — you'll use it constantly.)
2. **Photograph every settings page** before touching anything (your "factory state" record).
3. Confirm / set:
   - **Secure Boot: ON** — leave it (D6). Don't clear keys, don't enter setup mode.
   - **Storage / VMD / Intel RST: LOOK, DON'T TOUCH** (V16). Record what it says. If Phase C's live session sees the NVMe, the setting is fine as-is. Toggling it would likely make **Windows** unbootable.
   - **Fast Boot (BIOS): Disable** — makes F2/Esc reliably catchable; harmless.
   - TPM/fTPM: leave enabled (BitLocker needs it).
4. Save & exit.

**Rollback:** re-enter BIOS, restore from photos. Nothing here touches the disk.

---

## 6. Phase C — ⛔ Live-USB validation gate (~30–60 min, zero disk writes)

**Goal:** prove the hardware works on the exact kernel we're about to install — **before** any disk modification. This gate exists chiefly because of V9 (i915 second-screen status on 6.17) and V16 (VMD/NVMe visibility).

1. Esc-boot into USB stick #2 → **"Try Ubuntu"** (do *not* pick Install).
   - If both screens stay black → reboot, pick "Ubuntu (safe graphics)", record that fact (the default modesetting path has an issue; investigate before installing).
2. Connect Wi-Fi. Open a terminal.
3. Run the doctor from the stick 🔧:
   ```
   bash /path/to/dome/duo/bin/duo doctor | tee ~/doctor-live.txt
   ```
   Read-only checks: kernel version (expect 6.17.x) · both eDP panels present & enabled · Mutter D-Bus reachable · keyboard `0b05:1b2c` on USB · `hid_asus` loaded · **native kbd-backlight LED node (V8 ground truth)** · hidraw node for the keyboard · ELAN digitizers (`04f3:4259` / `04f3:42ec`) · IIO sensors · SOF audio device · Wi-Fi card model (AX211 vs BE200, V15) · NVMe visibility (V16 answered here) · VMD controller presence · `charge_control_end_threshold` · `platform_profile` · `mem_sleep` (expect `s2idle`) · suspicious dmesg lines (i915/asus/sof) · Secure Boot state.
4. Manual spot checks (5 minutes, tick them off):
   - Type on the keyboard **attached**; detach it → **does Wi-Fi stay up?** (V6); pair over **Bluetooth** (left-side switch, 6-digit PIN) and type detached.
   - Touch **both** screens; note whether bottom touch lands on the bottom screen or is mis-mapped to top (V7 — mis-mapping is fine, `zenduo` fixes it; *dead* touch is not).
   - Play audio (speakers + jack). Try the camera.
   - Brightness Fn keys; note *which* Fn keys emit anything (feeds `duo fn-probe`).
   - Attach/detach the keyboard 5× in a row — any desktop crash/flicker storm? (V14)
5. Save `doctor-live.txt` to the USB stick — it becomes `docs/hardware.md` raw material and the V8/V9/V15/V16 ground truth.

**GO criteria (all must pass):** NVMe visible · both panels render · keyboard works attached (USB) *and* detached (BT) · touchpad · Wi-Fi up and survives detach.
**SHOULD pass (record if not; not blocking):** audio, camera, both-panel touch, sensors, backlight LED node.
**NO-GO:** any MUST fails → power off. Nothing was written. Regroup (e.g. mainline-PPA kernel live test, firmware check) before ever touching the disk.

---

## 7. Phase D — Partitioning & installation (~1–2 h)

**Goal:** Ubuntu 24.04.4 installed into the ~205 GB gap with LUKS2 root, reusing the existing ESP, Windows untouched.
**Preconditions:** Phase C gate passed · BitLocker suspended (A13, within its 3-reboot window) · AC power connected.

### 7.1 Map the disk (live session, read-only)

```
lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL,MOUNTPOINTS /dev/nvme0n1
sudo parted /dev/nvme0n1 print
```

Expected existing layout (typical ASUS ship state — **record your actual numbers**):
`p1` ESP ~260 MB (FAT32) · `p2` MSR 16 MB · `p3` Windows C: (BitLocker) · `p4` WinRE ~1 GB · then **~205 GB free space**.
⚠ If your partition numbers differ, substitute accordingly *everywhere below*. Never touch p1–p4 beyond mounting p1 as the ESP.

### 7.2 Create the two new partitions (GParted, live session)

In the free space, create — and nothing else:

- `p5`: **2 GiB, ext4**, label `duo-boot` → `/boot` (unencrypted; kernels/initramfs; GRUB reads it without LUKS headaches)
- `p6`: **remaining ~203 GiB, unformatted** → the LUKS2 container

Apply. Double-check p1–p4 untouched in the GParted operation log.

### 7.3 Create the LUKS2 container (terminal)

```
sudo cryptsetup luksFormat --type luks2 /dev/nvme0n1p6      # type YES + strong passphrase
sudo cryptsetup open /dev/nvme0n1p6 cryptroot
sudo mkfs.ext4 -L duo-root /dev/mapper/cryptroot
```

The passphrase is now a **second critical secret** — store it with the BitLocker key (off-machine). Losing it = losing the Ubuntu install.

### 7.4 Run the installer (same live session)

Ubuntu 24.04.4 desktop installer → **Manual installation** ("Something else") — the guided modes can't do this layout, and manual mode has no LUKS-creation UI, which is why we pre-made it in 7.3 (R6):

| Device | Use as | Format? | Mount point |
|--------|--------|---------|-------------|
| `nvme0n1p1` (existing ~260 MB FAT32 ESP) | EFI System Partition | **☐ NO — do not tick** (R4!) | `/boot/efi` |
| `nvme0n1p5` | ext4 | ☑ yes | `/boot` |
| `/dev/mapper/cryptroot` | ext4 | ☐ no (freshly made in 7.3) | `/` |
| *Bootloader install device* | `/dev/nvme0n1` (the disk) | — | — |

⛔ **Stop at the summary screen. Read it twice.** It must list: format p5, use p1 as ESP *without* format, use mapper as `/`. Any mention of formatting p1 or touching p3 → **Back**, fix, re-read. Then Install. When it finishes choose **"Continue testing" — do not reboot** (R6).

### 7.5 Why not reboot yet

The installer generally does **not** write `/etc/crypttab` for a pre-existing LUKS container, so the initramfs wouldn't know to ask for the passphrase → first boot drops to busybox. Fix it now, in chroot, in five minutes.

### 7.6 Chroot fix: crypttab + initramfs + GRUB os-prober 🔧

```
# (live terminal; cryptroot still open from 7.3 — if not: sudo cryptsetup open /dev/nvme0n1p6 cryptroot)
sudo mount /dev/mapper/cryptroot /mnt
sudo mount /dev/nvme0n1p5 /mnt/boot
sudo mount /dev/nvme0n1p1 /mnt/boot/efi
for d in /dev /dev/pts /proc /sys /run; do sudo mount --bind $d /mnt$d; done
sudo cp /etc/resolv.conf /mnt/etc/resolv.conf
sudo chroot /mnt

# inside chroot:
blkid /dev/nvme0n1p6        # copy the UUID=... of the crypto_LUKS partition
echo "cryptroot UUID=<that-uuid> none luks,discard" >> /etc/crypttab
apt-get install -y cryptsetup-initramfs   # normally already present
update-initramfs -u -k all
ls /boot/initrd.img-*                     # note the newest version
lsinitramfs /boot/initrd.img-<newest> | grep -m1 cryptsetup   # MUST print something

# make GRUB show Windows (24.04 disables os-prober by default):
sed -i 's/^#\?GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=false/' /etc/default/grub
grep -q GRUB_DISABLE_OS_PROBER /etc/default/grub || echo 'GRUB_DISABLE_OS_PROBER=false' >> /etc/default/grub
update-grub                  # output MUST include "Found Windows Boot Manager"
exit
```

Unmount in reverse (`sudo umount -R /mnt`), remove the USB, reboot.

**Rollback:** if anything in 7.2–7.6 went sideways, nothing outside p5/p6/ESP-grub-files changed → §14.1 removes Ubuntu cleanly and Windows is exactly as before.

---

## 8. Phase E — First boot & dual-boot integrity (~45 min)

| Step | Action | Verify |
|------|--------|--------|
| E1 | Boot → GRUB menu shows **Ubuntu** + **Windows Boot Manager** | Both entries present |
| E2 | Boot Ubuntu → LUKS passphrase prompt → GNOME login | Reaches desktop; both screens or top-only is fine for now |
| E3 | ⛔ **Boot back into Windows — twice**: once via GRUB, once via Esc → Windows Boot Manager | Windows boots both ways. If BitLocker asks for the recovery key once: enter it, continue (expected worst case, R2) |
| E4 | In Windows: `manage-bde -status C:` → protection resumed (3-reboot suspension likely lapsed — good). If still off: `manage-bde -protectors -enable C:` | "Protection On" |
| E5 | Back in Ubuntu: `sudo apt update && sudo apt full-upgrade` | Clean |
| E6 | `uname -r` → **6.17.x**; `timedatectl` → RTC in UTC, time correct in both OSes (A5) | Matches |
| E7 | Clone the repo: `git clone https://github.com/JowiAoun/dome ~/.dotfiles && cd ~/.dotfiles` | Repo present |
| E8 | Run the system layer 🔧: `sudo make system HOST=zenbook-duo` — takes a Timeshift snapshot first, then: base apt packages, HWE + GA-fallback kernels (D7), `i915.enable_psr=0` + os-prober GRUB params, Duo deps, `zenduo-helper` + sudoers. Reboot after | `cat /proc/cmdline` contains `i915.enable_psr=0`; second screen still works; OLED flicker gone; GRUB "Advanced options" lists a 6.8.x kernel |
| E9 | Smoke-test suspend: close lid 2 min, reopen | Resumes; Wi-Fi back; note battery % drop |
| E10 | `duo doctor` on the installed system; save output | Compare against `doctor-live.txt` from Phase C |

**Ubuntu is now installed and safe.** Everything from here is iterative and Timeshift/git-protected.

---

## 9. Phase F — `dome` system layer (in this repo 🔧)

**Goal:** every root-level change to the machine is a **reviewable, idempotent, re-runnable script** in git — never an undocumented one-off command.

Layout (as scaffolded):

```
system/
├── lib.sh              # shared helpers: log/warn/die, require_root, DRY_RUN=1 support,
│                       #   ensure_pkg (apt install iff missing), ensure_line (grep-before-append),
│                       #   ensure_grub_param / grub params applied once via update-grub iff changed,
│                       #   host-profile resolution (HOST env → user-config.nix hostProfile → generic)
├── run.sh              # orchestrator: runs numbered scripts in order, gates duo-only ones on profile
├── 00-preflight.sh     # sanity: Ubuntu 24.04?, UEFI?, not a live session?, apt lock free
├── 10-apt-base.sh      # build-essential curl git make unzip timeshift etc.
├── 20-kernel.sh        # ensure linux-generic-hwe-24.04 (6.17 stack) + linux-generic (GA fallback, D7)
├── 30-grub-params.sh   # GRUB_DISABLE_OS_PROBER=false (all hosts w/ GRUB) ·
│                       #   i915.enable_psr=0 (duo hosts) · single update-grub iff changed
├── 40-duo-deps.sh      # [duo] usbutils inotify-tools iio-sensor-proxy python3-gi
├── 45-duo-udev.sh      # [duo] hidraw uaccess + LED permission rules (permission-only;
│                       #   display logic never reacts to udev events — V14)
├── 50-duo-sudoers.sh   # [duo] installs /usr/local/sbin/zenduo-helper (tiny input-validated root
│                       #   helper: only 'backlight <dev> <0-100>' / 'batlimit <20-100>')
│                       #   + /etc/sudoers.d/zenduo (NOPASSWD for that ONE binary, granted to the
│                       #   configured user only — from user-config.nix — not the sudo group;
│                       #   visudo -c validated) — narrower than upstream's NOPASSWD /usr/bin/env
└── 90-timeshift.sh     # snapshot before changes (run FIRST by run.sh despite the number)
```

Rules: `set -euo pipefail` everywhere · every script re-runnable with zero diff the second time · `DRY_RUN=1 sudo make system` prints what would change without changing it · scripts 40/50 run only when the host profile is `zenbook-duo`.

**Definition of done:** `sudo make system` twice in a row → second run reports no changes.

---

## 10. Phase G — `dome` user layer (Nix) migration

Ordered so nothing breaks for existing environments (WSL/Codespaces):

1. **G1 — flake v2 (done in this evolution):** adds `mkHome`, `homeConfigurations.generic` / `.zenbook-duo` keyed on host profile, `hosts/` directory — while **keeping** all legacy outputs (`default`/`user`/`jaoun`/`codespace`/`vscode`/`codespaces`) byte-compatible during migration. Host outputs read username/homeDirectory from `user-config.nix` (template fallback), eliminating the need for `builtins.getEnv` on the new path.
   **Validation status (2026-07-21):** the original "verify on the current machine" step is impossible (the WSL instance is gone), so both outputs were instead **fully evaluated to derivations in the work session** against current nixos-unstable + home-manager master — including the generated `duo-watch-displays`/`duo-bat-limit` units. Two packages removed from nixpkgs were caught and fixed (`neofetch` → `fastfetch`, `wslu` dropped). The first real `switch` happens on the Duo (or optionally in a Codespace first, via `bootstrap.sh`, as a lower-stakes rehearsal).
   **Flake-ref gotcha (fixed):** `--flake .` on a git repo copies *tracked files only*, so the gitignored `user-config.nix` was silently ignored and the template's values used instead. All invocations (Makefile, install.sh, bootstrap.sh) now use `path:.#...`, which includes untracked files — use the `path:` prefix in any manual `home-manager switch` too. Note this puts `user-config.nix` contents (name/email/prefs — no secrets) in the world-readable Nix store, same as any flake source.
2. **G2 — split `home.nix`** into `home/common.nix` + `home/shell.nix`, move `modules/{python,node,java,ai,cloud}.nix` → `home/langs/`. **Deferred** — pure refactor, done later with a generation-diff parity check (`home-manager build` both, `nix store diff-closures`). Not a blocker for the install.
   **Deprecation backlog for the same pass** (warnings on current unstable; the new names are NOT confirmed to exist in the currently-pinned inputs, so rename only together with a `nix flake update` + re-evaluation): `xorg.libX11`-style attrs → flattened `libx11`-style names, and `programs.git.{userName,userEmail,extraConfig}` → `programs.git.settings`. (`programs.zsh.initExtra` → `initContent` is already done — proven byte-identical output.)
3. **G3 — Ubuntu-desktop niceties:** `targets.genericLinux.enable = true` on the `zenbook-duo` host (icons/.desktop/XDG for Nix GUI apps). Kept off `generic` until verified harmless on WSL/Codespaces.
4. **G4 — GNOME dconf capture:** once the desktop is hand-configured to taste (Phase H era): `dconf dump / > dump.ini` → `dconf2nix` → `home/gnome.nix`, review, commit. From then on look-and-feel is reproducible.
5. **G5 — repo hygiene (done):** `node_modules/`, `package-lock.json`, `.node-version` untracked + `.gitignore` extended. `bootstrap.sh` stays for Codespaces/WSL until `install.sh` fully replaces it.
6. **G6 — secrets (later, optional):** `sops-nix` + age key per machine; never plaintext secrets in the store (flake contents are world-readable in `/nix/store`).

---

## 11. Phase H — `zenduo`: our own Duo tooling (in `duo/` 🔧)

### 11.1 Design principles

1. **Fail-safe by construction** — the display module *refuses* any configuration that would leave zero panels enabled (R10); keyboard-attach always converges to a working state; every watcher is a user-level systemd unit you can `systemctl --user stop`.
2. **Native-first, fallback-second** — every capability probes the kernel interface first (e.g. `asus::kbd_backlight` LED class device) and only then falls back to our userspace implementation. As kernels improve, `zenduo` automatically does less. `duo doctor` reports which path is active. (V8 says the fallback *is* today's path for kb-backlight.)
3. **Poll, don't storm** (V14) — keyboard presence = sysfs poll at 1 Hz with 2-cycle debounce; no udev rules on the pogo pins.
4. **Talk to GNOME properly** — display control via Mutter's `org.gnome.Mutter.DisplayConfig` D-Bus API (python3-gi), not the unpackaged `gnome-monitor-config` tool, and not xrandr (Wayland). Same API GNOME Settings uses.
5. **Dependency-light** — the kb-backlight fallback writes HID feature reports through `/dev/hidraw` (no pyusb, no kernel-driver detach that would kill keyboard input). A pyusb path is deliberately not implemented: if hidraw fails we want to know why, not silently degrade to a driver-detaching transport.
6. **Everything observable** — watchers log state transitions to the journal (`duo log` tails them).
7. **Self-contained & extractable** — `duo/` has no imports from the rest of `dome`; its own README and MIT LICENSE; extractable to a standalone repo once proven (v1.0 milestone).

### 11.2 Licensing rules (R11) — updated v1.1

- `zenduo` is **MIT** (matches dome).
- **Fmstrat/zenbook-duo-linux is GPL-3.0: never copy code from it.** Reading it to understand *behavior* (BT sync, airplane-mode reset, resume re-assert) is fine; implementation must be ours.
- **alesya-h/zenbook-duo-2024-ux8406ma-linux is BSD-2-Clause (verified 2026-07-21).** Adapting code is now *permitted* with copyright-notice attribution. Default remains original implementation (our architecture differs — D-Bus vs `gnome-monitor-config`); if we ever adapt a snippet, its file gets the BSD-2 attribution block.
- Kernel-derived constants (USB IDs; the ASUS HID feature report `{0x5a, 0xba, 0xc5, 0xc4, <level>}` confirmed in mainline `hid-asus.c`) are facts; using them is fine.
- Command names (`watch-displays`, `bat-limit`, …) are interface, not code — kept deliberately compatible with prior art.
- Both upstreams are credited in `duo/README.md`.

### 11.3 Components (as scaffolded)

| Path | What it does | State |
|------|--------------|-------|
| `duo/bin/duo` | CLI: `doctor`, `status`, `top/bottom/both/toggle`, `watch-displays`, `apply-displays`, `sync-backlight`, `watch-backlight`, `kb-backlight 0-3`, `bat-limit N`, `set-tablet-mapping`, `watch-rotation`, `fn-probe`, `log` | **doctor: complete & runnable today** (Phase C's gate tool; pure bash, read-only, no deps). Display/backlight/battery: implemented, **VERIFY-ON-HW**. Rotation: experimental |
| `duo/lib/displayctl.py` | Mutter DisplayConfig D-Bus client: get state, enable/disable panels by connector (eDP-1/eDP-2), preserve scale/transform/primary, zero-panel refusal invariant | Implemented, VERIFY-ON-HW |
| `duo/lib/watch_displays.py` | The dock-policy daemon. Converges wanted-vs-actual layout on three wake-ups (1 Hz keyboard poll, Mutter `MonitorsChanged`, logind `PrepareForSleep`), so resume/hotplug/lock/GNOME-Settings changes are all corrected; honours a manual override until the next dock/undock; `--once` backs `duo apply-displays` | Implemented, verified on HW 2026-07-23 |
| `duo/lib/dock.py` | Shared keyboard-dock probe (pogo USB only — Bluetooth means undocked) and the `$XDG_RUNTIME_DIR` manual-override marker | Implemented, verified on HW 2026-07-23 |
| `duo/lib/kb_backlight.py` | hidraw-first fallback: HID SET_FEATURE `{0x5a, 0xba, 0xc5, 0xc4, <0-3>}` to `0b05:1b2c` via `HIDIOCSFEATURE` ioctl (no pyusb, no driver detach); harmless if the device ignores it | Implemented, VERIFY-ON-HW |
| `duo/helper/zenduo-helper` | Root helper (installed to `/usr/local/sbin` by `system/50-duo-sudoers.sh`): validated `backlight`/`batlimit` writes only | Implemented |
| `duo/systemd/*.service` | `duo-watch-displays`, `duo-watch-backlight`, `duo-watch-rotation` — user units, `WantedBy=graphical-session.target` | Templates ready; instantiated by the Nix module on the duo host |
| `modules/zenbook-duo/default.nix` | home-manager module: `zenduo.enable`, `zenduo.repoPath`, per-watcher toggles; wires units + adds `duo/bin` to PATH | Ready |

### 11.4 Roadmap

- **v0.1 (now):** `duo doctor` — Phase C's gate. Its output resolves V8/V9/V15/V16 empirically.
- **v0.2:** manual display control + `watch-displays` proven through 20 attach/detach cycles + suspend/resume.
- **v0.3:** brightness sync (via `zenduo-helper`) + kb backlight (native or hidraw per doctor).
- **v0.4:** tablet/touch mapping (dconf, per V7/V10 device IDs) + rotation watcher (tent/portrait).
- **v0.5:** `bat-limit`, `fn-probe` inventory, polish, docs; decide Fmstrat-parity extras (BT auto-toggle, airplane reset) from observed need.
- **v1.0:** stable on daily use ≥2 weeks → optionally extract to its own repository.

### 11.5 Per-feature test protocol

Every feature graduates only after: 10× attach/detach cycles · survives suspend/resume · survives reboot · survives GNOME session restart (log out/in — `Alt+F2 r` is X-only) · no journal errors in `duo log`.

---

## 12. Phase I — Acceptance test matrix

Run after v0.3; re-run after every kernel update (`duo doctor` automates the top half).

| # | Feature | Test | Expected | If it fails |
|---|---------|------|----------|-------------|
| I-1 | Both panels | GNOME Displays shows eDP-1+eDP-2 | Both, 2880×1800@120 (or 1920×1200@60) | GA-kernel boot test; §14.6 |
| I-2 | Keyboard attached | Type | Works (USB `0b05:1b2c`) | doctor; check `hid_asus` |
| I-3 | Keyboard detached | Type over BT | Works | Re-pair; BT logs |
| I-4 | Wi-Fi survives detach | Detach with ping running | No drop (V6) | Kernel < 6.11? (shouldn't be) |
| I-5 | Auto screen toggle | Attach → bottom off; detach → both on | < 2 s, no flicker storm | `duo log`; debounce tuning |
| I-6 | Kb backlight | `duo kb-backlight 2` | Visible change; note native vs hidraw path | fn-probe; HID trace |
| I-7 | Fn keys | `duo fn-probe` inventory | Document what works — V5/V8 say expect gaps | Map missing keys via GNOME shortcuts to `duo` commands |
| I-8 | Audio | Speakers, jack, mic | All output; quality ≈ Windows-ish (V11) | `firmware-sof-signed` version; alsa-info |
| I-9 | Camera | Snapshot app | Image | uvcvideo dmesg |
| I-10 | Touch top | Touch hits top | Correct panel | — |
| I-11 | Touch bottom | Touch hits bottom | Correct panel after `set-tablet-mapping` (V7) | dconf keys; libwacom version |
| I-12 | Pen | Draw on both panels | Maps correctly | same as I-11 |
| I-13 | Rotation | Tent/portrait | Follows within 2 s | v0.4 iteration |
| I-14 | Brightness sync | Fn brightness | Both panels track | `zenduo-helper` perms |
| I-15 | Battery limit | `duo bat-limit 80`; charge past 80? | Stops at 80% | sysfs node (V12) |
| I-16 | Suspend | Lid close 30 min | ≤ ~2% drop, resumes clean | `/sys/power/mem_sleep`; wakeup sources |
| I-17 | Overnight suspend | 8 h | ≤ ~10% drop (V13 tolerance) | Deeper tuning/TLP |
| I-18 | TB4 + HDMI | External display on each port | Works alongside internal panels | cable/dock specifics |
| I-19 | GRUB → Windows | Boot Windows via GRUB | No BitLocker prompt (steady state) | §14.5 |
| I-20 | Windows updates | Take a cumulative update | Boot order/menu intact | §14.3 |
| I-21 | Timeshift restore drill | Restore pre-change snapshot over a scratch change | Comes back | Practice before you need it |

---

## 13. Phase J — Maintenance & day-2 operations

1. **Updates:** `apt` weekly. Before any kernel version jump: Timeshift snapshot (automated for `make system`; manual for plain `apt full-upgrade` kernel bumps). After: `duo doctor` + glance at I-1/I-5. Keep the GA 6.8 kernel installed permanently; prune old HWE kernels N-1.
2. **BIOS:** check MyASUS (Windows side) quarterly; EZ-Flash from USB is the no-Windows path. Never flash EC/keyboard/panel firmware from Linux (R12).
3. **Ubuntu point releases:** 24.04.5 expected ~Aug 2026 (final point release; HWE may roll again) — evaluate with a snapshot + doctor pass; no urgency.
4. **Upstream watch (monthly, ~10 min):** alesya-h repo · Fmstrat repo · asusctl issue #25 · NixOS Discourse UX8406MA thread · kernel `hid-asus.c` / `asus-wmi.c` changelogs. When native support lands, `zenduo`'s native-first probing usually means just deleting fallback code. Watch specifically for a `0b05:1b2c` entry appearing in `hid-asus.c` (V8).
5. **Nix layer:** `nix flake update` monthly-ish; `home-manager switch` with `-b backup`; roll back via `home-manager generations`.
6. **Windows side:** let it update freely; if it steals boot priority, fix via BIOS boot order or `efibootmgr -o` (§14.3). Fast Startup stays off.

---

## 14. Rollback & disaster recovery

- **14.1 Remove Ubuntu entirely (full undo):** From Windows: `diskmgmt.msc` → delete p5+p6 → extend C:. Mount ESP: admin `mountvol S: /S` → `rd /s S:\EFI\ubuntu`. Boot order: BIOS → Windows Boot Manager first (or `bcdedit /set {fwbootmgr} displayorder {bootmgr} /addfirst`). Machine is factory-shaped again.
- **14.2 LUKS first boot fails (busybox/initramfs prompt):** live USB → `cryptsetup open /dev/nvme0n1p6 cryptroot` → repeat §7.6 chroot exactly (crypttab line + `update-initramfs -u -k all`). Fixes ~all of R6.
- **14.3 Boot menu wrong / an OS missing:** Esc menu always has both real entries. From Ubuntu: `sudo update-grub` (re-probes Windows); `efibootmgr -v` + `efibootmgr -o XXXX,YYYY` to reorder. From BIOS: pick boot order directly.
- **14.4 ESP damaged/formatted (R4 worst case):** Windows recovery USB → Command Prompt → `diskpart` (`sel disk 0`, `sel part 1`, `assign letter=S`) → `bcdboot C:\Windows /s S: /f UEFI`. Then reinstall GRUB from an Ubuntu live chroot (`grub-install --efi-directory=/boot/efi`).
- **14.5 BitLocker demands the key repeatedly:** enter key → Windows up → `manage-bde -protectors -disable C:` → one reboot cycle → `-enable`. Persistent loops mean firmware boot config keeps changing (check you're not toggling Secure Boot / boot order each boot).
- **14.6 Second screen breaks after a kernel update:** boot previous kernel (GRUB → Advanced) → `sudo apt-mark hold linux-image-generic-hwe-24.04 linux-generic-hwe-24.04` until fixed upstream; report with doctor output. This is R5/V9's living mitigation.
- **14.7 Nuclear:** full restore from the pre-project disk image; Windows recovery USB; ASUS Cloud Recovery (needs internet, wipes disk).

---

## 15. Deferred / out of scope (deliberately)

- IR **face unlock** (Howdy on new Intel IR stacks: unreliable; revisit post-v1.0)
- **NPU** (`intel_vpu` firmware blob works per NixOS reports; no daily-driver need yet)
- **Thermal/fan profiles** via ACPI DEVID `0x00110019` debugfs experiments (only after everything else is stable, bracketed by Timeshift + GA kernel)
- ScreenXpert-style gestures / six-finger virtual keyboard (no Linux equivalent; GNOME's OSK appears when the keyboard is absent)
- **Hibernation** (s2idle machine; encrypted-swap complexity not worth it)
- **Any EC / keyboard-MCU / panel firmware flashing from Linux — never** (R12)

---

## 16. Appendices

### 16.1 Hardware quick reference

| Thing | Value |
|-------|-------|
| Model | ASUS Zenbook Duo (2024) UX8406MA (Meteor Lake; Core Ultra 7 155H / 9 185H) |
| Panels | 2× 14" OLED touch, eDP-1 (top) / eDP-2 (bottom), FHD@60 or 3K@120 |
| iGPU | Intel Arc (Xe-LPG), PCI `8086:7d55`, driver i915 (xe: watch item) |
| Keyboard | USB (pogo) + BT, `0b05:1b2c`, hid-asus (generic; no device-specific entry upstream — V8) |
| Digitizers | top ELAN9008 `04F3:4259` · bottom ELAN9009 `04F3:42EC` |
| Wi-Fi | Intel AX211 typical (BE200 possible — doctor reports) |
| Audio | Intel SOF `sof-audio-pci-intel-mtl`, harman/kardon |
| Battery | 75 Wh, `BAT0`, charge limit sysfs (asus-wmi) |
| Suspend | s2idle only |
| BIOS | 312 (2026-03-10); F2 setup, Esc boot menu; EZ-Flash for USB updates |

### 16.2 Command cheat-sheet

```
duo doctor                     # full hardware/health probe (safe anywhere, incl. live USB)
duo status                     # panels, keyboard, backlight, battery limit at a glance
duo top|bottom|both|toggle     # manual panel control (refuses all-off)
duo kb-backlight 0..3          # native LED if present, else hidraw fallback
duo bat-limit 80               # charge threshold
sudo make system HOST=zenbook-duo   # (re)apply system layer — idempotent
sudo make system HOST=zenbook-duo DRY_RUN=1   # preview what would change
sudo bash system/run.sh --host zenbook-duo --dry-run   # same, without make
      # NB: `DRY_RUN=1 sudo ...` does NOT work — sudo's env_reset strips it and
      # the "preview" would really apply the changes. Pass it as a make argument
      # or use the --dry-run flag.
home-manager switch --flake path:.#zenbook-duo -b backup   # path: includes user-config.nix
manage-bde -protectors -disable C: -RebootCount 3    # Windows: suspend BitLocker
```

### 16.3 Sources (verification round, 2026-07-21)

- Ubuntu 24.04.4 / 6.17 HWE + Mesa 25.2: Phoronix "Ubuntu 24.04.4 LTS Now Available With Linux 6.17 HWE Kernel"; OMG!Ubuntu; UbuntuHandbook (Jan–Feb 2026)
- ASUS UX8406MA BIOS support page (312 @ 2026-03-10, 15.21 MB)
- github.com/alesya-h/zenbook-duo-2024-ux8406ma-linux — README + **LICENSE: BSD-2-Clause** (re-fetched 2026-07-21)
- github.com/Fmstrat/zenbook-duo-linux — README; GPL-3.0; Ubuntu 25.10/UX8406CA status table (re-fetched 2026-07-21)
- Mainline `drivers/hid/hid-asus.c` (torvalds/linux master, fetched 2026-07-21): no `0x1b2c` device entry; `QUIRK_HID_FN_LOCK`, `asus_kbd_backlight_work` payload `{FEATURE_KBD_REPORT_ID, 0xba, 0xc5, 0xc4, level}` present
- `JowiAoun/dome` — full tree read directly in this session
- NixOS Discourse "Asus Zenbook Duo (2024 / UX8406MA)" thread (panel-sync firmware note; `i915.enable_psr=0`)
- Prior research docs: [`research/`](research/) (claims individually tagged in §2)
