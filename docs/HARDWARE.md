# Hardware facts

Everything the code relies on, with how it was established. "Measured" means
on the author's UX8406MA (Core Ultra 7 155H, 16 GB, 1920×1200 60 Hz panels,
BIOS 312), Ubuntu 24.04.4, kernels 6.17 → 7.0. Tags like **V8** are the claim
numbers from the original master plan
([research/2026-07-21-zenduo-master-plan-v1.1.md](research/2026-07-21-zenduo-master-plan-v1.1.md) §2),
kept so code comments and the research stay cross-referenced.

## Identification

| Thing | Value |
|---|---|
| Model | ASUS Zenbook Duo (2024) UX8406MA (Meteor Lake; Core Ultra 7 155H / 9 185H). DMI `product_name` contains `UX8406MA` |
| Panels | 2× 14" OLED touch, `eDP-1` (top) / `eDP-2` (bottom); FHD+@60 or 3K@120. The author's unit is the FHD+ one: EDID read 2026-09-12 gives SDC 0x41a0, one detailed timing, 1920×1200 at 154.3 MHz = 60.00 Hz, and `/sys/class/drm/card1-eDP-*/modes` lists nothing larger |
| iGPU | Intel Arc (Xe-LPG), PCI `8086:7d55`, driver i915 |
| Keyboard, USB (pogo pins) | `0b05:1b2c` "ASUS Zenbook Duo Keyboard", six HID interfaces, hid-generic + hid-multitouch |
| Keyboard, Bluetooth | `0b05:1b2d` — same keyboard, different product id per transport |
| Touchpad | part of the keyboard: one external USB combo device |
| Digitizers | top ELAN9008 (ACPI `I2C0.TPL0`), bottom ELAN9009 (`I2C5.TPLX`). This unit: `04f3:4259` and `04f3:42ec`; alesya-h's unit: `425b` and `425a`, so code pairs them by ACPI name. Which is which is read from alesya-h's script and agrees with the buses here; `duo set-tablet-mapping --identify` checks it on a unit |
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
| V7 | Touch/pen per-panel mapping: GNOME's guess puts both touchscreens on `eDP-1`; a 4-value `output` setting (EDID + connector) fixes it on Mutter 46 | 🧪 cause read from Mutter 46.2's source 2026-09-27; fix written, not yet applied on hardware |
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
- **The pogo link can be present and dead** (MEASURED 2026-09-05): four
  `xhci_hcd` resets in 40 s, "device firmware changed", then the
  re-enumeration failed with `can't set config #1, error -71`. The device
  stays in sysfs with the right ids, an empty `bConfigurationValue` and no
  interfaces — so no hidraw node, no typing, no media keys, while "docked"
  still reads true. The daemons had not touched it beforehand. Re-seating the
  keyboard (a port power cycle) is the only recovery seen; `duo status`,
  `duo doctor` and `watch-fn` report the state (`dock.keyboard_usb_configured`).
- **Vendor codes** (report id `0x5a`, second byte): `10` brightness down, `20`
  brightness up, `4e` Fn-lock, `6a` second-screen key, `c7` keyboard backlight
  (all confirmed on this unit, July 2026). Seen in the journal 2026-09-05 and
  mapped by their mainline hid-asus meaning: `7c` mic mute, `7e` emoji picker
  (**VERIFY-ON-HW** which keycaps; the legend says Fn+F9 and Fn+F11). Seen and
  unidentified: `3d`, `9c` — `duo fn-map` attributes them. `3d` arrived 41
  times on 2026-09-27, docked and over Bluetooth, often every 30 s or so and
  right after the keyboard connected, which reads like a status report and
  not a key; `watch-fn` logs an unknown code once per run. Volume and mute
  arrive as standard consumer-page usages and work natively.
- **Keyboard backlight** is `{0x5a, 0xba, 0xc5, 0xc4, level}` padded to the
  interface's report length. Docking, undocking and resume blank it in
  hardware; the level is remembered under `~/.local/state/zenduo/`.
- **Over Bluetooth a refused write looks like a good one.** A feature write
  goes through bluetoothd, and the ioctl returns success even when the
  keyboard refuses it. Measured 2026-09-27: on each of 15 reconnects
  bluetoothd logged 4 to 6 `Error setting Report value` in the same second as
  `kb_init`, whose ioctls had all returned success. After the confirmed
  handshake `kb_init` sends report ids `0x5d` and `0x5e` and the four OOBE
  reports, and the second OOBE report is the backlight command above, so
  these are the likely ones. The handshake itself is read back, and the media
  keys work over Bluetooth. Whether the backlight key works there is
  **VERIFY-ON-HW**: until then both modules log a Bluetooth write as
  "unconfirmed" and send the same bytes as before.
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
- **Touch on the bottom panel lands on the top one.** Reported 2026-09-27:
  fingers on the bottom screen act on the top screen, while the mouse works on
  both. No mapping was set (`dconf dump /org/gnome/desktop/peripherals/`
  listed none), so Mutter guessed. Read from mutter 46.2
  `src/backends/meta-input-mapper.c`: an unmapped touchscreen goes to a
  monitor of the same physical size, else to "the laptop panel", and Mutter
  names only `eDP-1` the laptop panel. Both panels are 306 x 187 mm to udev,
  so both touchscreens go to `eDP-1`. GNOME's `output` setting documents three
  values (vendor, product, serial), and those cannot help: both panels report
  `SDC` / `0x41a0` / `0x00000000`, with the same `ATNA40CT02-0` model string
  in the EDID (read from Mutter's `GetCurrentState` and
  `/sys/class/drm/card1-eDP-*/edid`). Mutter 46 reads a fourth value, the
  connector name, when two monitors share all three (`match_config()` and
  `monitor_has_twin()`). `lib/touch_map.py` writes all four, for the finger
  (`touchscreens/<vendor>:<product>`) and the pen (`tablets/...`) of each
  controller. `duo-watch-displays` does it once when it starts
  (`TOUCH_MAPPING=1`), `duo set-tablet-mapping` by hand. `--identify` asks you
  to touch the bottom screen and reads each controller's interrupt count in
  `/proc/interrupts`, which tells them apart with no root and no change.

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

**The silent-speakers wedge.** The speaker PCM can stop for good mid-session:
speakers go quiet, Bluetooth earbuds still work (a separate device, own
pipeline), and PipeWire logs `snd_pcm_avail after recover: Broken pipe` about
nineteen times a second until something re-opens the device. Measured
2026-09-13 on a wedged device, from `/proc/asound/card0/pcm0p/sub0/status` with
`period_size 1024, buffer_size 32768`:

    state: RUNNING   hw_ptr: 192   appl_ptr: 128   avail: 32832

`appl_ptr` is 64 frames *behind* `hw_ptr`, so `avail` (32832) exceeds
`buffer_size` (32768) — which is exactly how ALSA reports XRUN. PipeWire calls
`snd_pcm_recover`, the SOF pipeline comes back with the same stale DMA
position, and it xruns again immediately: a loop it never escapes. Sampling
the same file after a server restart shows `hw_ptr` advancing at 48000 frames/s
with `appl_ptr` correctly ahead, so nothing is broken in hardware.

What starts it is an underrun — the buffer is 682 ms, so it takes a stall of
that order, which this 16 GB machine reaches easily once it is swapping (see
below). What makes it a *fault* rather than a hiccup is that PipeWire 1.0.5
cannot reset the SOF pipeline from its recovery path. WirePlumber's idle
suspend does re-open the device cleanly, which is why the loop ends on its own
once every stream stops — and why it lasts for hours when something (a game, a
chat app) is always playing. Measured 2026-09-13: sixteen episodes across three
days of uptime.

Recovery is a user-level restart, no root and no module reload:

    systemctl --user restart wireplumber pipewire pipewire-pulse

That costs the clients their streams — PipeWire-native apps reconnect, Wine and
FMOD ones stay silent until restarted — so it is a repair, not something to
schedule. Do **not** reach for the CS35L41 driver here: the re-bind hazard
above still applies, and the amps are not what failed.

Cheaper than that restart, and it keeps every stream: change the quantum, which
makes PipeWire re-open the device.

    pw-metadata -n settings 0 clock.min-quantum 1024

VERIFIED 2026-09-19 on a device that was already wedged, with Roblox Studio
open: the loop stopped within seconds, playback worked again, and Studio kept
its stream, which the restart above would have taken from it.

**The other way in, and the one worth preventing (MEASURED 2026-09-19).** The
682 ms buffer above is only the buffer while everything asks for the default
size. PipeWire sizes the graph, the device included, from the smallest buffer
any one client asks for, so a single application can cut that deadline to a few
milliseconds and underrun on its own, with RAM free and nothing swapping.
Roblox does exactly that, under Sober and under Wine alike:

    node.latency = 240/48000        read off the live stream with pw-dump

Thirteen episodes in one day that way, against sixteen in three days from
memory pressure, and the longest ran 167 minutes. It ended only when PipeWire
restarted itself after 14 minutes of CPU on the dead device. A test tone
started during one never finished, which is the whole symptom: nothing on the
device can play, so "the speakers died and videos won't play" is still one
fault and not two.

The fix is a floor under the buffer, shipped as
[../config/pipewire/10-zenduo-min-quantum.conf](../config/pipewire/10-zenduo-min-quantum.conf)
and on by default (`zenduo.audioBufferFloor`, or
`./install.sh --no-audio-buffer-floor` to skip it). The floor is PipeWire's own
default quantum, so nothing runs with a smaller buffer than it already did, and
an app that asks for less is handed the default instead of being allowed to
resize the device. Recording and DAW work need a small buffer and should turn
it off.

**Memory pressure is an audio bug on this machine.** PipeWire's `pw-data-loop`
runs at RT priority 20 but nothing is locked (`VmLck: 0 kB`), so it takes major
page faults like any other thread. Measured 2026-09-13 during an episode: 19
MiB/s swapped in, 29 MiB/s out, ~5000 major faults/s, with 440 GiB written to
swap over 57 hours of uptime and zram full (13.6 G of data in 3.9 G of RAM,
overflowing to the disk swapfile). An RT thread that faults blocks on the swap
queue, and a few hundred milliseconds of that underruns even a 682 ms buffer.
The same stalls are what make browser video buffer forever, so a report of
"speakers died and videos won't play" is one symptom, not two.

**Bluetooth headsets drop to phone quality during a call (MEASURED
2026-09-20).** Ubuntu's WirePlumber 0.4.17 ships `policy-bluetooth.lua` with
`media-role.use-headset-profile = true`. When a capture stream starts whose
`media.role` is `Communication` or whose `application.name` is on the script's
list (Discord's `WEBRTC VoiceEngine`, every browser's `... input`, Zoom,
Telegram, Skype, Mumble) and the default output is a Bluetooth device, it
switches that device to its headset profile, and back two seconds after the
last such stream stops. It checks the default sink, never where the stream
reads, so it fires while Discord captures from the laptop's own DMIC. The
headset profile is HFP: mSBC, mono, 16 kHz, over a SCO link, and every
application's sound goes through it. Read off `pw-top` five minutes apart,
Roblox playing under Sober, Discord in a voice channel, EarFun Air Pro 4 as
the default output:

    bluez_output.70_5A_6F_6B_3B_81.1   S24LE 2 48000   a2dp-sink, aptX
    bluez_output.70_5A_6F_6B_3B_81.1   S16LE 1 16000   headset-head-unit-msbc

with `Sober:output_MONO` linked to the second. That is the "sound turned
static and low quality in the game, sometimes" report: sometimes is whenever
a voice app holds the microphone. The fix is a WirePlumber policy file,
[../config/wireplumber/11-zenduo-bluetooth-stereo.lua](../config/wireplumber/11-zenduo-bluetooth-stereo.lua)
(with a `.conf` twin for WirePlumber 0.5), on by default
(`zenduo.bluetoothStereo`, `./install.sh --no-bluetooth-stereo` to skip). The
headset then stays on A2DP and a voice app gets the internal microphone; the
earbuds' own microphone is a manual profile choice in Settings, as it is on
Windows. `duo doctor` and the Overview name a device that is on the headset
profile; `duo audio stereo` puts it back, `duo audio headset` is the manual
choice of its own microphone, and both read the device back before they
report success.

**PipeWire can start without realtime priority (MEASURED 2026-09-20).**
PipeWire's data loops ask rtkit for realtime once, at start. `rtkit-daemon`
is started by D-Bus on first use, and a login quick enough starts the user's
PipeWire first: this boot `pipewire.service` started at 21:04:42, rtkit logged
"Running" at 21:04:43 and never logged a request from it, and `pipewire`,
`pipewire-pulse` and `wireplumber` ran their data loops as `SCHED_OTHER` for
the session (`ps -eLo cls,rtprio,comm`). Two of the last five boots ran that
way; in the other three PipeWire started 6 to 11 seconds after rtkit and got
`RR 20`. Asked again later with `MakeThreadRealtimeWithPID`, rtkit granted
the same threads priority 20 at once, so nothing but the order is wrong. The
fix is a drop-in for the three units,
[../config/systemd/user/10-zenduo-rtkit.conf](../config/systemd/user/10-zenduo-rtkit.conf),
whose `ExecStartPre` asks rtkit for a property, which starts it and waits for
it, before the service starts. `./install.sh --user` also grants the priority
to the loops running now, and `duo doctor` says which loops lack it.

## Dual boot

The factory disk has **five** partitions, not four: `p1` ESP (~273 MB, flags
`boot, esp`), `p2` MSR, `p3` Windows, `p4` WinRE, and a hidden `p5` recovery
partition at the very end that is a near-identical FAT32 twin of `p1`. Never
pick `p5` as the ESP. Free space carved from Windows sits between `p3` and
`p4`; `parted print free` shows it, plain `print` does not. Ubuntu 24.04's
desktop installer cannot install into a pre-made LUKS container in manual
mode; use its own whole-disk LUKS flow or encrypt in place later. The full
story: [install/](install/README.md).
