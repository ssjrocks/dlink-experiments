# N9 Wi-Fi MCU firmware RE — toward enabling ICap (phase AoA)

Goal: enable the raw-I/Q capture (ICap) that stock firmware won't deliver, by
understanding/driving the Wi-Fi MCU ("N9") capture path directly. Pursued because
the device is disposable (brick-risk acceptable).

## What the firmware looks like
- Wi-Fi MCU = MediaTek **"N9"**, firmware runs from on-chip **ROM** + a **25 KB RAM
  patch** (`MT7626_FirmwareImage`, embedded in `mt_wifi.ko` at file off 0x2a5a52,
  0x6518 bytes). The bulk of the code (incl. the RF-test/ICap handler) is in ROM,
  not in the driver.
- N9 DRAM is reserved at ARM-phys `0x41000000` (16 MB, `N9-reserved-memory@41000000`).
  **Not** accessible via `/dev/mem` — reading it that way **crashes/reboots the SoC**
  (it's the Wi-Fi subsystem's space; access needs the driver's remap window).

## Host can read AND write chip registers (HQA, cmd_type 8)
- `0x1302` HQA_MACBbpRegBulkRead — read chip regs/mem (VERIFIED: 0x0 → real data).
- `0x1301` HQA_MacBbpRegWrite — write a MAC/BBP register.
- `0x1304` HQA_RfRegBulkWrite — write RF registers.
So host-side register programming of the capture is possible *if* the register
sequence is known and the CRs are host-writable.

## KEY FINDING: the capture engine IS configured by the firmware (not hard-gated)
Diffing the MAC/PHY register space (via `0x1302`) **before vs after** arming a
capture (`0x1580` Control=1) shows **~41 registers change** in the `0x4000–0x8000`
BBP/PHY region (e.g. 0x6100, 0x6188, 0x6188, 0x8014/8044/808c/80a4/8104/8110/8150/
81a4/81b0 …). So the firmware **does** program the capture hardware on this MT7629
(`0x7629`) variant — the earlier "all zeros" is a *readback* problem, not the
feature being compiled out.

## Where the data might be (unconfirmed)
A coarse `0x1302` scan during a TX carrier + capture shows a dense ~64 KB block at
**`0x30000–0x40000`** whose contents **partially change with the signal** (≈986 of
12288 bytes differ carrier-on vs off over 0x30000–0x33000). Candidate for (part of)
the capture sysram, but it does not yet cleanly decode as raw I/Q, and free-run
(fgTrigger=0) capture may only partially latch.

## The sysram readback problem
Stock flow returns the I/Q via a **firmware event** (ExtEventWifiSpectrumRawDataDump),
and the address-readback (`0x1580` Control=2) is **gated on chip==`0x7615`** (this is
`0x7629`). Direct `0x1302` reads of the documented sysram addr `0x140000` return zero
(not in the register space `0x1302` reaches without a window). So the captured samples
are produced but not retrievable through the normal path on this variant.

## Next steps (the real remaining work)
1. **Dump the N9 ROM** (via the driver's MCU remap window — RE how `mt_wifi.ko` reads
   MCU memory; `/dev/mem` is out). Then reverse the RF-test/ICap handler to get: the
   exact capture **trigger** sequence (so it latches a real signal, not empty), and
   the **sysram read** mechanism (`SYSRAM_INTF_SEL` window CRs) to retrieve the I/Q.
2. With that, either drive the whole capture + read from the host (`0x1301`/`0x1302`),
   or patch the N9 patch/ROM to un-gate the readback and reflash (brick-OK).
3. Decode I/Q → per-antenna phase → MUSIC bearing (3-element array).

Status: promising — the hardware configures a capture and host reg r/w works — but
retrieving usable I/Q still needs the ROM-level RE of the trigger + sysram window.
This is an open, substantial reverse-engineering effort.
