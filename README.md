# dlink-experiments

Reverse-engineering and repurposing a **D-Link DIR-1750 (HW rev A1)** Wi-Fi
router — a MediaTek MT7629B / MT7615 device — as a research platform. The goal
is to turn a piece of e-waste into something useful: root access, a modifiable
UI, and (the ambitious part) using the radio's four antennas and the hidden
RF-test subsystem for **per-antenna RSSI direction finding** and eventually
**phase-based angle-of-arrival (AoA)**.

Everything here was derived from static analysis (Ghidra) of the stock firmware
plus live experiments on the actual device. Findings are labelled **proven**
(verified on-device or in decompilation) vs **suspected**.

> This is a personal research project on a device I own, done for learning. See
> [STATUS.md](STATUS.md) for exactly where it stands and what is left.

---

## Hardware

| | |
|---|---|
| Model | D-Link DIR-1750, hardware rev **A1** |
| SoC | MediaTek **MT7629B** (ARM Cortex-A7, armv7) |
| Wi-Fi | MediaTek **MT7615 / MT7615D**, **3×3:3** (3 RX chains), 4 physical antennas |
| Stock OS | Rebadged **OpenWrt** (LuCI, opkg, dropbear, uci — hidden behind the D-Link UI) |
| Wi-Fi driver | Proprietary fullmac **`mt_wifi.ko`** (RaLink lineage: `ra0`/`rax0`/`apcli0`/`wds0`, `iwpriv` not `iw`, **no** mac80211/mt76) |

---

## Goals

1. **Root + persistent access** — ✅ done (key-only SSH).
2. **Rebuild/repack firmware** so custom images flash cleanly — ✅ done (decrypt/encrypt + squashfs repack understood).
3. **Modify the stock web UI** (cosmetic + feature experiments) — ✅ done.
4. **Non-interfering wired lab host** so Wi-Fi experiments don't drop the shell — ✅ done.
5. **Read the radio's per-antenna signal data from userspace** — ✅ done (reverse-engineered MediaTek RACFG/HQA client).
6. **Amplitude (RSSI) direction finding** across the 4 antennas — ✅ demonstrated.
7. **Phase-based AoA** (per-subcarrier CSI → MUSIC) — 🚧 substrate proven reachable; calibration + bench loop not done.
8. Explore the chip's **ICap (raw 4-antenna I/Q)** path as a narrowband SDR primitive — 🔬 identified in firmware, not yet driven.

---

## Status at a glance

| Phase | State |
|---|---|
| Firmware decrypt / repack | ✅ Proven |
| Key-only root SSH | ✅ Proven |
| Stock UI edits | ✅ Proven |
| Wired lab host (no LAN interference) | ✅ Proven |
| Wi-Fi driver RE verdicts | ✅ Proven (Ghidra + live) |
| RACFG/HQA userspace client | ✅ Working (live chip ID, fw build, per-antenna RSSI) |
| Per-antenna RSSI direction finding | ✅ Demonstrated (see [results](results/)) |
| Phase-based AoA (CSI/MUSIC) | 🚧 `BFQdRead` command decoded; invoking it reboots the box (31 s watchdog) — needs valid sounding first |
| Raw I/Q ICap / SDR | 🔬 Mapped in firmware, not driven |

See **[STATUS.md](STATUS.md)** for the full report.

---

## Key findings (short version)

- **Standard monitor mode is architecturally closed.** The driver's RX path
  hard-converts every 802.11 frame to Ethernet before it reaches the netdev;
  there is **zero** radiotap/prism code in the binary, and
  `iwpriv ... set NetworkType=Monitor` crash-reboots the device. Real radiotap
  capture would mean writing new driver RX code, not finding a hidden command.
  → [docs/wifi-driver-re.md](docs/wifi-driver-re.md)

- **The RF-test (ATE/QA-tool) subsystem is live hardware, not stubbed.** It
  exposes **per-antenna RSSI**, beamforming **Q/D matrix** (per-subcarrier,
  phase-bearing CSI) and **ICap** (raw coherent I/Q across all 4 chains).

- **A from-scratch MediaTek RACFG/HQA client works** over raw Ethernet to the
  on-device `ated` daemon. It pulls live `chip_id=0x7629`, firmware build
  string, and per-antenna RX statistics. The protocol + 183-command map are
  fully documented. → [docs/racfg-hqa-protocol.md](docs/racfg-hqa-protocol.md)

- **Amplitude direction finding works today.** Carrying a transmitting phone
  around the room produces a clear, repeatable swing in the per-antenna RSSI
  values (≈24 dB distance swing; strongest-antenna rotates with bearing). The
  radio is 3×3, so the array is 3 elements (the 4th RSSI is always the floor).
  → [results/df_result.png](results/df_result.png)

- **Firmware is OpenSSL `Salted__` AES-256-CBC** behind a 116-byte D-Link
  header; the key is `HMAC-SHA1("DIR-1750", "MT7629B_DIR-1750-S1-1904")`. Images
  can be decrypted, the squashfs rebuilt, and re-encrypted to flash.
  → [docs/firmware.md](docs/firmware.md)

---

## Repo layout

```
docs/
  firmware.md            Firmware encryption, layout, and repack recipe
  root-access.md         Getting key-only root SSH + the OverlayFS gotcha
  wifi-driver-re.md      Ghidra verdicts: monitor mode, Air Monitor, ICap, beamforming CSI
  racfg-hqa-protocol.md  The MediaTek RACFG/HQA wire protocol + command map
tools/
  hqa.py                 Working RACFG/HQA client (PC-side, raw Ethernet)
  cmdmap.json            183 HQA command_id -> driver handler address mappings
  cap3.sh                Per-antenna RSSI capture loop (over SSH)
  df_live.py             Live ANSI-bar per-antenna RSSI display
  df_monitor.py          Alternative live RSSI monitor
results/
  df_result.png          Direction-finding plot from a real walk-around
  df_run.log             The raw per-antenna RSSI samples behind that plot
STATUS.md                Full status report + phase tracker
```

---

## Reproducing the direction-finding demo

Prerequisites: root SSH to the device as `ated`/`iwpriv` are available, and a
client (e.g. a phone) associated and transmitting (streaming video is an easy
traffic source).

```bash
# Live bars, ~1 Hz, cleanest source (iwpriv stat, normal operation):
python3 tools/rssi_live.py rax0   # rax0 = 5GHz, ra0 = 2.4GHz; ssh alias "dir1750"

# Older variant that scrapes the dmesg station table:
python3 tools/df_live.py

# Or log a timed capture while you move the client around:
./tools/cap3.sh run.log 40        # 40 s
```

Any transmitting station works as the target. A convenient controlled one is
the host PC's own Wi-Fi radio (if, like here, the PC uses Ethernet for
internet): `nmcli con up dlink-9A9D` then `ping -I <wlan> -i 0.01 192.168.1.254`
to keep uplink traffic flowing. Remember this is a **3×3 radio** — the 4th RSSI
value is always the noise floor.

The RACFG/HQA client (`tools/hqa.py`) talks to the device directly over raw
Ethernet and needs `sudo` and the device's `ated` daemon running:

```bash
# on the device:
iwpriv ra0 set ATE=ATESTART ; ated -f -u -b br-lan -i ra0
# on the PC (same L2 segment):
sudo python3 tools/hqa.py chipid     # -> chip_id=0x7629
sudo python3 tools/hqa.py rxstat     # -> per-antenna RX stats
```

Adjust the interface name (`eno2`) and device MAC in `hqa.py` to your setup.

---

## Non-goals / ethics

This targets a device I own, on an isolated wired segment, for learning about
RF and firmware internals. The direction-finding work senses a cooperating test
transmitter (my own phone) in my own space. Nothing here is intended for
surveilling other people or networks.

## License

MIT — see [LICENSE](LICENSE).
