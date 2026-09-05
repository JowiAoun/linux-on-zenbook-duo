# Hardware facts

Everything the code relies on, with how it was established. "Measured" means
on the author's UX8406MA (Core Ultra 7 155H, 16 GB, 2880×1800 120 Hz panels,
BIOS 312), Ubuntu 24.04.4, kernels 6.17 → 7.0. Tags like **V8** are the claim
numbers from the original master plan
([research/2026-07-21-zenduo-master-plan-v1.1.md](research/2026-07-21-zenduo-master-plan-v1.1.md) §2),
kept so code comments and the research stay cross-referenced.

## Identification

| Thing | Value |
|---|---|
| Model | ASUS Zenbook Duo (2024) UX8406MA (Meteor Lake; Core Ultra 7 155H / 9 185H). DMI `product_name` contains `UX8406MA` |
| Panels | 2× 14" OLED touch, `eDP-1` (top) / `eDP-2` (bottom); FHD@60 or 3K@120 |
| iGPU | Intel Arc (Xe-LPG), PCI `8086:7d55`, driver i915 |
| Keyboard, USB (pogo pins) | `0b05:1b2c` "ASUS Zenbook Duo Keyboard", six HID interfaces, hid-generic + hid-multitouch |
| Keyboard, Bluetooth | `0b05:1b2d` — same keyboard, different product id per transport |
| Touchpad | part of the keyboard: one external USB combo device |
| Digitizers | top ELAN9008 `04f3:4259`, bottom ELAN9009 `04f3:42ec` |
| Backlights | `intel_backlight` (top), `card1-eDP-2-backlight` (bottom, tracks the real level), `asus_screenpad` (reports a fixed value and does not track anything visible — never sync to it) |
| Wi-Fi | Meteor Lake CNVi `8086:7e40`; RF module typically AX211, some units BE200 (post-suspend drops) |
| Audio | Intel SOF `sof-audio-pci-intel-mtl`; ALC294 codec + two Cirrus CS35L41 amps |
| Battery | 75 Wh, `BAT0`, `charge_control_end_threshold` via asus-wmi |
| Sensors | 3 IIO devices; iio-sensor-proxy runs |
| Thermal | `platform_profile`: quiet / balanced / performance, native (no ACPI patching needed) |
| Suspend | `mem_sleep`: `[s2idle] deep` — s2idle is the default and the tested one |
| Storage | NVMe behind Intel VMD; visible to Linux as-is. **Never toggle the BIOS storage mode** — it breaks Windows |
| Fingerprint | none; the IR camera is the biometric device |
| BIOS | F2 setup, Esc boot menu, EZ-Flash for USB updates; 312 (2026-03-10) |

## Verified baseline

| # | Claim | Status |
|---|---|---|
| V1 | Ubuntu 24.04.4 ships a 6.17 HWE kernel + Mesa 25.2 | ✅ and since moved to 7.0 |
| V6 | Keyboard detach kills Wi-Fi below kernel 6.11 (spurious rfkill press; asus-wmi quirk `quirk_asus_zenbook_duo_kbd`) | ✅ survives detach on 6.17 |
| V7 | Touch/pen per-panel mapping needs Mutter MR 3556 + libwacom #640 (GNOME 46+) | 📄 not yet verified with a pen |
| V8 | Mainline `hid-asus.c` has NO entry for `0b05:1b2c`: no native kbd backlight, no Fn layer | ✅ measured; the HID fallback is the daily path |
| V9 | i915 second-screen regressions (6.9 line) | ✅ none on 6.17/7.0; the GA kernel stays installed as the escape hatch |
| V10 | The ids in the table above | ✅ |
| V11 | Audio: SOF works; speakers below Windows quality without voicing | ✅ see Speakers |
| V12 | Battery limit via sysfs | ✅ |
| V13 | s2idle only | ✅ (`deep` is listed, untested) |
| V14 | udev rules on the pogo keyboard storm | 📄 both upstreams converged on polling; we poll at 1 Hz |
| V15 | AX211 typical, BE200 possible | 📄 |
| V16 | VMD could hide the NVMe | ✅ non-issue |

## The keyboard, in detail

- **Hotkey mode.** The keyboard ships with the Fn layer dormant: bare F5 and
  Fn+F5 emit the identical usage. hid-asus turns the layer on with an
  "ASUS Tech.Inc." feature-report handshake to report ids `0x5a`, `0x5d`,
  `0x5e`, followed by an OOBE-disable sequence. Sent from userspace over
  hidraw (`duo kb-init`) it works — and flips the layers: after it the media
  function is the *bare* key and Fn+key gives F1..F12.
- **17 bytes over USB.** The USB vendor interface declares feature `0x5a` as
  16 bytes and then STALLs (`EPIPE`) anything but **17**; 16 is right over
  Bluetooth (mainline's size). The length is negotiated per interface, never
  assumed.
- **Which interface.** Several of the six accept feature reports and quietly
  drop them, and `/dev/hidrawN` renumbers on every re-enumeration (and sorts
  as text: `hidraw16` before `hidraw5`). The vendor collection is found
  structurally: the only interface declaring feature report `0x5a` (usage page
  `0xff31`).
- **Proof of success.** `GET_FEATURE 0x5a` echoes `ASUS Tech.Inc.` back once
  the handshake landed — valid only immediately after the write, because any
  later `0x5a` write (the backlight report) overwrites that buffer.
- **It forgets.** Every re-enumeration (dock, undock, reboot, resume from
  suspend) drops hotkey mode. `watch-fn` re-sends on node-set changes and on
  resume, detected by the gap between `CLOCK_BOOTTIME` and `CLOCK_MONOTONIC`.
- **Vendor codes** (report id `0x5a`, second byte): `10` brightness down, `20`
  brightness up, `4e` Fn-lock, `6a` second-screen key, `c7` keyboard backlight.
  Volume and mute arrive as standard consumer-page usages and work natively.
- **Keyboard backlight** is `{0x5a, 0xba, 0xc5, 0xc4, level}` padded to the
  interface's report length. Docking, undocking and resume blank it in
  hardware; the level is remembered under `~/.local/state/zenduo/`.
- **Bluetooth pairing.** Detach, slide the switch on the left edge on, then
  hold F10 for 4–5 s until the LED flashes blue rapidly; the switch alone does
  not advertise. Remove a stale Windows pairing first.
- **Touchpad.** libinput's disable-while-typing only covers internal touchpads;
  the quirk `AttrTPKComboLayout=below` makes it treat the combo like one.

## Displays

- Control goes through `org.gnome.Mutter.DisplayConfig`, the API GNOME
  Settings uses. Mutter rejects a layout that does not start at the origin
  ("positions are offset") or whose monitors are not all adjacent ("not
  adjacent"); `displayctl.build_config` normalises both.
- **Temporary vs persistent apply.** A persistent `ApplyMonitorsConfig` is
  treated by gnome-shell as a user change and raises the "Keep display
  settings?" countdown every time — measured 2026-07-23. Daemons apply
  temporarily; the cost is a brief flash of the bottom panel after some
  resumes until the daemon corrects it.
- **Why converge, not toggle.** Resume makes Mutter re-read `monitors.xml`
  (both panels); the keyboard never moved, so an edge-triggered watcher had
  nothing to react to and the bottom panel stayed lit under the keyboard.
- **Only the bottom panel is governed.** "Docked → exactly [top]" also forced
  the top panel on, snapping the laptop screen back after Win+P External Only.
- `i915.enable_psr=0`: Panel Self Refresh causes visible flicker on both OLED
  panels (the Windows driver disables it too).

## Speakers

Two Cirrus CS35L41 smart amps behind the ALC294, running ASUS's `spk-prot`
firmware with this unit's calibration (R0=10223/10307). That firmware is
*protection* (excursion, thermal), not voicing; Windows does the voicing in
an APO above the driver. Measured third-octave response (internal DMIC, so a
shape, not a calibration): useful band from ~300 Hz, everything below 200 Hz
more than 18 dB down, treble tilt uncertain. The chain in
[../lib/speaker_dsp.py](../lib/speaker_dsp.py) — high-pass 120 Hz, bass
enhancer, compressor staged so its net gain is positive everywhere, limiter
at −1 dBFS with gain-boost off — and the measurements that produced every
number are documented in [../nix/audio.nix](../nix/audio.nix).

**The PUP_DONE failure.** After a boot that follows a Windows session with
Fast Startup on, both amps sometimes time out their power-up handshake
(`Failed waiting for CS35L41_PUP_DONE_MASK: -110`). The speakers still play,
without the amp DSP: harsh, crackly, for the rest of the boot. Nothing in
userspace causes or fixes it. **Do not re-bind or reload the driver**: the
driver does not tear down its ALSA controls on unbind, the re-bind collides
with them, the left amp fails to attach to the codec and the right one never
probes. Recovery is a full power-off. Prevention is on the Windows side:
`powercfg /h off` as Administrator, then use Shut down rather than Restart
between systems. `duo-cs35l41-check` watches the kernel log and tells you.

## Dual boot

The factory disk has **five** partitions, not four: `p1` ESP (~273 MB, flags
`boot, esp`), `p2` MSR, `p3` Windows, `p4` WinRE, and a hidden `p5` recovery
partition at the very end that is a near-identical FAT32 twin of `p1`. Never
pick `p5` as the ESP. Free space carved from Windows sits between `p3` and
`p4`; `parted print free` shows it, plain `print` does not. Ubuntu 24.04's
desktop installer cannot install into a pre-made LUKS container in manual
mode; use its own whole-disk LUKS flow or encrypt in place later. The full
story: [install/](install/README.md).
