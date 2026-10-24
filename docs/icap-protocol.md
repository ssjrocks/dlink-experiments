# ICap (Instant Capture) raw-I/Q — protocol (toward phase AoA)

Goal: live per-antenna I/Q (→ phase) of a received signal for angle-of-arrival.
ICap is the chip's raw-I/Q capture engine (RBIST → sysram). This documents the
**fully reverse-engineered, on-device-verified** command protocol and the one
remaining gap (making the ADC capture latch samples).

Reverse-engineered from `mt_wifi.ko` and **confirmed against the open mt7615
driver source** (`dt99/mt7615`: `ate/testmode_ioctl.c`, `include/mcu/mt_cmd.h`,
`embedded/mcu/andes_mt.c`, `embedded/include/rtmp.h`). Client:
[../tools/icap.py](../tools/icap.py).

## Transport — plain HQA (cmd_type 8), no ATE/19-magic path

ICap is reachable over the **same HQA raw-Ethernet channel the BF reads use**
(ethertype 0x2880 → `ated` → ioctl `0x8be8` → driver `HQA_CMDHandler`). The HQA
command `HQA_CapWiFiSpectrum` is in the DIR-1750 command table at **`0x1580`**
(handler `0x21eba4`), so no separate ATE command path is needed. (The driver's
ATE ops — `MT_ATESetICapStart` etc. at ate-ops indices 0x3c/0x3d/0x3e — are what
`0x1580` calls internally.)

Device setup (all safe, **no reboot** — verified over a long session):
```
iwpriv rax0 set ATE=ATESTART        # enter ATE/RF-test mode (sets 3s cmd timeout)
iwpriv rax0 set ATECHANNEL=36       # tune a channel with signal
iwpriv rax0 set ATE=RXFRAME         # start RX (chains then show real RSSI, e.g. -64/-68/-99)
ated -f -u -b br-lan -i rax0
```

## Commands

### Enter ICap mode — HQA `0x1509` (HQA_CalibrationTestMode)
Data (big-endian u32): `[Value][ICapLen]`. `Value`: 0=NORMAL, 1=RFTEST, **2=ICAP_MODE**.

### Arm / read — HQA `0x1580` (HQA_CapWiFiSpectrum), first field = Control
All fields big-endian u32 unless noted.
- **Control=1 (arm):** `Trigger, RingCapEn, Event(u4TriggerEvent), Node(u4CaptureNode),
  Len, StopCycle, BW, MACTriggerEvent, SourceAddress(6 raw bytes), Band, PhyIdx`.
- **Control=2 (get capture info):** reply has `StartAddr1, StartAddr2, StartAddr3,
  EndAddr, StopAddr, Wrap` (per-chain sysram buffer addresses). Returns status 1
  while the capture has not completed.
- **Control=3 (dump I/Q):** `WF_Num, IQ_Type` → reply `[Control][WF_Num][IQ_Type][count][count×i32 samples]`.
  One capture stores all chains; read each chain by `WF_Num` (0/1/2).

### Bulk memory read — HQA `0x1302` (verified working)
Data: `[Offset u32][Len u16 words≤371]` → reply `[2 bytes][Len×4 bytes]`.
Reads chip memory (e.g. `0x0` returns real data). Use to read sysram directly.

## Capture nodes (`rtmp.h`) — the key constants
```
FOUR_WAY_ADC = 0x6   (all 4 chains' ADC, coherent — use for AoA)
FOUR_WAY_FIIQ= 0x8   FOUR_WAY_FDIQ = 0x9
WF0_ADC=0xb WF1_ADC=0xc WF2_ADC=0xd WF3_ADC=0xe   (single chain)
WFx_FIIQ=0x200b.. WFx_FDIQ=0x300b..
CAP_BW_20=0 CAP_BW_40=1 CAP_BW_80=2
```
Sysram: 12 banks × 4096 samples; `WIFISPECTRUM_SYSRAM_START_ADDR` = 0x140000
(or 0x110004 per chip variant).

## Verified on-device (2026-10-24)
- `0x1509`/`0x1580`/`0x1302` all accepted; **no reboot** across a long session.
- Arm returns status 0; `MtCmdRfTestICapStart:(Status = 0)` in dmesg (command
  reaches the chip). Read (Control=3) returns correct-shape **256-sample buffers
  per chain** (`count=0x100`, reply len 1042 = 18 + 256×4).
- RX confirmed live (`RSSI-A=-64` etc. after `ATE=RXFRAME`).

## The remaining gap: the capture does not latch samples
Every readback — Control=3 dump, and direct sysram reads via `0x1302` — returns
**all zeros**. Swept exhaustively with no non-zero result:
- `Node` ∈ {0..8, FOUR_WAY_ADC, WFx_ADC}; `BW` ∈ {20,40,80}; both bands.
- `Trigger=0` (free-run): capture "completes" (status 0) but buffer empty.
- `Trigger=1` (trigger mode) with `MACTriggerEvent=1`, broadcast source, ambient
  beacons arriving, `Event` ∈ {0..4}: status stays **1 (never triggers)**.

So the ADC→sysram RBIST capture engine is not writing. The MCU command is
accepted but the capture doesn't fire. Likely one of: a specific (undocumented)
`u4TriggerEvent` value the QA tool uses; an RBIST capture-enable CR that must be
written directly (`CR_RBIST_CAPTURE`, sysram interface-select CRs exist in
`rtmp.h`); or the capture is intended to fire during a controlled TX (DPD-cal use
case) and needs a cooperating/CW transmitter on the channel to trigger.

## CONCLUSION (2026-10-24): ICap does not capture on this device's firmware

The decisive test: made the chip transmit a **continuous carrier (`ATE=TXCARR`)**
— the strongest possible signal, fed straight into its own ADCs — and captured.
Result: **still all zeros**, on every node, and Control=2 returns **no capture
address**. So it is not a signal/trigger problem.

Root cause (from the `0x1580` handler, 0x21eba4): the capture-result path is
**gated on the Wi-Fi chip reporting `0x7615`**
(`if ((adapter+0x11ca28 & 0xffff) == 0x7615)`), but the DIR-1750's integrated
**MT7629 Wi-Fi reports chip-id `0x7629`** (confirmed via HQA `0x1514`). The ICap /
WifiSpectrum (RBIST) capture is a factory/QA feature that is effectively **not
enabled for this chip variant in the production firmware**: the host-side handlers
all exist (commands ack, `MtCmdRfTestICapStart: Status=0`), but the MCU never
performs the capture and never returns buffer addresses.

**This is a firmware/chip-variant limit, not fixable from the host.** Getting raw
I/Q would require different hardware (a discrete MT7615/MT7915 with QA firmware) or
replacing this chip's Wi-Fi firmware with a QA/factory build that enables ICap for
the `0x7629` variant — a separate, major undertaking.

### Implication for phase-based AoA on this device
All *live* per-antenna **phase** paths are blocked on stock firmware:
- **ICap raw I/Q** — gated out for this chip variant (above).
- **BF/PFMU profile** — reads fine but is a *static* stored profile, not a live channel.
- **CSI/radiotap** — not exported; the RX path hard-converts 802.11→Ethernet.

So live direction finding on this device is limited to **amplitude** (per-antenna
RSSI, 3 chains), which does show a real directional response (see
[df_result.png](../results/df_result.png)). A calibrated amplitude bearing
estimator is the achievable DF here; phase AoA needs different hardware or firmware.
