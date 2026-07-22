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

## Phase D — pending

Runbook = PLAN.md §7 with these as-built amendments: `p6` ≈ **49.8 GiB** (not
~203 GiB); pre-flight includes `manage-bde -status C:` (re-suspend if the
3-boot window lapsed) and the BT unpair above; 4 GB swapfile in Phase E.
