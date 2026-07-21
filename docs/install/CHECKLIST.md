# Install-day checklist

Condensed tick-list for the Ubuntu 24.04.4 dual-boot install on the UX8406MA.
**Read this on a phone/second machine while the laptop is busy.** Every item
references the full procedure in [PLAN.md](PLAN.md) — when anything surprises
you, stop and read the referenced section before continuing.

Legend: ⛔ = hard gate, do not pass on a failure.

## 0 · Before you start (off-machine)

- [ ] BitLocker recovery key saved off-machine, ID matches `manage-bde -protectors -get C:` (§4 A1)
- [ ] Disk image / backup verified restorable
- [ ] Ubuntu LUKS passphrase chosen; stored with the BitLocker key
- [ ] Two USB sticks at hand (≥16 GB recovery, ≥8 GB installer)
- [ ] AC power available for the whole session

## A · Windows prep (§4, ~1–2 h)

- [ ] A2 BIOS updated to **312** via MyASUS (AC power, don't interrupt)
- [ ] A3 Other MyASUS firmware/driver updates applied
- [ ] A4 `powercfg /h off` (Fast Startup + hibernation off)
- [ ] A5 UTC clock: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f` → reboot
- [ ] A6 Windows **recovery USB** created (stick #1) and boot-tested via Esc
- [ ] A7 C: shrunk by **209920 MB** (~205 GB unallocated) — Disk Management only
- [ ] A9 `chkdsk C: /scan` clean
- [ ] A10 `ubuntu-24.04.4-desktop-amd64.iso` downloaded, SHA256 verified
- [ ] A11 ISO written to stick #2 (Rufus GPT/UEFI or Ventoy), boot-tested
- [ ] A12 This repo copied onto stick #2 (`duo/bin/duo` present)
- [ ] A13 **BitLocker suspended**: `manage-bde -protectors -disable C: -RebootCount 3` (do B/C/D in one sitting)

## B · BIOS (§5, ~10 min)

- [ ] Every settings page photographed BEFORE changes
- [ ] Secure Boot **ON** (leave it) · VMD/RST **look, don't touch** · Fast Boot **off** · TPM on

## C · ⛔ Live-USB gate (§6, zero disk writes)

- [ ] Esc-boot stick #2 → **Try Ubuntu** (NOT Install)
- [ ] Wi-Fi connected
- [ ] `bash <stick>/dome/duo/bin/duo doctor | tee ~/doctor-live.txt` → **no MUST failures**
- [ ] Keyboard types attached; detach → **Wi-Fi stays up**; BT pair (left switch, PIN) → types detached
- [ ] Both screens touch-respond (mis-mapping OK, dead touch NOT)
- [ ] Audio + camera tried (record result; not blocking)
- [ ] 5× attach/detach — no crash/flicker storm
- [ ] `doctor-live.txt` saved to the stick

**GO** = NVMe visible · both panels render · keyboard USB+BT · touchpad · Wi-Fi survives detach.
**Anything MUST fails → power off, nothing was written (§6 NO-GO).**

## D · Partition + install (§7, same live session)

- [ ] 7.1 `lsblk` + `parted print` — record actual partition numbers (expect p1 ESP / p2 MSR / p3 C: / p4 WinRE)
- [ ] 7.2 GParted, in free space ONLY: `p5` 2 GiB ext4 label `duo-boot` · `p6` rest **unformatted**
- [ ] 7.3 LUKS:
      `sudo cryptsetup luksFormat --type luks2 /dev/nvme0n1p6`
      `sudo cryptsetup open /dev/nvme0n1p6 cryptroot`
      `sudo mkfs.ext4 -L duo-root /dev/mapper/cryptroot`
- [ ] 7.4 Installer → "Something else": p1 → `/boot/efi` **FORMAT UNTICKED** ⛔ · p5 → `/boot` ext4 format ✓ · `/dev/mapper/cryptroot` → `/` no format · bootloader → `/dev/nvme0n1`
- [ ] ⛔ Summary screen read TWICE — any mention of formatting p1 or touching p3 → Back
- [ ] Install finishes → **"Continue testing" — DO NOT REBOOT**
- [ ] 7.6 Chroot fix (crypttab + initramfs + os-prober) — follow the block in PLAN.md §7.6 verbatim; `update-grub` must print **"Found Windows Boot Manager"**
- [ ] `sudo umount -R /mnt` → remove USB → reboot

## E · First boot (§8, ~45 min)

- [ ] E1 GRUB shows **Ubuntu + Windows Boot Manager**
- [ ] E2 LUKS passphrase → GNOME desktop
- [ ] E3 ⛔ Windows boots via GRUB **and** via Esc menu (recovery-key prompt once = expected worst case)
- [ ] E4 `manage-bde -status C:` → Protection On (re-enable if not)
- [ ] E5 Ubuntu: `sudo apt update && sudo apt full-upgrade`
- [ ] E6 `uname -r` = 6.17.x · `timedatectl` RTC in UTC
- [ ] E7 `git clone https://github.com/JowiAoun/dome ~/.dotfiles && cd ~/.dotfiles`
- [ ] E8 `sudo make system HOST=zenbook-duo` → reboot → `cat /proc/cmdline` has `i915.enable_psr=0`; GRUB Advanced lists 6.8.x fallback
- [ ] E9 Suspend 2 min → resumes, Wi-Fi back
- [ ] E10 `duo doctor` on the installed system; compare with `doctor-live.txt`
- [ ] `./install.sh --host zenbook-duo` (Nix + home-manager layer)

## If something breaks

| Symptom | Go to |
|---------|-------|
| First boot drops to busybox/initramfs | PLAN.md §14.2 (repeat chroot fix) |
| An OS missing from boot menu | §14.3 |
| ESP damaged / Windows won't boot | §14.4 |
| BitLocker loops on the recovery key | §14.5 |
| Second screen dead after kernel update | §14.6 |
| Want Ubuntu gone entirely | §14.1 |
