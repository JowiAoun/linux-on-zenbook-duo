# Installing Ubuntu on the Zenbook Duo, next to Windows

The condensed, as-built procedure. The full phase-gated plan it was executed
from is archived at
[../research/2026-07-21-zenduo-master-plan-v1.1.md](../research/2026-07-21-zenduo-master-plan-v1.1.md);
[CHECKLIST.md](CHECKLIST.md) is the tick-list version and
[INSTALL-LOG.md](INSTALL-LOG.md) the journal of what actually happened,
deviations included. Read the log: every trap below came from it.

**Prime directive: never take a step that cannot be undone.** Nothing writes
to the disk until the live-USB gate passes.

## 0. Before you start

- BitLocker recovery key saved **off the machine**; check the ID matches
  `manage-bde -protectors -get C:`.
- A disk image or backup you have verified restores.
- A Windows 11 ISO on a Ventoy stick doubles as the recovery drive (its
  Repair → Command Prompt has `diskpart` and `bcdboot`).
- AC power for the whole session.

## A. Windows side (1–2 h)

1. Update the BIOS with MyASUS (312 or later) while you still have Windows.
2. `powercfg /h off` as Administrator: Fast Startup and hibernation off. This
   is not optional — with it on, the speaker amps come up unprotected on the
   Linux side ([../HARDWARE.md](../HARDWARE.md#speakers)).
3. UTC clock: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f`, reboot, then resync
   (`net start w32time; w32tm /config /syncfromflags:manual /manualpeerlist:"time.windows.com,0x9" /update; w32tm /resync /rediscover`).
4. Shrink C: in Disk Management only. Expect a wall: `$MFT::$BITMAP` cannot be
   moved by Windows tooling and capped the shrink at ~53 GB on the author's
   unit. Pagefile, hibernation and shadow copies off first; in the Virtual
   Memory dialog "No paging file" does nothing until you click **Set**. The
   defrag event log names the blocking file. Two ways out: take the small
   partition and plan a clean reinstall once Windows is retired, or decrypt
   BitLocker fully and shrink with GParted from a live session.
5. `chkdsk C: /scan`.
6. Ventoy stick (GPT, Secure Boot on) with the Ubuntu ISO (SHA256 verified),
   the Windows ISO, and this repository as a folder.
7. Just before the live session: `manage-bde -protectors -disable C: -RebootCount 3`.

## B. BIOS (10 min)

F2 at the logo. Photograph every page. Secure Boot **on** (leave it). Storage /
VMD: **look, don't touch** — toggling it breaks Windows. Fast Boot off. TPM
on. Esc is the one-time boot menu you will use constantly.

## C. ⛔ Live-USB gate (30–60 min, zero disk writes)

Ventoy under Secure Boot shows `Verification failed: (0x1A) Security
Violation` the first time — expected: OK → Enroll key from disk → `VTOYEFI` →
`ENROLL_THIS_KEY_IN_MOKMANAGER.cer`. Boot the Ubuntu ISO in normal mode,
**Try Ubuntu**. Ventoy's data partition is unmountable from its own live
session; fetch the repo instead:

```bash
wget https://github.com/JowiAoun/linux-on-zenbook-duo/archive/refs/heads/main.tar.gz
tar xf main.tar.gz
bash linux-on-zenbook-duo-main/bin/duo doctor | tee ~/doctor-live.txt
```

The live home is RAM: photograph or upload the output. Then by hand: type
attached; detach → Wi-Fi stays up; pair over Bluetooth (F10 long-press) and
type detached; touch both screens; play audio; attach/detach five times.

**GO:** NVMe visible, both panels render, keyboard USB + BT, touchpad, Wi-Fi
survives detach. **Anything MUST-fails: power off.** Nothing was written.

## D. Partition and install (1–2 h)

- `lsblk` and `sudo parted /dev/nvme0n1 print free`. The factory layout has
  **five** partitions; the free space is between `p3` and `p4`; `p1` and the
  hidden `p5` are near-identical FAT32 twins — the ESP is `p1` (flags
  `boot, esp`, start of the disk).
- GParted: create `/boot` (2 GiB ext4) and the root partition in the free
  space. After Apply, `lsblk` — GParted has created only the first of two
  queued partitions before. Check numbering before any `cryptsetup` command.
- **The 24.04 desktop installer cannot install into a pre-made LUKS container
  in manual mode** (it lists the raw partition and never offers the opened
  mapper device). Either use the installer's own encrypted whole-disk flow
  (only if Windows is gone), install unencrypted and encrypt in place later
  with `cryptsetup reencrypt --encrypt` from a live USB, or accept an
  unencrypted interim install as the author did.
- Installer → Manual. `p1` → `/boot/efi`, **format unticked**. Your `/boot`
  and `/` partitions as made. Bootloader device: the disk. Read the summary
  twice: any mention of formatting `p1` or touching `p3` → Back.
- If you did pre-make LUKS by another route: do not reboot before adding
  `/etc/crypttab` and rebuilding the initramfs in a chroot (the archived plan
  §7.6 has the exact commands).

## E. First boot (45 min)

1. GRUB shows Ubuntu and Windows Boot Manager. Boot Ubuntu.
2. Boot **Windows twice**, via GRUB and via Esc. A single BitLocker recovery
   prompt is the expected worst case. `manage-bde -status C:` → Protection On.
3. Ubuntu: `sudo apt update && sudo apt full-upgrade`; `uname -r` ≥ 6.11;
   `timedatectl` shows the RTC in UTC.
4. Install this project:
   ```bash
   sudo apt install -y git
   git clone https://github.com/JowiAoun/linux-on-zenbook-duo ~/linux-on-zenbook-duo
   cd ~/linux-on-zenbook-duo && ./install.sh
   ```
   Reboot (kernel and GRUB changed). `cat /proc/cmdline` contains
   `i915.enable_psr=0`; GRUB → Advanced lists the GA kernel as the fallback.
5. `duo doctor` on the installed system; compare with `doctor-live.txt`.
6. Close the lid for two minutes; it resumes with Wi-Fi.

## If something breaks

| Symptom | Do |
|---|---|
| First boot drops to busybox/initramfs | live USB → open the LUKS volume → chroot → crypttab + `update-initramfs -u -k all` |
| An OS is missing from the boot menu | `sudo update-grub`; `efibootmgr -v` / `efibootmgr -o`; or the BIOS boot order |
| ESP damaged / Windows won't boot | Windows ISO → Repair → Command Prompt → `diskpart` (select disk 0, partition 1, assign letter=S) → `bcdboot C:\Windows /s S: /f UEFI`; then reinstall GRUB from a live chroot |
| BitLocker asks for the key every boot | enter it → `manage-bde -protectors -disable C:` → one reboot → `-enable`; persistent loops mean the firmware boot config keeps changing |
| Second screen dead after a kernel update | boot the previous kernel (GRUB → Advanced), `apt-mark hold` the HWE metapackages, report with `duo report` |
| Speakers harsh after a boot from Windows | full power-off; `powercfg /h off` in Windows |
| Want Ubuntu gone | from Windows: delete its partitions, extend C:, `mountvol S: /S`, `rd /s S:\EFI\ubuntu`, put Windows Boot Manager first |
