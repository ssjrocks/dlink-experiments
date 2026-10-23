# Project status report

_Last updated: 2026-10-23._

A frank account of where the DIR-1750 repurposing project stands: what is
**proven**, what is **in progress**, and what is **not started / blocked**.

---

## 1. Access & platform — DONE

- **Root SSH, key-only.** Reached as a wired host at a static LAN address via an
  SSH alias (`dir1750`). The device's old dropbear only supports `ssh-rsa`, so
  the key is RSA-4096 with legacy algorithm flags; ed25519 is rejected. Password
  login is disabled; the original stock root hash is restored (a temporary debug
  password used during bring-up was removed).
- **Wired lab host.** The device is plugged into the main switch as a quiet host:
  its DHCP server is **off**, WAN is disabled, RA/DHCPv6 disabled — so it does
  **not** interfere with the real LAN (no rogue DHCP). It still has internet via
  the gateway. The wire is independent of Wi-Fi, so Wi-Fi experiments on
  `ra0*/rax0*` never drop the shell. This was the whole point of the cutover.
- **Stock web UI edits** verified (cosmetic string + an injected GIF on the login
  page) — the OpenWrt `/www` tree is fully writable.

**Gotcha learned (cost 3 needless reflashes):** `/etc` is an OverlayFS
(jffs2 `/overlay` over squashfs `/rom`). Flashing firmware does **not** clear the
overlay, so files written to `/etc` on a running build shadow the `/rom` version
on the next flash. To change persisted `/etc` config, edit it **live over SSH**,
not by reflashing. A factory reset clears the overlay back to `/rom`.

## 2. Firmware decrypt / repack — DONE

Full recipe in [docs/firmware.md](docs/firmware.md). Image = 116-byte D-Link
header + OpenSSL `Salted__` AES-256-CBC blob; key derived from
`HMAC-SHA1("DIR-1750", "MT7629B_DIR-1750-S1-1904")`. Payload is DTB + an xz
squashfs at a fixed offset; it rebuilds and re-encrypts to a flashable image.
Custom images have been built and flashed successfully.

## 3. Wi-Fi driver reverse engineering — DONE (verdicts)

Ground truth from decompiling `mt_wifi.ko` (not stripped — full symbols) plus
live tests. Full detail in [docs/wifi-driver-re.md](docs/wifi-driver-re.md).

- **Monitor mode (radiotap): architecturally closed.** RX path hard-converts
  802.11→Ethernet before the netdev; no radiotap/prism code exists;
  `NetworkType=Monitor` crash-reboots the device. **Not** a hidden-command away.
- **Air Monitor:** delivers per-frame **per-antenna RSSI** + rate/MCS/BW for up
  to 16 target MACs to userspace (EtherType 0xA051). Reachable via `iwpriv`, low
  crash risk.
- **ICap (Instant Capture):** raw coherent **I/Q across all 4 antennas**,
  programmable depth, can trigger on a source MAC. The real AoA/SDR substrate.
  Driven by the RF-test ioctl path, **not** a plain `iwpriv` string.
- **Beamforming Q/D matrix:** per-subcarrier, phase-bearing CSI-derived data —
  a second route to phase information for AoA.
- **ATE/RF-test subsystem is live hardware, not stubbed:** `iwpriv ra0 set
  ATE=ATESTART` enters cleanly (no crash), and with debug on, real on-chip
  routines run (synth calibration, chip command channel responding).

## 4. RACFG/HQA userspace client — WORKING

Full protocol in [docs/racfg-hqa-protocol.md](docs/racfg-hqa-protocol.md); client
is [tools/hqa.py](tools/hqa.py).

- From-scratch, reverse-engineered MediaTek **RACFG/HQA** client over raw
  Ethernet (ethertype **0x2880**) to the on-device **`ated`** daemon.
- **Validated live:** `chip_id=0x7629`, fw build `"057 0:5:4 20191220220413"`,
  and per-antenna RX statistics (4 chains).
- **The bug that cost hours:** the RACFG `cmd_type` field must be **8 or 9**;
  `ated` silently drops frames with `cmd_type=0`.
- Full **183-command** map decoded from the driver's HQA dispatch table (14
  ranges) in [tools/cmdmap.json](tools/cmdmap.json).

## 5. Direction finding — AMPLITUDE DONE, PHASE NOT STARTED

**Amplitude (RSSI) DF — demonstrated.** Reading the four per-antenna RSSI values
from the station table as a transmitting phone moves around the room produces a
clear, repeatable signal:

- ≈24 dB swing with distance;
- the strongest antenna rotates among ANT0/1/2 as bearing changes;
- the live display updates at ~1 Hz.

See [results/df_result.png](results/df_result.png) and the raw samples in
[results/df_run.log](results/df_run.log).

**ANT3-floor resolved (2026-10-23):** ANT3 always reading `-127` is **not a bug**
— this is a **3×3:3 (AC1750-class) radio with only 3 RX chains**. Confirmed two
ways: (a) both bands cap at 3 spatial streams (2.4 GHz 450 Mb/s = 3×150; 5 GHz
1300 Mb/s = 3×433), and (b) `iwpriv rax0 stat` reports `RSSI = a b c -127`
consistently across different clients (phone and PC). The 4 physical antennas
feed 3 RF chains. So the usable array is **3 elements** — still enough for an
unambiguous 2D bearing.

**Cleaner data source found:** `iwpriv <iface> stat` prints an authoritative
`RSSI = a b c d` line directly, in **normal operation** (no ATE mode, no
`DebugCategory`, no dmesg scraping). [tools/rssi_live.py](tools/rssi_live.py) uses
it. Any transmitting station works; the PC's own Wi-Fi radio is a convenient
controlled test station (associate it to `dlink-9A9D`, ping the router to keep
uplink traffic flowing) since this PC uses Ethernet for internet.

**Phase-based AoA — reachable, not built.** The substrate exists (BF Q/D matrix
and/or ICap I/Q), but turning it into a bearing needs:

1. ATE RX locked to a channel with a target transmitting on it.
2. `HQA_ManualAssoc` → `HQA_BFSounding` → `HQA_BFQdRead` to pull per-subcarrier,
   per-antenna phase (`BFQdRead` currently times out with no sounding data —
   needs a sounded STA and likely a subcarrier-index param + async reply
   handling).
3. Per-chain phase-offset **calibration** against known angles.
4. A **MUSIC** (or similar) estimator over the calibrated phases.

Steps 3–4 are an empirical bench loop (requires physically moving a transmitter
through known angles) — the realistic multi-session chunk of remaining work.

## 6. Raw I/Q / SDR — MAPPED, NOT DRIVEN

ICap is located and understood in the firmware (config struct, per-timestep
(I32,Q32) pairs, 0x20 stride = 4 coherent chains, readout hook). It is **not** a
direct HQA command, so firing an actual capture needs the RF-test ioctl path
(MTK's QA tool for this chip, or a custom userspace ioctl client) — a separate
engineering effort from the HQA client above.

---

## Honest risk / unknowns

- Phase AoA on a commodity 4-antenna consumer radio with unknown per-chain phase
  behaviour is **genuinely hard** and may not yield usable bearings without
  careful calibration; this is the part most likely to stall.
- `BFQdRead` returning phase data at all on this chip/firmware is unproven.

## What I'd do next

1. ~~Explain the ANT3 floor reading.~~ **Done** — it's a 3×3 radio (3 RX chains).
2. Get `HQA_BFSounding` + `HQA_BFQdRead` to return real per-subcarrier phase for
   an associated, sounded station (the one open phase-data question).
3. Stand up a calibration jig (transmitter at known angles) and a first MUSIC
   pass on amplitude+phase across the 3-element array.
