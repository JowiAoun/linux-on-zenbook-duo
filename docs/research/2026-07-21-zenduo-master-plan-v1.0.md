# ZenDuo Master Plan

## Dual-booting Ubuntu 24.04 LTS on the ASUS Zenbook Duo (2024) UX8406MA — and evolving `dome` to make it reproducible

> **Status:** v1.0 — 2026-07-21 · Author: Claude (Cowork session) with Jay
> **Scope:** From a working Windows 11 machine (backed up, BitLocker key saved) to a safe, fully-tooled Ubuntu 24.04 dual boot, with the `dome` repo evolved to reproduce the whole setup, including our **own** Duo hardware tooling (working name: **`zenduo`**).
> **Prime directive:** *Never take a step that can't be undone.* Every phase below has an explicit verification gate and a rollback path. Phases are ordered so that all destructive operations happen as late as possible, after the hardware has proven itself on a live USB.

---

## 0. How to read this plan

- Phases **A–E** get Ubuntu installed safely (one to two evenings).
- Phases **F–H** build out `dome` (system layer, Nix user layer, `zenduo` tooling) — iterative, low risk, mostly reversible with `git` + Timeshift.
- Phase **I** is the acceptance test matrix; Phase **J** is day-2 maintenance.
- ⛔ marks **hard gates**: do not continue past them until the gate criteria pass.
- 🔧 marks steps automated by scripts already scaffolded in this repo (`system/`, `duo/`).
- Anything labeled **VERIFY-ON-HW** is a claim we could not fully confirm from sources and must be tested on the machine before relying on it.

---

## 1. Decisions (locked) and assumptions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Distribution | **Vanilla Ubuntu 24.04.4 LTS** (GNOME, Wayland) | See §1.1 — ratified over Arch below |
| D2 | Disk split | **~200 GB for Ubuntu**, Windows keeps the rest | Jay's choice; conservative shrink, Windows stays the BIOS-update/fallback OS |
| D3 | Encryption | **LUKS2 + passphrase** for Ubuntu root; separate unencrypted 2 GB `/boot`; Windows keeps BitLocker | Laptop theft protection on both OSes; §7 handles the installer's LUKS gap |
| D4 | Repo architecture | **Hybrid**: keep home-manager flake (user layer) + new idempotent bash **system layer** + `hosts/` profiles | Jay ratified the research recommendation; WSL/Codespaces flows keep working |
| D5 | Duo tooling | **Write our own (`zenduo`)**, using alesya-h & Fmstrat as *prior art only* | Jay's choice. ⚠ Licensing note in §11.2 — Fmstrat is GPL-3.0, alesya-h's license is unverified, so we reimplement clean-room and only borrow *interfaces and ideas*, not code |
| D6 | Boot chain | **GRUB on the existing Windows ESP** (no format!), Secure Boot **stays ON**, `os-prober` enabled | Ubuntu's signed shim works with Secure Boot; one ESP avoids firmware confusion |
| D7 | Kernel policy | **HWE 6.17 stack** (default on 24.04.4) + **GA 6.8 installed as fallback** | Newest well-tested kernel for this hardware; a known-good escape hatch in GRUB |
| D8 | Swap | 8 GB **swapfile inside encrypted root**; no hibernation | Machine is s2idle-only; hibernate isn't worth the complexity |
| D9 | Clock | Windows switched to **UTC RTC** via registry | More robust than making Linux use local time |
| D10 | Desktop | **GNOME on Wayland** (Ubuntu default) | All Duo display tooling depends on Mutter's D-Bus API; KDE/X11 out of scope |

### 1.1 Arch vs vanilla Ubuntu — recommendation: **vanilla Ubuntu 24.04.4**

You asked directly, so here is the reasoning, not just the verdict:

**Why Ubuntu wins for this project:**

1. **The kernel-freshness argument for Arch has mostly expired.** In 2024–2025, Arch's edge was getting Duo enablement (the 6.11 Wi-Fi-detach fix, HID keyboard work, firmware sync fixes) months early. As of Feb 2026, Ubuntu 24.04.4 ships the **6.17 HWE kernel + Mesa 25.2** out of the box — at or past the point where the UX8406MA's known kernel-side fixes landed. The remaining gaps (auto display toggle, rotation, brightness sync, tablet mapping) are **userspace** problems that `zenduo` solves identically on any distro.
2. **Your stated constraint is "be extremely careful and break nothing."** Arch is a rolling target: kernel bumps arrive weekly and *this exact machine* has already been burned by one (the i915 6.9-line second-screen regression hit Arch users first, tracked in Arch's own packaging issue #72). On LTS, kernels move only when *you* move them, Timeshift snapshots bracket every change, and a known-good kernel stays installed.
3. **Your whole stack is already Ubuntu-shaped.** `dome` targets WSL + Codespaces (both Ubuntu), `bootstrap.sh` assumes apt-adjacent environments, and the hybrid architecture (D4) gets you *fresh userspace tools through Nix anyway* — you get Arch-like tool freshness in the user layer on top of an LTS base. That combination is strictly better for you than Arch alone.
4. **Community path is widest here.** The reference implementations (alesya-h, Fmstrat) and most UX8406 success reports are GNOME-first, and Fmstrat validates specifically against Ubuntu releases.

**What you'd give up (honestly):** day-0 mainline kernels (matters again only if a *new* must-have fix lands upstream — mitigation: Ubuntu mainline-kernel PPA on demand), the AUR (Nix layer covers this), and the Arch wiki (still readable from Ubuntu 🙂).

**Middle path if you ever want it:** Fedora Workstation tracks kernels ~1–2 versions behind mainline with more polish than Arch — it's the tinkerer's compromise. Not needed today.

---

## 2. Verified research baseline

Everything the previous agent claimed, re-checked on 2026-07-21. ✅ = independently re-verified now, 📄 = well-sourced in the research and consistent with other evidence (not re-verified), ❓ = could not confirm — plan treats it as unknown.

| # | Claim | Status | Consequence for the plan |
|---|-------|--------|--------------------------|
| V1 | Ubuntu 24.04.4 (Feb 2026) ships **6.17 HWE + Mesa 25.2** | ✅ (Phoronix, OMG!Ubuntu, UbuntuHandbook) | Install 24.04.4 directly; **no kernel dance needed** — this simplifies the original research's "install then upgrade kernel" flow |
| V2 | Latest BIOS = **312, 2026-03-10** | ✅ (ASUS support page) | Phase A updates BIOS from Windows before anything else |
| V3 | `dome` repo inventory (flake w/ impure `$USER`, `home.nix`, `modules/{python,node,java,ai}.nix`, `bootstrap.sh`, templates) | ✅ (read via project sync + GitHub) | Migration plan in §10 matches reality. **New finding:** `node_modules/`, `package-lock.json`, `.node-version` are committed — cleanup in §10.5 |
| V4 | alesya-h repo: `duo` script w/ watch-displays, backlight sync, bat-limit, kb-backlight (pyusb), tablet mapping; GNOME-specific; deps `gnome-monitor-config`, `usbutils`, `inotify-tools`, `iio-sensor-proxy`, `python3`+pyusb | ✅ (README re-fetched; 119★) | `zenduo` reimplements this feature set; we replace the unpackaged `gnome-monitor-config` build-dep with direct Mutter D-Bus calls |
| V5 | Fmstrat repo: systemd-based; tested **Ubuntu 25.10 / UX8406CA**; status table says **Fn keys still only partial and detached-keyboard backlight broken even there** (kernel 6.17) | ✅ (README re-fetched; GPL-3.0) | Temper expectations: even on 6.17, assume Fn keys/backlight need userspace help until proven otherwise (**VERIFY-ON-HW** via `duo doctor` + `duo fn-probe`) |
| V6 | Keyboard-detach kills Wi-Fi; fixed by asus-wmi quirk in **kernel ≥ 6.11** | 📄 (patch author + user confirmation cited in research) | 6.17 inherits the fix; live-USB gate explicitly tests detach → Wi-Fi survives |
| V7 | Touch/pen per-panel mapping needs Mutter MR 3556 + libwacom #640, both merged; GNOME 46+ | 📄 | Ubuntu 24.04 = GNOME 46 → should work; acceptance test I-13 confirms |
| V8 | Exact first kernel with **native** Duo kb backlight/Fn keys (hid-asus) | ❓ (research itself flagged this; LKML shows ASUS kbd-backlight HID rework still iterating at v10 in Dec 2025) | `zenduo` **probes native support first** (`/sys/class/leds/asus::kbd_backlight`) and falls back to its own HID tool; no assumption baked in |
| V9 | i915 second-screen regression (6.9+ line) — status on 6.17 | ❓ (Arch GitLab + kernel.org sources bot-walled during verification) | ⛔ Live-USB gate (Phase C) proves both panels **before any disk change**; `i915.enable_psr=0` kept; GA 6.8 fallback kernel installed |
| V10 | Hardware IDs: kbd USB `0b05:1b2c`; digitizers ELAN9008 `04F3:4259` (top) / ELAN9009 `04F3:42EC` (bottom); iGPU `8086:7d55`; panels eDP-1/eDP-2 | 📄 (inxi dumps in research) | Baked into `duo doctor` checks and tablet-mapping config |
| V11 | Audio: SOF `sof-audio-pci-intel-mtl`; early-kernel "dummy output" issues; one woofer pair enabled by quirk, second needs SPI/_DSD work — "close to Windows but not equal" | 📄 | On 6.17 + current firmware expect working audio with slightly-sub-Windows speaker fullness; test in gate; **known limitation**, not a blocker |
| V12 | Battery charge limit via `/sys/class/power_supply/BAT?/charge_control_end_threshold` | 📄 (standard asus-wmi) | `duo bat-limit` uses it; doctor verifies the node exists |
| V13 | Suspend: **s2idle only**, historical MTL drain issues | 📄 | Accept; measure overnight drain in Phase I; no hibernation (D8) |
| V14 | Raw udev rules on the pogo keyboard cause an **event storm** (many sub-devices) — poll `lsusb` instead | 📄 (alesya-h & Fmstrat both converged on polling) | `zenduo watch-displays` polls at 1 Hz with debounce; no udev triggers for attach/detach |
| V15 | Wi-Fi module is typically **Intel AX211** (well supported); some units may have BE200 (suspend quirks) | 📄 | `duo doctor` reports which card is present; contingency noted in §14.6 |
| V16 | Intel VMD/RST could hide the NVMe from the installer | ❓ (no UX8406-specific reports either way) | Phase B *looks but does not touch* the BIOS storage setting; Phase C checks `lsblk` sees the disk — if it does, VMD is a non-issue; **never toggle the BIOS storage mode** (breaks the existing Windows install) |
| V17 | ASUS on LVFS/fwupd: limited coverage; BIOS updates via MyASUS (Windows) or EZ-Flash (USB) | 📄 | Keep Windows partition as the firmware-update OS (D2); never flash EC/keyboard/panel firmware from Linux |
| V18 | Upstream repos "not pushed to anymore" (Jay's assumption behind D5) | ⚠ Partially true at best | Fmstrat has 25.10-era updates (recent); alesya-h's last-commit date couldn't be confirmed (API rate-limited). D5 (own tooling) stands on its own merits — control + maintenance — but both repos stay valuable as living references; §13.4 puts them on the watch list |

---

## 3. Risk register and safety rails

| # | Risk | L×I | Prevention | Detection | Response |
|---|------|-----|------------|-----------|----------|
| R1 | Windows unbootable after partitioning | Low × Critical | Shrink **only** from Windows Disk Management; never move/resize NTFS from Linux; never touch p1–p4 | Windows boot test in D8 | §14.3 boot-order repair; recovery USB; restore image |
| R2 | BitLocker recovery loop after GRUB install | Med × High | **Suspend BitLocker** (`-RebootCount 3`) before install; Secure Boot left ON; key saved (done ✅) | First Windows boot after GRUB | Enter recovery key once; resume protectors; §14.5 |
| R3 | Data loss during shrink | Low × Critical | Backup already done ✅; BitLocker suspended; shrink leaves NTFS internally consistent | chkdsk after shrink | Restore from backup |
| R4 | **ESP accidentally formatted** in installer (the #1 dual-boot killer) | Med × Critical | Manual partitioning walkthrough in §7 with explicit "Do **not** tick format on p1"; screenshot checklist | Installer summary screen review (mandatory pause) | If formatted: §14.4 rebuild Windows boot files from recovery USB (`bcdboot`) |
| R5 | Second screen dead on 6.17 (V9 unknown) | Low-Med × Med | ⛔ Phase C proves panels on live USB **before** install | `duo doctor` panel check | No-go → investigate (mainline PPA live test) with zero disk changes made |
| R6 | LUKS system unbootable on first boot (installer doesn't write `crypttab` for pre-made LUKS) | **High** × Med | §7.6 chroot step adds `crypttab` + rebuilds initramfs **before** first reboot — treat as mandatory, not optional | First boot passphrase prompt appears | §14.2 live-USB unlock + chroot repair (exact commands provided) |
| R7 | Secure Boot blocks something | Low × Med | Stock Ubuntu shim/kernels are signed; no DKMS modules planned | Boot failure w/ SB error | Temporarily disable SB to diagnose; MOK enrollment only if we ever add DKMS |
| R8 | Laptop cooks in a bag (s2idle wake) | Med × Med | Test suspend in Phase I; set lid-close = suspend + check `/sys/power/mem_sleep`; consider `s2idle`+screens-off verification | Warm-bag test, battery drain % overnight | Tune wakeup sources (`/proc/acpi/wakeup`); worst case power-off before transport |
| R9 | A Windows or GRUB update breaks the boot menu | Med × Low | Windows keeps its own bootmgr entry (chainloaded); firmware boot menu (Esc) always works | Boot menu missing an OS | §14.3 `efibootmgr`/BIOS boot-order fix; `update-grub` re-detects Windows |
| R10 | **Our own tooling turns both screens off** | Med × Med | Hard invariant in `zenduo`: refuse any display config with zero enabled panels; keyboard-attach always restores top-only; Ctrl+Alt+F3 TTY as last resort | You're staring at two black screens | Attach keyboard (poller re-enables top); TTY `duo both`; `loginctl terminate-session` worst case |
| R11 | License contamination in `zenduo` | Med × Med (legal/hygiene) | §11.2 rules: no code copied from GPL-3.0 Fmstrat; alesya-h treated the same until license verified; kernel constants are facts, fine to use | Code review before each commit | Rewrite tainted code clean-room |
| R12 | Bricking via firmware flashing from Linux | — | **Out of scope, forever**: no EC, keyboard-MCU, or panel-firmware flashing from Linux. BIOS via MyASUS/EZ-Flash only | — | — |

**Standing safety rails through every phase:**

1. BitLocker recovery key + Windows recovery USB exist *off-machine* before Phase A completes.
2. Nothing writes to disk until the ⛔ Phase C gate passes.
3. The installer summary screen gets a full stop-and-read before clicking Install (R4).
4. No reboot after install until the §7.6 chroot fix is done (R6).
5. Timeshift snapshot before every `make system` run once Ubuntu is up.
6. Windows partition is sacred: we never resize, move, defragment, or "clean up" p1–p4 from Linux.
---

## 4. Phase A — Windows-side preparation (~1–2 h active)

**Goal:** Windows fully prepared, firmware current, 200 GB carved out, install media ready. Everything here is done *in Windows*.
**Preconditions:** Backup verified restorable (✅ done per Jay); BitLocker recovery key saved off-machine (✅ done — double-check it's legible and matches: `manage-bde -protectors -get C:`).

| Step | Action | Command / location | Verify |
|------|--------|--------------------|--------|
| A1 | Confirm BitLocker key really matches this volume | Admin PowerShell: `manage-bde -protectors -get C:` → compare the Numerical Password ID with your saved key's ID | ID matches saved key |
| A2 | **Update BIOS to 312** (2026-03-10) | MyASUS → Customer Support → Live Update (or download `UX8406MA` BIOS 312 from ASUS support + run) | After reboot, BIOS shows 312. ⚠ Plugged into AC; do not interrupt |
| A3 | Update other firmware/drivers offered by MyASUS (ME, touchpad, etc.) | MyASUS Live Update | No pending critical updates |
| A4 | Disable Fast Startup (prevents dirty NTFS + surprise hibernation state) | Admin PowerShell: `powercfg /h off` (also removes hiberfile, frees disk) | `powercfg /a` no longer lists Hibernate/Fast Startup |
| A5 | Set hardware clock to UTC (kills dual-boot clock drift at the source) | Admin PowerShell: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f` then reboot | Windows clock still correct after reboot |
| A6 | Create a **Windows recovery USB** (≥16 GB stick #1) | Search "Create a recovery drive", include system files | Stick boots (test via Esc boot menu) |
| A7 | Free up & shrink C: by **~205 GB** | `diskmgmt.msc` → right-click C: → Shrink Volume → enter `209920` MB | ~205 GB shows as *Unallocated* after C: |
| A8 | If shrink offers less than ~205 GB (unmovable files) | Temporarily: disable pagefile (System → Advanced → Performance → Virtual memory), disable System Restore on C:, `powercfg /h off` (done), reboot, retry shrink. **Re-enable pagefile after.** Do *not* use third-party partition tools on a BitLocker volume | Shrink succeeds |
| A9 | Run a disk health check | `chkdsk C: /scan` | No errors |
| A10 | Download **Ubuntu 24.04.4 desktop ISO** + verify | From ubuntu.com/download; PowerShell: `certutil -hashfile ubuntu-24.04.4-desktop-amd64.iso SHA256` → compare to SHA256SUMS on ubuntu.com | Hash matches exactly |
| A11 | Write ISO to USB stick #2 (≥8 GB) | Rufus (GPT / UEFI-non-CSM, default ISO mode) or Ventoy | Stick boots to Ubuntu menu |
| A12 | Stage this repo where the live session can reach it | Copy the `dome-evolution/` folder (or a clone of `dome` once merged) onto USB stick #2's data partition (Ventoy makes this trivial) | `duo/bin/duo` present on the stick |
| A13 | **Suspend BitLocker** (immediately before proceeding to Phase B/C/D in one sitting) | Admin PowerShell: `manage-bde -protectors -disable C: -RebootCount 3` | `manage-bde -status C:` → "Protection Off (3 reboots remaining)". Auto-re-arms after 3 boots — a deliberate dead-man switch |
| A14 | Note machine specifics for the record | `msinfo32`: SSD model, RAM, BIOS mode (UEFI), Secure Boot state (On) | Values recorded in `docs/hardware.md` later |

**Rollback:** everything in Phase A is non-destructive. The shrink can be undone by extending C: back over the unallocated space. BitLocker re-arms itself after 3 reboots (or `manage-bde -protectors -enable C:`).

---

## 5. Phase B — BIOS configuration (~10 min)

**Goal:** Know the firmware state; change the minimum possible.

1. Reboot; hold **F2** at the ASUS logo → BIOS setup. (**Esc** = one-time boot menu — you'll use it constantly.)
2. **Photograph every settings page** before touching anything (your "factory state" record).
3. Confirm / set:
   - **Secure Boot: ON** — leave it. Ubuntu's shim is signed (D6). Don't clear keys, don't enter setup mode.
   - **Storage / VMD / Intel RST setting: LOOK, DON'T TOUCH** (V16). Just record what it says. If Phase C's live session sees the NVMe (it almost certainly will — kernel 6.17 has VMD support), the setting is fine as-is. Toggling it would likely make **Windows** unbootable (its storage driver is bound to the current mode) — that's R1 territory.
   - **Fast Boot (BIOS): Disable** — makes F2/Esc reliably catchable; harmless.
   - TPM/fTPM: leave enabled (BitLocker needs it).
4. Save & exit.

**Rollback:** re-enter BIOS, restore from your photos. Nothing here touches the disk.

---

## 6. Phase C — ⛔ Live-USB validation gate (~30–60 min, zero disk writes)

**Goal:** Prove the hardware works on the exact kernel we're about to install — **before** any disk modification. This gate exists chiefly because of V8/V9 (unconfirmed keyboard-native support and i915 second-screen status).

1. Esc-boot into USB stick #2 → **"Try Ubuntu"** (do *not* pick Install).
   - If both screens stay black → reboot, pick "Ubuntu (safe graphics)", record that fact (it means the default modesetting path has an issue; we'd investigate before installing).
2. Connect Wi-Fi. Open a terminal.
3. Run the doctor from the stick: `bash /path/to/duo/bin/duo doctor | tee ~/doctor-live.txt` 🔧
   It checks, read-only: kernel version (expect 6.17.x), both eDP panels present & enabled, GNOME/Mutter D-Bus reachable, keyboard `0b05:1b2c` on USB, `hid_asus` loaded, **native kbd-backlight LED node presence (V8 answered here)**, ELAN digitizers (top `04f3:4259`, bottom `04f3:42ec`), IIO sensors, SOF audio device, Wi-Fi card model (AX211 vs BE200, V15), NVMe visibility (V16 answered here), VMD controller presence, battery `charge_control_end_threshold`, `platform_profile`, `mem_sleep` (expect `s2idle`), suspicious dmesg lines (i915/asus/sof).
4. Manual spot checks (5 minutes, tick them off):
   - Type on the keyboard **attached**; detach it → **does Wi-Fi stay up?** (V6); pair it over **Bluetooth** (left-side switch, 6-digit PIN) and type detached.
   - Touch **both** screens; note whether bottom touch lands on the bottom screen or is mis-mapped to top (V7 — mis-mapping is fine, `zenduo` fixes it; *dead* touch is not).
   - Play audio (speakers + jack). Try the camera (Cheese/Snapshot).
   - Brightness Fn keys; note *which* Fn keys emit anything (feeds `duo fn-probe` data).
   - Attach/detach the keyboard 5× in a row — any desktop crash/flicker storm? (V14)
5. Save `doctor-live.txt` to the USB stick (it becomes `docs/hardware.md` raw material and our V8/V9/V15/V16 ground truth).

**GO criteria (all must pass):** NVMe visible · both panels render · keyboard works attached (USB) *and* detached (BT) · touchpad · Wi-Fi up and survives detach.
**SHOULD pass (record if not, not blocking):** audio, camera, both-panel touch, sensors, backlight LED node.
**NO-GO:** any MUST fails → power off. Nothing was written. We regroup (e.g. test a mainline-PPA kernel from another live env, check firmware) before ever touching the disk.

---

## 7. Phase D — Partitioning & installation (~1–2 h)

**Goal:** Ubuntu 24.04.4 installed into the 205 GB gap with LUKS2 root, reusing the existing ESP, Windows untouched.

**Preconditions:** Phase C gate passed · BitLocker suspended (A13, within its 3-reboot window) · AC power connected.

### 7.1 Map the disk (live session, read-only)

```
lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL,MOUNTPOINTS /dev/nvme0n1
sudo parted /dev/nvme0n1 print
```

Expected existing layout (typical ASUS ship state — **record your actual numbers**):
`p1` ESP ~260 MB (FAT32) · `p2` MSR 16 MB · `p3` Windows C: (BitLocker) · `p4` WinRE ~1 GB · then **~205 GB free space**.
⚠ If your partition numbers differ, substitute accordingly *everywhere below*. Never touch p1–p4 beyond mounting p1 read-write as the ESP.

### 7.2 Create the two new partitions (GParted, live session)

In the free space, create — and nothing else:

- `p5`: **2 GiB, ext4**, label `duo-boot` → will be `/boot` (unencrypted, holds kernels/initramfs; GRUB reads it without LUKS headaches)
- `p6`: **remaining ~203 GiB, unformatted** → will be the LUKS2 container

Apply. Double-check p1–p4 untouched in the GParted log.

### 7.3 Create the LUKS2 container (terminal)

```
sudo cryptsetup luksFormat --type luks2 /dev/nvme0n1p6      # type YES + strong passphrase
sudo cryptsetup open /dev/nvme0n1p6 cryptroot
sudo mkfs.ext4 -L duo-root /dev/mapper/cryptroot
```

The passphrase is now a **second critical secret** — store it with the BitLocker key (off-machine). Losing it = losing the Ubuntu install.

### 7.4 Run the installer (still same live session)

Ubuntu 24.04.4's desktop installer → **Manual installation** ("Something else") — the guided modes can't do this layout, and its manual mode has no LUKS creation UI, which is why we pre-made it in 7.3 (R6):

| Device | Use as | Format? | Mount point |
|--------|--------|---------|-------------|
| `nvme0n1p1` (the existing ~260 MB FAT32 ESP) | EFI System Partition | **☐ NO — do not tick** (R4!) | `/boot/efi` |
| `nvme0n1p5` | ext4 | ☑ yes | `/boot` |
| `/dev/mapper/cryptroot` | ext4 | ☐ no (freshly made in 7.3) | `/` |
| *Bootloader install device* | `/dev/nvme0n1` (the disk) | — | — |

⛔ **Stop at the summary screen.** Read it twice. It must list: format p5, use p1 as ESP *without* format, use mapper as `/`. Any mention of formatting p1 or touching p3 → **Back**, fix, re-read. Then Install. When it finishes choose **"Continue testing" — do not reboot** (R6).

### 7.5 Why not reboot yet

The installer generally does **not** write `/etc/crypttab` for a pre-existing LUKS container, so the initramfs wouldn't know to ask for your passphrase → first boot drops to busybox. We fix it now, in chroot, in five minutes.

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
blkid /dev/nvme0n1p6        # copy the UUID=... of the LUKS partition (crypto_LUKS)
echo "cryptroot UUID=<that-uuid> none luks,discard" >> /etc/crypttab
apt-get install -y cryptsetup-initramfs   # normally already present
update-initramfs -u -k all
lsinitramfs /boot/initrd.img-$(uname -r 2>/dev/null || ls /boot | grep -oP 'initrd.img-\K.*' | head -1) | grep -m1 cryptsetup   # must print something

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
| E3 | ⛔ **Boot back into Windows — twice**: once via the GRUB entry, once via Esc→Windows Boot Manager | Windows boots both ways. If BitLocker asks for the recovery key once: enter it, continue (expected worst case, R2) |
| E4 | In Windows: `manage-bde -status C:` → protection resumed (the 3-reboot suspension has likely lapsed — good). If still off: `manage-bde -protectors -enable C:` | "Protection On" |
| E5 | Back in Ubuntu: `sudo apt update && sudo apt full-upgrade` | Clean |
| E6 | `uname -r` → **6.17.x**; `timedatectl` → RTC in UTC, time correct in both OSes (A5) | Matches |
| E7 | Install the GA fallback kernel (D7): `sudo apt install linux-generic` | GRUB "Advanced options" now lists 6.8.x too — your escape hatch |
| E8 | Install & baseline Timeshift: `sudo apt install timeshift` → rsync mode, system files only, snapshot **"post-install-clean"** | Snapshot listed |
| E9 | Run the system layer 🔧: `sudo make system` (adds `i915.enable_psr=0`, os-prober setting, base packages, Duo deps — §9) then reboot | `cat /proc/cmdline` contains `i915.enable_psr=0`; second screen still works; OLED flicker gone |
| E10 | Smoke-test suspend: close lid 2 min, reopen | Resumes; Wi-Fi back; note battery % drop |

**Ubuntu is now installed and safe.** Everything from here is iterative and Timeshift/git-protected.
---

## 9. Phase F — `dome` system layer (already scaffolded 🔧)

**Goal:** every root-level change to the machine is a **reviewable, idempotent, re-runnable script** in git — never an undocumented one-off command.

Layout (in this repo now):

```
system/
├── lib.sh              # shared helpers: log, die, require_root, DRY_RUN=1 support,
│                       #   ensure_pkg (apt install -y iff missing), ensure_line (grep-before-append),
│                       #   ensure_grub_param (add kernel param iff absent + update-grub once)
├── 00-preflight.sh     # sanity: Ubuntu 24.04?, UEFI?, not live session?, disk free
├── 10-apt-base.sh      # build-essential curl git make timeshift etc.
├── 20-kernel.sh        # ensure linux-generic-hwe-24.04 (6.17 stack) + linux-generic (GA fallback)
├── 30-grub-params.sh   # i915.enable_psr=0 · GRUB_DISABLE_OS_PROBER=false · update-grub (once, iff changed)
├── 40-duo-deps.sh      # [duo hosts only] usbutils inotify-tools iio-sensor-proxy python3-usb python3-gi
├── 50-duo-sudoers.sh   # [duo hosts only] installs /usr/local/sbin/zenduo-helper (tiny root helper,
│                       #   input-validated: only 'backlight <0-100%>' / 'batlimit <20-100>')
│                       #   + /etc/sudoers.d/zenduo (NOPASSWD for that ONE binary; validated w/ visudo -c)
│                       #   — deliberately narrower than upstream's NOPASSWD /usr/bin/env approach
└── 90-timeshift.sh     # ensure a snapshot exists before the run (invoked first by `make system`)
```

Rules: `set -euo pipefail` everywhere · every script re-runnable with zero diff the second time · `DRY_RUN=1 make system` prints what would change · scripts 40/50 run only when the host profile is `zenbook-duo` (from `user-config.nix` / `--host` flag).
**Definition of done:** `sudo make system` twice in a row → second run reports "no changes".

## 10. Phase G — `dome` user layer (Nix) migration

Ordered so nothing breaks for existing environments (WSL/Codespaces):

1. **G1 — flake v2 (scaffolded):** adds `mkHome`, explicit `username` (kills `builtins.getEnv`), and `homeConfigurations.generic` / `.zenbook-duo` keyed on host profile — while **keeping** the legacy `default/user/jaoun/codespace/vscode/codespaces` outputs during migration. Verify on your *current* machine first: `nix flake check` + `home-manager switch --flake .#generic -b backup` must reproduce today's environment exactly.
2. **G2 — split `home.nix`** into `home/common.nix` + `home/shell.nix`, move `modules/*.nix` → `home/langs/*.nix`. *Deferred until I can read the full repo contents* (see MIGRATION.md — needs the repo folder connected or pushed where I can fetch it); done as a no-behavior-change refactor with a parity check.
3. **G3 — Ubuntu-desktop niceties:** `targets.genericLinux.enable = true;` in the generic Linux host path (icons/.desktop/XDG for Nix GUI apps).
4. **G4 — GNOME dconf capture:** once the desktop is configured by hand to taste (Phase H era): `dconf dump / > dump.ini` → `dconf2nix` → `home/gnome.nix`, review, commit. From then on look-and-feel is reproducible.
5. **G5 — repo hygiene (do anytime):** `git rm -r --cached node_modules package-lock.json .node-version` + `.gitignore` additions (scaffolded in `gitignore.additions`); keep `bootstrap.sh` working for Codespaces/WSL until `install.sh` fully replaces it, then fold.
6. **G6 — secrets (later, optional):** `sops-nix` + age key per machine; never plaintext secrets in the store (flake contents are world-readable in `/nix/store`).

## 11. Phase H — `zenduo`: our own Duo tooling (the interesting part)

### 11.1 Design principles

1. **Fail-safe by construction** — the display module *refuses* any configuration that would leave zero panels enabled (R10); keyboard-attach always converges to a working state; every watcher is a user-level systemd unit you can `systemctl --user stop`.
2. **Native-first, fallback-second** — every capability probes the kernel interface first (e.g. `asus::kbd_backlight` LED class device) and only then falls back to our userspace implementation (HID feature report via pyusb). As kernels improve, `zenduo` automatically does less. `duo doctor` reports which path is active.
3. **Poll, don't storm** (V14) — keyboard presence = `lsusb`-style sysfs poll at 1 Hz with 2-cycle debounce; no udev rules on the pogo pins.
4. **Talk to GNOME properly** — display control via Mutter's `org.gnome.Mutter.DisplayConfig` D-Bus API (python3-gi), not the unpackaged `gnome-monitor-config` tool, and not xrandr (Wayland). One less build-dep, and it's the same API GNOME Settings uses.
5. **Everything observable** — `duo log` tails our journal namespace; every watcher logs state transitions.
6. **Self-contained & extractable** — `duo/` has no imports from the rest of `dome`; its own README and LICENSE; if/when it matures, `git filter-repo` (or a fresh repo + subtree copy) extracts it as Jay's standalone project ("we need to create our own repository potentially" — supported, deferred until it's proven on hardware).

### 11.2 Licensing rules (R11)

- `zenduo` is **MIT** (matches dome).
- **Fmstrat/zenbook-duo-linux is GPL-3.0: we never copy code from it.** Reading it to understand *behavior* (what to fix: BT sync, airplane-mode reset, resume re-assert) is fine; implementation must be ours.
- **alesya-h's license is unverified** (API rate-limited during research) → treated exactly like the GPL case until someone confirms: interfaces and ideas yes, code no. Command names (`watch-displays`, `bat-limit`, …) are interface, not code — we deliberately keep them compatible.
- Kernel-derived constants (USB IDs, the ASUS HID report format `5a ba c5 c4 <level>` from mainline `hid-asus.c`) are facts; using them is fine.
- Both upstreams get credited in `duo/README.md` as prior art.

### 11.3 Components (scaffolded today)

| Path | What it does | State |
|------|--------------|-------|
| `duo/bin/duo` | CLI entry point: `doctor`, `status`, `top/bottom/both/toggle`, `watch-displays`, `sync-backlight`, `watch-backlight`, `kb-backlight 0-3`, `bat-limit N`, `set-tablet-mapping`, `watch-rotation`, `fn-probe`, `log` | **doctor: complete & runnable today** (it's Phase C's gate tool). Display/backlight/battery: implemented, **VERIFY-ON-HW**. Rotation: experimental stub |
| `duo/lib/displayctl.py` | Mutter DisplayConfig D-Bus client: get state, enable/disable panels by connector (eDP-1/eDP-2), preserve scale/transform, zero-panel refusal invariant | Implemented, VERIFY-ON-HW |
| `duo/lib/kb_backlight.py` | pyusb fallback: HID SET_REPORT (feature, id `0x5a`, payload `5a ba c5 c4 <0-3>`) to `0b05:1b2c` | Implemented, VERIFY-ON-HW (harmless if the device ignores it) |
| `duo/systemd/*.service` | `duo-watch-displays`, `duo-watch-backlight`, `duo-watch-rotation` — user units, `WantedBy=graphical-session.target` | Ready; enabled by the Nix module only on the duo host |
| `modules/zenbook-duo/default.nix` | home-manager module wiring the units + PATH; `zenduo.repoPath` option points at the working tree (live-editable during development) | Ready |

### 11.4 Roadmap

- **v0.1 (now):** `duo doctor` — used at the Phase C gate. Its output (`doctor-live.txt`) resolves V8/V9/V15/V16 empirically.
- **v0.2:** manual display control + `watch-displays` proven through 20 attach/detach cycles + suspend/resume.
- **v0.3:** brightness sync (via `zenduo-helper`) + kb backlight (native or fallback per doctor).
- **v0.4:** tablet/touch mapping (dconf, per V7/V10 device IDs) + rotation watcher (tent/portrait modes).
- **v0.5:** `bat-limit`, `fn-probe` inventory, polish, docs; decide Fmstrat-parity extras (BT auto-toggle, airplane reset) based on observed need.
- **v1.0:** stable on daily use ≥2 weeks → optionally extract to its own repository.

### 11.5 Per-feature test protocol

Every feature graduates only after: 10× attach/detach cycles · survives suspend/resume · survives reboot · survives GNOME session restart (`Alt+F2 r` is X-only, so: log out/in) · no journal errors at `duo log`.

## 12. Phase I — Acceptance test matrix

Run after v0.3; re-run after every kernel update (`duo doctor` automates the top half).

| # | Feature | Test | Expected | If it fails |
|---|---------|------|----------|-------------|
| I-1 | Both panels | GNOME Displays shows eDP-1+eDP-2 | Both, 2880×1800@120 (or 1920×1200) | GA kernel boot test; §14.6 |
| I-2 | Keyboard attached | Type | Works (USB `0b05:1b2c`) | doctor; check `hid_asus` |
| I-3 | Keyboard detached | Type over BT | Works | Re-pair; BT logs |
| I-4 | Wi-Fi survives detach | Detach; ping running | No drop (V6) | Kernel < 6.11? (shouldn't be) |
| I-5 | Auto screen toggle | Attach → bottom off; detach → both on | < 2 s, no flicker storm | `duo log`; debounce tuning |
| I-6 | Kb backlight | `duo kb-backlight 2` | Visible change; note native vs fallback path | fn-probe; HID trace |
| I-7 | Fn keys | `duo fn-probe` inventory | Document what works — V5 says expect gaps | Map missing keys via GNOME shortcuts to `duo` commands |
| I-8 | Audio | Speakers, jack, mic | All output; quality ≈ Windows-ish (V11) | `firmware-sof-signed` version; alsa-info |
| I-9 | Camera | Snapshot app | Image | uvcvideo dmesg |
| I-10 | Touch top | Touch hits top | Correct panel | — |
| I-11 | Touch bottom | Touch hits bottom | Correct panel after `set-tablet-mapping` (V7) | dconf keys; libwacom version |
| I-12 | Pen | Draw both panels | Maps correctly | same as I-11 |
| I-13 | Rotation | Tent/portrait | Follows within 2 s | v0.4 iteration |
| I-14 | Brightness sync | Fn brightness | Both panels track | `zenduo-helper` perms |
| I-15 | Battery limit | `duo bat-limit 80`; charge past 80? | Stops at 80% | sysfs node (V12) |
| I-16 | Suspend | Lid close 30 min | ≤ ~2% drop, resumes clean | `/sys/power/mem_sleep`; wakeup sources |
| I-17 | Overnight suspend | 8 h | ≤ ~10% drop (V13 tolerance) | Consider deeper tuning/TLP |
| I-18 | TB4 + HDMI | External display each port | Works alongside internal panels | cable/dock specifics |
| I-19 | GRUB → Windows | Boot Windows via GRUB | No BitLocker prompt (steady state) | §14.5 |
| I-20 | Windows updates | Take a cumulative update | Boot order/menu intact | §14.3 |
| I-21 | Timeshift restore drill | Restore the pre-change snapshot onto a scratch change | Comes back | practice before you need it |

## 13. Phase J — Maintenance & day-2 operations

1. **Updates:** `apt` weekly. Before any kernel version jump: Timeshift snapshot (the `90-timeshift.sh` hook covers `make system`; for plain `apt full-upgrade` kernel bumps, snapshot manually or add an apt hook later). After: `duo doctor` + glance at I-1/I-5. Keep GA 6.8 installed forever; prune old HWE kernels only N-1.
2. **BIOS:** check MyASUS (Windows side) quarterly; EZ-Flash from USB is the no-Windows path. Never flash EC/keyboard/panel firmware from Linux (R12).
3. **Ubuntu point releases:** 24.04.5 expected ~Aug 2026 (final point release; HWE may roll again) — evaluate with a snapshot + doctor pass, no urgency.
4. **Upstream watch (monthly, ~10 min):** alesya-h repo · Fmstrat repo · `asusctl` issue #25 · NixOS Discourse UX8406MA thread · kernel `hid-asus.c` / `asus-wmi.c` changelogs. When native support for something lands, `zenduo`'s native-first probing means we usually just delete fallback code.
5. **Nix layer:** `nix flake update` monthly-ish; `home-manager switch` with `-b backup`; roll back via `home-manager generations` if needed.
6. **Windows side:** let it update freely; if it steals boot priority, fix via BIOS boot order or `efibootmgr -o` (§14.3). Windows Fast Startup stays off.

## 14. Rollback & disaster recovery

- **14.1 Remove Ubuntu entirely (full undo):** From Windows: `diskmgmt.msc` → delete p5+p6 → extend C:. Mount ESP: admin `mountvol S: /S` → `rd /s S:\EFI\ubuntu`. Boot order: BIOS → Windows Boot Manager first (or `bcdedit /set {fwbootmgr} displayorder {bootmgr} /addfirst`). Machine is factory-shaped again.
- **14.2 LUKS first boot fails (busybox/initramfs prompt):** live USB → `cryptsetup open /dev/nvme0n1p6 cryptroot` → repeat §7.6 chroot exactly (crypttab line + `update-initramfs -u -k all`). This fixes ~all of R6.
- **14.3 Boot menu wrong / an OS missing:** Esc menu always has both real entries. From Ubuntu: `sudo update-grub` (re-probes Windows), `efibootmgr -v` + `efibootmgr -o XXXX,YYYY` to reorder. From BIOS: pick boot order directly.
- **14.4 ESP damaged/formatted (R4 worst case):** Boot Windows recovery USB → Command Prompt → `diskpart` (`sel disk 0`, `sel part 1`, `assign letter=S`) → `bcdboot C:\Windows /s S: /f UEFI`. Then reinstall GRUB from Ubuntu live chroot (`grub-install --efi-directory=/boot/efi`).
- **14.5 BitLocker demands the key repeatedly:** enter key → Windows up → `manage-bde -protectors -disable C:` → reboot cycle once → `-enable`. Persisting loops mean firmware boot config keeps changing (check you're not toggling Secure Boot / boot order each boot).
- **14.6 Second screen breaks after a kernel update:** boot previous kernel (GRUB → Advanced) → `sudo apt-mark hold linux-image-generic-hwe-24.04 linux-generic-hwe-24.04` until fixed upstream; report with `doctor` output. This is R5/V9's living mitigation.
- **14.7 Nuclear:** full restore from the pre-project disk image; Windows recovery USB; ASUS Cloud Recovery (needs internet, wipes disk).

## 15. Deferred / out of scope (deliberately)

- IR **face unlock** (Howdy on new Intel IR stacks: unreliable; revisit post-v1.0)
- **NPU** (`intel_vpu` firmware blob works per NixOS reports; no daily-driver need yet)
- **Thermal/fan profiles** via ACPI DEVID `0x00110019` debugfs experiments (the one true "low-level" frontier here; only after everything else is stable, with Timeshift + GA kernel bracket)
- ScreenXpert-style gestures / six-finger virtual keyboard (no Linux equivalent; GNOME's OSK appears when keyboard absent)
- **Hibernation** (s2idle machine, encrypted swap complexity not worth it)
- **Any EC / keyboard-MCU / panel firmware flashing from Linux — never** (R12)

## 16. Appendices

### 16.1 Hardware quick reference

| Thing | Value |
|-------|-------|
| Model | ASUS Zenbook Duo (2024) UX8406MA (Meteor Lake; Core Ultra 7 155H / 9 185H) |
| Panels | 2× 14" OLED touch, eDP-1 (top) / eDP-2 (bottom), FHD@60 or 3K@120 |
| iGPU | Intel Arc (Xe-LPG), PCI `8086:7d55`, driver i915 (xe: watch item) |
| Keyboard | USB (pogo) + BT, `0b05:1b2c`, hid-asus |
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
duo kb-backlight 0..3          # native LED if present, else HID fallback
duo bat-limit 80               # charge threshold
sudo make system               # (re)apply system layer — idempotent
home-manager switch --flake .#zenbook-duo -b backup
manage-bde -protectors -disable C: -RebootCount 3    # Windows: suspend BitLocker
```

### 16.3 Sources (verification round, 2026-07-21)

- Ubuntu 24.04.4 / 6.17 HWE: Phoronix "Ubuntu 24.04.4 LTS Now Available With Linux 6.17 HWE Kernel"; OMG!Ubuntu & UbuntuHandbook coverage (Jan–Feb 2026)
- ASUS UX8406MA BIOS page (312 @ 2026-03-10)
- github.com/alesya-h/zenbook-duo-2024-ux8406ma-linux (README, 119★)
- github.com/Fmstrat/zenbook-duo-linux (README; GPL-3.0; Ubuntu 25.10/UX8406CA status table)
- github.com/JowiAoun/dome (root listing + project-synced file contents)
- NixOS Discourse "Asus Zenbook Duo (2024 / UX8406MA)" thread (firmware ≥ 2024-09 for panel sync; `i915.enable_psr=0`)
- Arch Linux packaging issue #72 (i915 second-screen regression tracking; bot-walled on re-fetch — status unconfirmed, handled by Phase C gate)
- Prior research docs in this project (claims individually tagged in §2)
