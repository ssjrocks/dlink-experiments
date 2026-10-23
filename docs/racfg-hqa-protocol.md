# MediaTek RACFG / HQA wire protocol (DIR-1750 / MT7615)

Status: **client works end-to-end** and pulls live chip data. Reference
implementation: [../tools/hqa.py](../tools/hqa.py) (PC-side, run with `sudo`).

Validated: `chip_id=0x7629`, fw build `"057 0:5:4 20191220220413"`, per-antenna
RX statistics (4 chains). Reverse-engineered from the on-device `ated` daemon
(`/usr/bin/ated` v2.0.2, ARM musl, stripped) and `mt_wifi.ko` in Ghidra.

## Transport

- **On the device**, start the ATE bridge daemon (not auto-running):
  ```bash
  iwpriv ra0 set ATE=ATESTART
  ated -f -u -b br-lan -i ra0      # -u = unicast reply
  ```
  `ated` opens a `PF_PACKET` raw socket (promiscuous) that receives MediaTek
  **RACFG** command frames and forwards them to the driver via ioctl.

- **From the PC** (on the same L2 segment, e.g. over the switch to the device's
  `br-lan`): a raw `AF_PACKET` socket.
  - Ethernet: `dst = device br-lan MAC`, `src = PC MAC`, **ethertype `0x2880`**.

## RACFG payload (12-byte header + data)

```
offset  size  field
+0x00   4     magic      = 18 14 28 80
+0x04   2     cmd_type   u16 BE = 0x0008   <-- MUST be 8 or 9, or ated SILENTLY DROPS the frame
+0x06   2     cmd_id     u16 BE
+0x08   2     length     u16 BE = len(data)
+0x0a   2     seq        u16
+0x0c   ...   data
```

Reply: identical framing with `cmd_type |= 0x8000` (response bit) set; `data`
holds the result.

> **The bug that cost hours:** `cmd_type = 0` is silently dropped by `ated`'s
> receive loop. It must be **8 or 9**. Everything else can be right and you'll
> still get no reply.

## HQA command dispatch

The driver's `HQA_CMDHandler` uses a dispatch table at `0x2426a4` with **14
ranges** mapping `cmd_id` → handler sub-tables; **183 commands** total in
`0x1000..0x2102`. The full `cmd_id → handler address` map is in
[../tools/cmdmap.json](../tools/cmdmap.json).

Key commands:

| cmd_id | name | notes |
|---|---|---|
| `0x1500` | `hqa_get_fw_info` | firmware build string |
| `0x1514` | `HQA_GetChipID` | returns `0x7629` |
| `0x1506` | `HQA_GetRxStatisticsAll` | **per-antenna RSSI** (four int32; `-128`/`0xffffff80` = no signal) |
| `0x1510` | `HQA_GetRxSNR` | |
| `0x1512` | `HQA_FFT` | |
| `0x1509` | `HQA_CalibrationTestMode` | |
| `0x152c` | `HQA_SetBandMode` | |
| `0x152b` | `HQA_WIFIPowerOff` | |
| `0x1556` | `HQA_BFSounding` | beamforming sounding (AoA phase path) |
| `0x155b` | `HQA_BFQdRead` | **per-subcarrier Q/D matrix = phase-bearing CSI** |
| `0x1554` | `HQA_BFProfileDataRead` | |
| `0x1553` | `HQA_StaRecBfUpdate` | |
| `0x155a` | `HQA_ManualAssoc` | associate a target STA |
| `0x1546` | `HQA_TxBfProfileTagMatrix` | |
| `0x1557` | `HQA_TXBFSoundingStop` | |

## Per-antenna RSSI (direction-finding substrate) — works now

`HQA_GetRxStatisticsAll` (`0x1506`) returns ~282 bytes including four int32
per-chain values (WF0..WF3). They read `-128` when nothing is transmitting on
the channel; with a target transmitting on the ATE RX channel they become real
per-antenna RSSI → coarse (amplitude) direction.

## Path to live AoA (needs a transmitting target + bench loop)

1. Set the ATE RX channel (`HQA_SetBandMode` + channel) and have a target
   transmit on it.
2. **Amplitude DF:** read `HQA_GetRxStatisticsAll` per-antenna RSSI as the target
   moves. _(reachable now — demonstrated)_
3. **Phase AoA:** `HQA_ManualAssoc` (associate target) → `HQA_BFSounding` →
   `HQA_BFQdRead` (per-subcarrier Q/D, phase across the 4 antennas) → MUSIC.
   `BFQdRead` currently times out with no sounding data: needs a sounded STA and
   likely a subcarrier-index param + larger/async reply handling.
4. **Calibrate** per-chain phase offsets against a known angle.

Raw ICap (`MT_ATESetICapStart`) is **not** a direct HQA command (not in the
table) — the BF Q/D path is the exposed route to phase data via HQA; raw-I/Q
ICap would need the separate `iwpriv`/ATE RF-test ioctl path.
