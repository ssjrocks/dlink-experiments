# Wi-Fi driver reverse engineering (`mt_wifi.ko`)

Ground truth from decompiling the stock `mt_wifi.ko` in Ghidra (the module is
**not stripped** — full symbols) and confirming with live `iwpriv` tests on the
device.

The driver is MediaTek's proprietary **fullmac** driver of RaLink lineage:
interfaces `ra0`/`rax0`/`apcli0`/`wds0`, controlled with **`iwpriv`** (not the
`iw`/mac80211 stack), and there is **no mac80211 / mt76** anywhere. That shapes
everything below.

## Monitor mode (radiotap): architecturally closed

- The RX data path
  `indicate_802_11_pkt` → `wlan_802_11_to_802_3_packet` →
  `announce_or_forward_802_3_pkt` **hard-converts every 802.11 frame to
  Ethernet** before it reaches the netdev. (This is why `tcpdump` sees
  `EN10MB`, not 802.11.)
- There is **zero radiotap/prism code** in the entire binary.
- `iwpriv ... set NetworkType=Monitor` **crash-reboots** the device (tested
  live).

Conclusion: getting real radiotap capture means **writing new driver RX code**,
not finding a hidden command. Treated as out of scope.

## Air Monitor: per-antenna RSSI to userspace — REACHABLE

Functions `Set_Enable_Air_Monitor_Proc`, `Set_MonitorTarget0..15_Proc`,
`Air_Monitor_Pkt_Report_Action`.

Delivers, per received frame, **per-antenna RSSI** plus rate/MCS/BW and
addresses, for up to **16 target MACs**, to userspace (and `wapp`) as a custom
**EtherType 0xA051**. Reachable now via `iwpriv`, no patching, low crash risk
(it's a reporting feature, not a mode switch). Good amplitude-sensing primitive.

## ICap (Instant Capture): raw 4-antenna I/Q — the SDR/AoA substrate

`MtCmdRfTestICapStart`, config struct `prICapInfo`:

- `u4CaptureLen` — programmable capture depth
- `ucBW` — bandwidth
- `u4CaptureNode` — RX tap point
- `fgRingCapEn` — ring / continuous capture
- `u4SourceAddressLSB/MSB` + `u4MACTriggerEvent` — **trigger capture on a
  specific source MAC**

`ExtEventICapIQDataHandler` stores per time-step **(I32, Q32)** pairs with a
**0x20 stride = 4 chains coherent**. Readout is `MT_ATEGetICapIQData` via a
chip-ops hook at `+0x158` (NULL there would mean "not hooked").

This is the real angle-of-arrival substrate and a narrowband snapshot SDR
primitive. Earlier assumptions that "SDR/CSI is impossible on MT7615" were
**wrong**. ICap is **not** a direct HQA command, so driving it needs the RF-test
ioctl path (see [racfg-hqa-protocol.md](racfg-hqa-protocol.md)).

## Beamforming Q/D matrix: phase-bearing CSI — second route to phase

`CmdETxBfQdRead` (subcarrier-index param, ExtCmd `0xED`/`0x1E`): per-subcarrier,
phase-bearing, CSI-derived data. This is the exposed route to phase information
for AoA via the HQA client (`HQA_BFSounding` + `HQA_BFQdRead`), as opposed to
raw ICap I/Q.

## ATE / RF-test subsystem is live hardware

Driven via the ATE framework (`MtCmdATEModeCtrl`, `ATE_Thread`,
`ATEManualParsingParam`, `iwpriv ra0 set ATE=...`).

Verified live: `iwpriv ra0 set ATE=ATESTART` enters ATE mode cleanly (exit 0,
**no crash**, unlike `NetworkType=Monitor`). With debug enabled, real on-chip
routines actually run — `mt_ate_sx_inc_cal_ext` (synth calibration) and
`AndesSendCmdMsg: msg state=5` (chip command channel responding). So the ATE /
RF-test subsystem (ICap's parent) is **live hardware, not stubbed** — a strong
signal that the ICap hooks are wired.

**Gotcha:** full-debug (`DebugCategory=0xffffffff`) plus a blocking `iwpriv` in
ATE floods dmesg and can hang the SSH session; recover with `reboot` (over the
wired shell all config survives, ~70 s).

## Radio is 3×3:3 — only 3 RX chains (verified live)

The per-antenna RSSI readout (`iwpriv <iface> stat` → `RSSI = a b c d`) always
shows the **4th value at `-127`** (noise floor), on both bands and for every
client tested. This is **not a fault**: the DIR-1750 is an AC1750-class
**3×3:3** radio with **3 RF/RX chains**. Confirmed two ways:

- Max rates are 3-stream on both bands: 2.4 GHz **450 Mb/s** (= 3×150, HT40) and
  5 GHz **1300 Mb/s** (= 3×433, VHT80).
- `iwpriv rax0 stat` → `RSSI = -53 -47 -52 -127` is stable across different
  associated clients (a phone, and this PC's Wi-Fi).

The board has 4 physical antennas but they feed 3 RF chains. For direction
finding the usable array is therefore **3 elements** — enough for an unambiguous
2D bearing.

### Best per-antenna RSSI source: `iwpriv <iface> stat`

`iwpriv rax0 stat` (or `ra0` for 2.4 GHz) prints a `RSSI = a b c d` line that is
the driver's own per-chain RSSI, available in **normal AP operation** — no ATE
mode, no `DebugCategory`, no dmesg scraping. This is the cleanest amplitude-DF
input and is what [../tools/rssi_live.py](../tools/rssi_live.py) reads. Keep a
station associated and transmitting (uplink traffic) so the values stay fresh.

## Why full OpenWrt is not practical here

No mt76 Wi-Fi support exists for MT7629, and there's a `scpsys` WBSYS
power-domain blocker. The stock (OpenWrt-derived) build with the proprietary
driver is the practical base to work from.
