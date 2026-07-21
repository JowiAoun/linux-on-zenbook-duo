# Running Ubuntu 24.04 LTS Natively on the ASUS Zenbook Duo (2024) UX8406MA
 
## TL;DR
- Ubuntu 24.04 LTS can be made to feel nearly "native" on the UX8406MA, but **only if you move off the stock GA kernel (6.8) to a newer kernel** — ideally the 24.04 HWE stack (6.14, or the later-backported 6.17) or a mainline/OEM kernel — and layer community userspace scripts (alesya-h / Fmstrat "duo" tools) on top for dual-screen toggling, brightness sync, rotation and battery limit.
- The three genuinely hard features are (1) automatic bottom-screen on/off when the keyboard is docked/undocked, (2) the detachable keyboard's backlight + Fn hotkeys, and (3) the i915 second-screen regression; the first is solved in userspace, the second needs a very recent kernel (HID patches merged after 6.14) or a pyusb script, and the third needs kernel parameters/patches.
- Nothing here risks bricking if you follow standard precautions; the one Linux-relevant hazard is BitLocker/partition handling during install. Keep Windows on a small partition because ASUS ships BIOS updates primarily for Windows (though EZ-Flash lets you update from a USB stick without Windows).
## Key Findings
 
### The machine and why the model number matters
The UX8406MA is the 2024 Meteor Lake Zenbook Duo: Intel Core Ultra 7 155H or Ultra 9 185H, Intel Arc integrated graphics (Xe-LPG, PCI ID 8086:7d55), up to 32 GB LPDDR5x, dual 14" OLED touchscreens (either FHD 1920×1200 60 Hz or 3K 2880×1800 120 Hz), a 75 Wh battery, harman/kardon speakers, an FHD IR webcam with Windows Hello, 2× Thunderbolt 4, 1× USB-A 3.2 Gen 1, HDMI 2.1, and a 3.5 mm jack. The detachable ErgoSense Bluetooth keyboard identifies over USB as `0b05:1b2c`; the two touch digitizers are ELAN devices confirmed in a Linux Mint UX8406MA `inxi` dump as `ELAN9008:00 04F3:4259` (top panel) and `ELAN9009:00 04F3:42EC` (bottom panel). This is a completely different platform from the older UX481/UX482/UX582 "ScreenPad Plus" Duos — on those the second screen is a strip not covered by the keyboard, and the asus-wmi ScreenPad backlight drivers (e.g., Plippo/asus-wmi-screenpad) apply. Those older solutions do NOT translate to the UX8406MA, whose second display is a full eDP panel (eDP-2).
 
### Overall verdict
The best-documented real-world configuration is GNOME on Wayland (Ubuntu 24.04's default) with a recent kernel, plus the `alesya-h/zenbook-duo-2024-ux8406ma-linux` scripts. Community reports show most hardware works; the friction points are keyboard hotkeys/backlight and the finicky display handling. Adam Conway of XDA Developers, testing CachyOS/KDE Plasma, concluded ("Swapping from Windows to Linux on my laptop was a huge mistake"): *"I didn't expect quite so many small issues. It just made me want to reach for my MacBook Air more than anything… for now I'll just stick with the devil I know."* By contrast, NixOS/Fedora/Arch users report a "basically perfect" experience after kernel and script setup — the difference is almost entirely kernel version and willingness to run the helper scripts.
 
## Details
 
### 1. Feature-by-feature support status (Ubuntu 24.04)
 
**Displays — dual OLED**
- Both panels light up and are usable from kernel 6.7 onward. However, there is an **i915 regression from the 6.9 kernel line onward that breaks the second screen** (tracked in the Arch Linux packaging issue tracker; a small ~4-line fix existed but was slow to reach mainline). Practically, verify the second panel works on whatever kernel you land on and keep `i915.enable_psr=0` in your kernel command line to stop OLED flicker (Panel Self Refresh is the culprit; this is a hardware-level quirk present on Windows too).
- **Keyboard-attach → bottom screen off/on is NOT automatic in any stock configuration.** It is solved in userspace: the `duo watch-displays` script (alesya-h) watches `lsusb` for the keyboard's appearance/disappearance and calls `gnome-monitor-config`; Fmstrat's script does the same via systemd. Raw udev rules produce an "event storm" on the pogo pins (each sub-device generates separate events, crashing/reflashing the desktop) and are discouraged; polling `lsusb` is the recommended approach.
- Orientation/rotation for tent, vertical and desktop modes: handled in userspace via `duo watch-rotation`, which reads `monitor-sensor` from iio-sensor-proxy.
- Fractional scaling works per-GNOME; the scripts include a scaling config you must set to match your panel (1080p vs 3K).
- Wayland vs X11: GNOME Wayland is the target and generally best; the alesya scripts are GNOME-specific (require GNOME 46 or a backported Mutter patch for correct touch mapping). KDE and XFCE users manage screens manually. Linux Mint/Cinnamon guidance is to troubleshoot in X11 because Wayland there is experimental.
**Detachable keyboard**
- Bluetooth pairing works (toggle the switch on the left of the keyboard, watch for the 6-digit PIN notification, enter it); pogo-pin/USB dock mode enumerates as a composite HID device (`0b05:1b2c`, 6 interfaces, hid-generic/hid-multitouch/usbhid).
- **Detaching the keyboard triggers an rfkill "wireless disable" keypress that kills Wi-Fi.** This is a kernel HID issue fixed by the asus-wmi quirk `quirk_asus_zenbook_duo_kbd` (`.ignore_key_wlan = true`), authored by Mathieu Fenniak (Aug 23, 2024, reviewed-by Ilpo Järvinen), on the reasoning that *"this keyboard does not have a wireless toggle capability so these presses are always spurious."* A Linux Mint UX8406MA user confirmed updating to the 6.11 kernel fixed it. Fmstrat's script also works around it in userspace for older kernels.
- Keyboard backlight: controllable in userspace via `duo set-kb-backlight <0|1|2|3>` where "0 meaning off and 3 meaning max brightness. Requires python3 and pyusb installed" (per the alesya-h README). Native in-kernel HID backlight control merged into `hid-asus` only in a kernel newer than the 6.14 HWE kernel (see kernel work below).
- Fn/hotkeys (brightness, volume, screen toggle, MyASUS): historically not working over the dock/BT; native HID handling merged later than the 6.14 HWE kernel.
- Function lock: the newer hid-asus code adds a `QUIRK_HID_FN_LOCK` bit and an `asus_kbd_set_fn_lock()` handler (Fn+Esc), using report byte `0x4e`.
**Touchscreens & pen**
- Both digitizers work as absolute pointers. Out of the box both map to the top screen; correct mapping to each display needs Mutter merge request 3556 and libwacom PR #640 — both merged upstream (present in GNOME 46+/recent Ubuntu). `duo set-tablet-mapping` writes the needed dconf, and `duo toggle-bottom-touch` lets you palm-rest while drawing with a pen.
- On-screen keyboard: GNOME's on-screen keyboard appears when no physical keyboard is attached; there is no Linux equivalent of ASUS's ScreenXpert six-finger virtual keyboard/gesture layer.
**CPU / GPU / NPU (Meteor Lake)**
- CPU (155H/185H) works fully; Intel Arc graphics work on i915 (`8086:7d55`). Kernel 6.8 is the bare minimum and has rough edges on this generation; newer kernels + newer Mesa (the 24.04.3 HWE stack ships the Mesa 25.0.x series, a major uplift over 24.2.x) materially improve graphics.
- NPU/VPU: not used by default; the Intel VPU firmware blob (`vpu_37xx`) can be loaded manually (as demonstrated on NixOS) for the intel_vpu driver.
**Audio**
- Meteor Lake audio uses Intel SOF (`sof-audio-pci-intel-mtl`). On the 6.8 GA kernel with 24.04's original firmware many MTL laptops get "dummy output"/no speakers; this generally requires a newer kernel + newer `firmware-sof-signed` (the sof-bin project). Meteor Lake speaker-amp support (Cirrus / TI TAS) has been a recurring pain point; a quirk merged around kernel 6.7 enabled one of the two woofer pairs on the Duo, with sound described as "still not on par with windows, but pretty close." The second woofer pair requires additional SPI/_DSD workarounds.
- Headphone jack and mic array generally come up once SOF is working.
**Webcam / face login**
- The FHD webcam works via uvcvideo. The IR camera for Windows Hello has no turn-key Linux equivalent; face login requires the third-party **Howdy** project and manual configuration, and IR-based Howdy on new Intel IR sensors is often unreliable. Treat face-unlock as "not native."
**Wi-Fi / Bluetooth**
- The UX8406MA typically ships with the **Intel Wi-Fi 6E AX211 (2×2) + Bluetooth 5.3** (confirmed on Micro Center's PS99T listing), which is well supported on kernel 6.8. Some units/regions may carry the newer BE200 (Wi-Fi 7); BE200 has documented Linux instability (drops after suspend with the "Unable to change power state from D3cold to D0" error, BT/Wi-Fi coexistence issues) that is firmware/kernel-dependent and improving with newer kernels.
**Sensors**
- Ambient light sensor and accelerometers are exposed via IIO; iio-sensor-proxy drives auto-rotation. With two internal panels, rotation logic must be scripted (the `duo watch-rotation` approach) because desktop auto-rotate assumes a single panel.
**Power management**
- Only s2idle (Modern Standby) is typically advertised; deep sleep is usually absent, and Meteor Lake s2idle battery drain has been a widely reported issue (notably a regression from the 6.9 line on the closely related Zenbook 14 UX3405MA). Battery life with both screens on is far lower than Windows; ASUS's official figure is up to 8 hours: per the Zenbook DUO (2024) UX8406 product page, *"Zenbook DUO's long-lasting 75 Wh battery can keep you productive for up to 8 hours… in just 49 minutes you can top it up to a 60% charge level"* (ASUS tests Dec 13, 2023, 1080p Video Playback / PCMARK10, Core Ultra 9-185H, brightness 150 cd/m²). Use power-profiles-daemon (default on Ubuntu) or TLP.
- Battery charge limit works natively via `/sys/class/power_supply/BAT?/charge_control_end_threshold` (asus-wmi); `duo bat-limit 80` wraps it.
**ASUS ACPI/WMI**
- `asus-wmi`/`asus-nb-wmi` load and provide battery threshold. Performance/thermal profiles need the DEVID "throttle_thermal_policy_lite" path (`0x00110019`) — a patch was written for the Duo (matching the Vivobook Pro 16X firmware API) and can be poked via debugfs (`echo 0x00110019 > /sys/kernel/debug/asus-nb-wmi/dev_id`); platform_profile support has improved in newer kernels.
**Fingerprint**
- The UX8406MA has **no fingerprint reader** — it uses the IR camera for biometrics (ASUS spec lists "IR webcam with Windows Hello support," not a fingerprint sensor). fprintd is therefore not applicable.
**USB4/Thunderbolt, HDMI, external displays**
- Both Thunderbolt 4 ports (data/display/PD, up to 40 Gbps) and HDMI 2.1 work for external displays and PD charging; external monitors coexist with the two internal panels.
**Other**
- No SD/microSD card reader on this model. Standard status LEDs only. Firmware TPM is present.
### 2. Support matrix: GA kernel 6.8 vs HWE kernel
 
| Feature | Ubuntu 24.04 GA (6.8) | Ubuntu 24.04 HWE (6.14 / 6.17 backport) | How it's solved |
|---|---|---|---|
| Both OLED panels detected | Works (6.7+), but 6.9+ i915 regression risk | Works; use `i915.enable_psr=0` | Kernel + boot param |
| Auto bottom-screen toggle on dock | Not automatic | Not automatic | Userspace script (alesya/Fmstrat) |
| Screen rotation (tent/vertical/desktop) | Manual | Manual | Userspace `watch-rotation` + iio-sensor-proxy |
| Touch/pen mapping to correct panel | Needs GNOME46+/Mutter MR3556 + libwacom#640 | Works (patches upstreamed) | `set-tablet-mapping` |
| Keyboard typing (BT + USB dock) | Works | Works | Kernel HID |
| Detach kills Wi-Fi | Bug present | Fixed (quirk, ~6.11+) | Kernel quirk / script |
| Keyboard backlight | Script only (pyusb) | Native only on kernels newer than 6.14 | Script or newer kernel |
| Fn hotkeys | Mostly non-functional | Native only on newer kernels | Newer kernel |
| Audio (speakers/mic) | Often "dummy output" | Works with newer SOF firmware | Kernel + firmware-sof-signed |
| Webcam (RGB) | Works | Works | uvcvideo |
| IR face login | Not native | Not native | Howdy (unreliable) |
| Wi-Fi 6E AX211 / BT | Works | Works | iwlwifi |
| Battery charge limit | Works | Works | sysfs / asus-wmi |
| Performance/thermal profiles | Partial | Improved | asus-wmi + patch |
| NPU | Manual firmware | Manual firmware | intel_vpu blob |
| Suspend | s2idle only, drain | s2idle only, drain | Accept / tune |
 
### 3. Existing software & community projects
- **alesya-h/zenbook-duo-2024-ux8406ma-linux** — the flagship repo (the `duo` script; ~118 stars). Solves: automatic bottom-screen on/off (GNOME), brightness sync top→bottom, battery limit, keyboard backlight (pyusb), touch/pen panel mapping, auto-rotation. GNOME-specific; mature and widely forked; includes Fedora 40 notes.
- **Fmstrat/zenbook-duo-linux** — a systemd-service-based alternative that additionally handles the Wi-Fi-toggle-on-detach bug, airplane-mode reset, and boot/resume state; validated on Ubuntu 25.10 and the UX8406CA. Its status table lists keyboard-backlight-when-keyboard-off and full Fn keys as still not working. A KDE fork exists (brett-lempereur/zenbook-duo-linux-kde).
- **rvzsec/UX8406MA** — collected Linux configs for the model.
- **flukejones/asusctl (now OpenGamingCollective) issue #25** — the umbrella tracking issue for UX8406 covering keyboard, display, power; also where the hid-asus and power-profile (throttle_thermal_policy_lite) patches were prototyped. asusctl/supergfxctl/rog-control-center are aimed at ROG hardware; on the non-ROG Zenbook Duo only a subset (battery limit, generic LED) applies, so asusctl is **not** the primary tool here. Note asusctl's minimum recommended kernel is now the latest mainline and it explicitly does not support X11.
- **hid-asus kernel work** — Josh Leivenzon (GitHub hacker1024) built HID-based hotkey + backlight + Fn-lock support for device `0b05:1b2c`, based on Luke Jones's earlier "use hid for brightness control on keyboard" patch. He reported it "fully working - hotkeys + backlight" (mic-mute LED excepted) on a v6.14.4 base in May 2025. The design deliberately uses HID rather than WMI so the keyboard also works as a standalone USB keyboard on any host. The current mainline `hid-asus.c` contains the resulting `QUIRK_HID_FN_LOCK` and HID backlight code.
- **NixOS Discourse thread "Asus Zenbook Duo (2024 / UX8406MA)"** and its linked Google Sheets hardware matrix — the single richest technical log of what works and how (KMS boot config, VPU firmware, PSR flicker analysis, keyboard HID reverse engineering).
- **Reference docs**: Arch Wiki Laptop/ASUS (battery threshold, function-key behavior), Linux Mint forum UX8406MA threads, Kubuntu forum MTL-audio thread, and the ASUS ZenTalk Linux thread.
- **Firmware/LVFS**: ASUS has begun uploading some firmware to LVFS/fwupd, but coverage for this laptop's BIOS is limited; the reliable path is ASUS EZ-Flash from a USB stick, which does **not** require Windows. The latest BIOS is version 312 (dated 2026/03/10 on ASUS's download page).
### 4. Which layer each problem lives at, and recommended order of work
**Userspace (do first, lowest risk):** dual-screen toggle on dock/undock, brightness sync, rotation, battery-limit, keyboard-backlight-via-pyusb, touch mapping — all handled by the community scripts + GNOME settings + udev/systemd. This gets you ~80% of "native" feel with zero kernel risk. Install `gnome-monitor-config`, `inotify-tools`, `usbutils`, `iio-sensor-proxy`, `python3-pyusb`.
 
**Kernel (choose a recent kernel, then optionally patch):** i915 second-screen behavior + PSR flicker (boot params/patch), SOF audio (kernel + firmware-sof-signed), the detach-kills-Wi-Fi quirk (~6.11+), native keyboard backlight/hotkeys/Fn-lock (hid-asus, kernel newer than 6.14), platform/performance profiles (asus-wmi patch). On Ubuntu 24.04 the pragmatic move is the HWE kernel (6.14 today, 6.17 backport available); if a feature you need only exists in a newer kernel than HWE ships, use the Ubuntu mainline kernel PPA or build with the specific patch (DKMS is viable for hid-asus-type modules).
 
**ACPI/WMI reverse engineering (only if chasing profiles/fan/EC):** dump DSDT/SSDT with acpica (`acpidump`/`iasl`) and validate with fwts; the throttle-thermal-policy-lite DEVID (`0x00110019`) was found this way and can be exercised via `/sys/kernel/debug/asus-nb-wmi/`.
 
**Firmware/EC — do NOT touch:** do not attempt to reflash the keyboard MCU, EC, or panel firmware from Linux. BIOS updates should go through EZ-Flash (USB) or MyASUS on Windows.
 
## Recommendations
1. **Before touching anything:** create a Windows recovery USB, image the whole disk (Clonezilla or Macrium Reflect), and **record your BitLocker recovery key** (tied to your Microsoft account or exportable from Windows) — resizing or even encountering the encrypted partition can trigger BitLocker recovery. Update the BIOS to the latest (312 as of March 2026) from Windows/EZ-Flash first, while you still have Windows.
2. **Dual-boot, don't wipe.** Shrink Windows in Windows' own Disk Management, leave Windows on ~60–100 GB so you retain MyASUS BIOS/firmware updating and a fallback. Disable or suspend BitLocker before repartitioning.
3. **Install Ubuntu 24.04.3+ and immediately switch to the HWE kernel** (`sudo apt install linux-generic-hwe-24.04`); if you need the newest features (native keyboard hotkeys), add the newer HWE backport (6.17) or the mainline kernel. Add `i915.enable_psr=0` to `GRUB_CMDLINE_LINUX_DEFAULT` and `update-grub`. Keep Secure Boot ON — Ubuntu's signed shim and HWE kernels support it; only custom-built kernels need MOK enrollment.
4. **Clone and run the community scripts** (start with alesya-h; use Fmstrat if you want the Wi-Fi-detach fix and systemd integration on an older kernel). Bind `duo toggle`, `duo set-kb-backlight`, etc. to hotkeys, and enable the `watch-*` services at session start.
5. **Verify audio** (`aplay -l`); if speakers are "dummy output," update `firmware-sof-signed` and move to a newer kernel.
6. **Accept that IR face-unlock, ScreenXpert gestures/virtual keyboard, and full Windows-parity battery life are not achievable today.**
**Thresholds that change the plan:** If your running kernel post-dates the hid-asus Zenbook Duo merge (confirm with `modinfo hid_asus` / test the keys), drop the pyusb backlight script and use native hotkeys + Fn-lock. If your unit has a BE200 card and you see post-suspend Wi-Fi drops, move to the newest kernel/firmware or swap in an AX211. If a future 24.04 HWE kernel integrates the i915 second-screen fix cleanly, you can drop the PSR/mode workaround params.
 
## Caveats
- The exact mainline kernel version that first shipped native UX8406MA keyboard backlight + hotkeys is **not definitively confirmed** from primary kernel.org sources; the developer's working tree was based on v6.14.4 in May 2025 and the features are present in current mainline `hid-asus.c`, pointing to a first release **after 6.14 (most plausibly 6.16 or 6.17)**. Confirm against your specific running kernel before relying on native hotkeys. Note that separate, later asus-wmi keyboard quirks exist for the different UX8406**CA** (Arrow Lake) and UX8407AA variants — do not conflate them with the UX8406MA HID work.
- Whether the native HID backlight/hotkeys function identically over **Bluetooth** (versus the USB/pogo dock) is not explicitly confirmed; the developer's rationale emphasized USB/HID, and ASUS restricts some Fn keys over BT to non-ASUS hosts.
- Several sources describe distros other than Ubuntu (NixOS, Fedora, Arch, Mint); behavior maps to kernel/GNOME/Mesa versions, not the distro name, so it transfers to Ubuntu with matching versions.
- The i915 second-screen regression status shifts release to release; test your specific kernel and keep a known-good kernel installed to boot into.
- Some reports are individual community experiences and may not generalize; where a fix is described as "merged upstream," confirm it is actually present in your kernel before depending on it.