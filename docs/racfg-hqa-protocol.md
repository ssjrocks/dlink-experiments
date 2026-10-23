# MediaTek RACFG / HQA wire protocol (DIR-1750 / MT7615)

Status: **client works end-to-end** and pulls live chip data. Reference
implementation: [../tools/hqa.py](../tools/hqa.py) (PC-side, run with `sudo`).

Validated: `chip_id=0x7629`, fw build `"057 0:5:4 20191220220413"`, per-antenna
RX statistics (4 chains). Reverse-engineered from the on-device `ated` daemon
(`/usr/bin/ated` v2.0.2, ARM musl, stripped) and `mt_wifi.ko` in Ghidra.

## Transport

- **On the device**, start the bridge daemon (not auto-running):
  ```bash
  ated -f -u -b br-lan -i rax0     # -u = unicast reply; -i picks the band's iface
  ```
  `ated` opens a `PF_PACKET` raw socket (promiscuous) that receives MediaTek
  **RACFG** command frames and forwards them to the driver via ioctl.

  > **The HQA channel works in NORMAL AP operation — ATE mode is NOT required.**
  > (2026-10-23) With `ated` running and the radio in ordinary AP mode (no
  > `iwpriv ... set ATE=ATESTART`), `HQA_GetChipID`, `hqa_get_fw_info` and
  > `HQA_GetRxStatisticsAll` all return live data, and associated stations stay
  > connected. This is better than the earlier assumption that you must enter ATE
  > mode (which also drops every STA). Pick `-i rax0` for 5 GHz, `-i ra0` for
  > 2.4 GHz, matching the band your target station is on.

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

## `HQA_BFQdRead` (0x155b) decoded — and why it reboots the device

Decompiling the handler chain
`HQA_BFQdRead` → `Set_TxBfQdRead` → `TxBfQdRead` → `CmdETxBfQdRead` gives the
exact wire format:

- **Request data field** = a **4-byte big-endian subcarrier index**. The driver
  byteswaps it, formats it as a decimal string, then `simple_strtol`s it back
  and **truncates it to a signed `char`** — so the effective range is −128..127.
- `CmdETxBfQdRead` builds firmware **ExtCmd `0xED`, sub-command `0x1E`** with a
  4-byte payload `{ 0x16, subCarrIdx, band, 0 }`. `band` is derived from the
  ioctl interface (so `-i rax0` → 5 GHz band). **No station/wcid is selected** —
  it reads the Qd matrix the chip currently holds for that band.
- The result arrives **asynchronously**: an ExtEvent handler stores the buffer,
  and `HQA_BFQdRead` blocks on `wait_for_completion_timeout` before copying up to
  **14 DWORDs** into the RACFG reply at `data+2`.

> ⚠️ **HAZARD (observed 2026-10-23): invoking `BFQdRead` crash-reboots the
> device.** With no valid *sounded* BF profile held by the chip, the firmware
> command (`chip_cmd_tx`) never completes; the board's **MediaTek hardware
> watchdog (31 s timeout, `mtk-wdt`)** then resets the whole SoC. A client that
> retries with long timeouts just keeps the chip wedged into the watchdog window.
> The device recovers on its own (~70 s, config survives), but this makes naive
> Qd polling destructive.
>
> Getting usable phase data therefore requires first guaranteeing a valid sounded
> profile exists for the target STA (so the command actually completes) — the BF
> sounding sequence (`HQA_ManualAssoc`/`HQA_BFSounding`/`HQA_StaRecBfUpdate`) has
> to be driven correctly before `BFQdRead`, and each step must be verified not to
> wedge the command channel. This is the current frontier.

### Follow-up test (2026-10-23): the profile read reboots too — root cause found

`HQA_BFProfileDataRead` (0x1554) uses the **same** firmware command
`ExtCmd 0xED / subcmd 0x1E`, only with a different tag (**7** instead of 0x16):
payload `{7, pfmu_id, fgBFer, band, subCarrIdx(2B)}`. It was tried as the
"safer" read (it has a host-side NULL-bailout `BFQdRead` lacks) under the best
normal-mode conditions available:

- **implicit TxBF is enabled** (`dmesg`: `read_itxbf: ITxBfEn = 1`), so the chip
  computes internal per-subcarrier steering;
- a real VHT-NSS2 station was associated and passing uplink traffic (so iBF had
  reciprocity data to calibrate from).

Result: **it still rebooted the device** (confirmed via uptime reset), exactly
like `BFQdRead`. So the reboot is **not** "no profile exists" — it is that the
**readback-completion event is only wired up in ATE/RF-test mode**. In normal AP
operation the async event that fills the host buffer (`adapter+0x7a2c98`) is
never generated (cf. the RE note that the IQ/profile readback chip-op hook at
`+0x158` is NULL = "not hooked" outside test mode). The host thread then blocks
forever in `wait_for_completion_timeout` holding a lock, the `/dev/watchdog`
kicker is starved, and the 31 s MTK watchdog resets the SoC.

**Conclusion:** there is **no normal-mode route** to the per-subcarrier phase /
Qd / PFMU data on this chip. Any `0xED/0x1E` readback reboots the box. Phase data
requires the full MediaTek QA-tool flow **in ATE mode** — enter ATE
(`MtATESetMacTxRx`, which installs the readback event hook), then
`HQA_ManualAssoc` → `HQA_StaRecBfUpdate` → `HQA_TxBfProfileTagMatrix` →
`HQA_BFSounding` with a cooperating transmitter on the ATE RX channel, and only
then read. That is a from-scratch bench effort (test-mode sounding partner +
calibration), not a normal-operation capture. Amplitude DF via `iwpriv stat`
remains the only reboot-free per-antenna signal.
