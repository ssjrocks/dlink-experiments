# ICap raw-I/Q capture build — working notes (DIR-1750 / MT7615)

Goal: live per-antenna I/Q (→ phase) of a received signal, to identify a tilted
antenna (and ultimately AoA). Amplitude DF proved too insensitive indoors.

## Transport (established)
- Same RACFG raw-Ethernet channel as the working BF reads: PC eno2 → device
  br-lan MAC bc:22:28:10:9a:9d, ethertype 0x2880, RACFG hdr {magic 18 14 28 80,
  cmd_type u16 BE, cmd_id u16 BE, len, seq}. cmd_type 8 = HQA (BF reads work),
  **cmd_type 9 = ATE** (need this for ICap — ICap is NOT in the HQA table).
- `ated` is a stripped generic bridge: recvfrom raw socket → ONE ioctl into the
  driver → driver's RACFG handler dispatches on cmd_type/cmd_id. So the ATE
  command id is defined in the DRIVER, not ated.
- Must be in ATE mode first: `iwpriv ra0 set ATE=ATESTART` (sets MtCmdATEModeCtrl(1)
  + 3s completion timeout; makes 0xED/0x1E-style reads return instead of reboot).

## ICap capture config — prICapInfo (from MtCmdRfTestICapStart @0x16e438, fully named)
Fields (each u32 unless noted): fgTrigger, fgRingCapEn, u4TriggerEvent,
u4CaptureNode, u4CaptureLen, u4CapStopCycle, ucBW, u4MACTriggerEvent,
u4SourceAddressLSB, u4SourceAddressMSB, u4BandIdx.
→ can trigger capture on a specific source MAC (the PC) via u4SourceAddress*/u4MACTriggerEvent.
Spectrum variant: MtCmdWifiSpectrumStart + pSpectrumInfo (same field set).

## Key functions (mt_wifi.ko)
- MT_ATESetICapStart 0x227044 → chip_ops+0x14c = MtCmdRfTestICapStart 0x16e438
- MT_ATEGetICapStatus 0x225f98 ; MT_ATEGetICapIQData 0x226f70 (chip_ops+0x158)
- ExtEventICapIQDataHandler 0x167e54 (stores returned I/Q per time-step, 0x20 stride = 4 chains coherent)
- ExtEventICapStatusHandler 0x168080 ; ICapRawDataHandler 0x167284
- OID path: OID_802_11_WIFISPECTRUM_DUMP_DATA (ioctl OID the QA tool uses)
- MT_ATESetICapStart has NO direct callers (indirect via ATE ops struct) → reached by cmd_type-9 ATE dispatch.

## Transport — RESOLVED (ated FUN_000124ec, the RACFG relay loop)
- ated keys off the magic dword at frame+0x56:
  - `18 14 28 80` → HQA path → FUN_00012354(data, 0)  (the HQA ioctl 0xf → HQA_CMDHandler, cmd_type-8 table). **This is my working BF-read path.**
  - `19 14 28 80` → **ATE path** → idx = FUN_00011fc0(cmdhdr, raw); if (&DAT_000251ec)[idx] != 0: FUN_00012354(data, idx)  (issues the OID ioctl for that idx).
- So ICap = a **`19 14 28 80`** frame over the same raw-Ethernet/ated channel. Same transport as BF reads, different leading magic byte + an ATE command id that FUN_00011fc0 maps to an OID.
- HQA_CMDHandler (driver) ignores the +4 cmd_type field; routes purely by command_id via table @0x2426a4 (14 ranges). ICap NOT in that table → confirms ATE/OID path.
- ated also special-cases some HQA cmd ids (0x152c band set → copies .dat + hqa_set_band; 0x1307/0x1308/0x1511 logging) — not needed for ICap.

## Driver ICap config — prICapInfo (MtCmdRfTestICapStart @0x16e438)
u32 fields: fgTrigger, fgRingCapEn, u4TriggerEvent, u4CaptureNode, u4CaptureLen,
u4CapStopCycle, ucBW, u4MACTriggerEvent, u4SourceAddressLSB, u4SourceAddressMSB, u4BandIdx.

## TODO (next — the remaining build)
1. Reverse ated FUN_00011fc0 + table DAT_000251ec → the ATE command id ↔ OID map; find the OID(s) for ICapStart / GetICapStatus / GetICapIQData (OID_802_11_WIFISPECTRUM_* family). Confirm the frame body layout FUN_00012354 forwards.
2. In the driver, find the OID set/query handler that routes those OIDs → MT_ATESetICapStart / MT_ATEGetICapIQData, and the exact arg struct + I/Q readback reply format (ExtEventICapIQDataHandler stores to a buffer; GetICapIQData reads it out).
3. Build PC client: ATE mode on; send 19-magic ICapStart (arm, trigger on PC MAC, capture len, BW, band); PC emits probe bursts on the ATE RX channel; poll GetICapStatus; read GetICapIQData; phase per chain = atan2(Q,I).
4. Experiment: tilt one antenna → that chain's phase shifts (phase-center move ⇒ tens of degrees at 5 GHz), identifies the antenna. Repeat per antenna to map physical↔chain.

## Honest scope
This is a genuine multi-session build: ~2 more RE layers (ated OID map + driver OID/ICap arg+readback), then client + on-device iteration (reboots), then the probe-burst triggering wrinkle (STA drops in ATE mode), then phase interpretation. Not a one-sitting job.

## Caveats
- ATE mode drops the associated STA; capture relies on PC probe-request bursts on the ATE RX channel.
- Reboots likely while iterating. Device recovers ~70s, config survives.
