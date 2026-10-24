#!/usr/bin/env python3
# DIR-1750 / MT7615 — ICap (Instant Capture) raw-IQ client, over the HQA channel
# (cmd_type 8) via ated. Reverse-engineered from mt_wifi.ko + confirmed against the
# open mt7615 driver source (dt99/mt7615: testmode_ioctl.c, mt_cmd.h, andes_mt.c).
#
# STATUS: commands execute end-to-end on the device with NO reboot — enter ICap mode,
# arm the capture (correct capture node = FOUR_WAY_ADC), and read back 256-sample
# buffers per chain. The one unsolved piece is making the ADC->sysram capture actually
# LATCH samples: free-run completes but empty, trigger-mode never fires with the
# parameter values exposed here. That trigger/enable step is the remaining work (see
# docs/icap-protocol.md).
#
# Setup on device (safe, no reboot):
#   iwpriv rax0 set ATE=ATESTART
#   iwpriv rax0 set ATECHANNEL=36
#   iwpriv rax0 set ATE=RXFRAME          # start RX so the chains see signal
#   ated -f -u -b br-lan -i rax0
# Then run this with sudo (PC L2-adjacent to the device br-lan over the switch).
import socket, struct, time, sys, math

IFACE = "eno2"
DEV   = bytes.fromhex("bc2228109a9d")     # device br-lan MAC
ET    = 0x2880
MAGIC = bytes([0x18, 0x14, 0x28, 0x80])

# ---- HQA command ids (from the DIR-1750 cmdmap; confirmed in driver source) ----
HQA_CAL_TEST_MODE = 0x1509   # [Value, ICapLen]  Value: 0=NORMAL 1=RFTEST 2=ICAP_MODE
HQA_CAP_SPECTRUM  = 0x1580   # ICap: Control 1=arm 2=get-addrs 3=dump-IQ
HQA_MEM_BULK_READ = 0x1302   # [Offset u32, Len u16 words<=371] -> raw memory

# ---- Capture nodes (rtmp.h) ----
FOUR_WAY_ADC = 0x6   # all 4 chains' ADC, coherent (use this for AoA)
FOUR_WAY_FIIQ = 0x8; FOUR_WAY_FDIQ = 0x9
WF0_ADC = 0xb; WF1_ADC = 0xc; WF2_ADC = 0xd; WF3_ADC = 0xe   # single-chain
CAP_BW_20, CAP_BW_40, CAP_BW_80 = 0, 1, 2

_s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW); _s.bind((IFACE, 0))
SRC = _s.getsockname()[4]; _s.close()

def xact(cmd_id, data, timeout=5.0):
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ET)); s.bind((IFACE, ET)); s.settimeout(timeout)
    s.send(DEV + SRC + struct.pack(">H", ET) + MAGIC + struct.pack(">HHHH", 8, cmd_id, len(data), 0) + data)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try: p = s.recv(4096)
        except socket.timeout: break
        if struct.unpack(">H", p[12:14])[0] == ET and p[6:12] == DEV:
            L = struct.unpack(">H", p[22:24])[0]
            return p[26:26 + max(L, 0)]
    return None

def icap_mode(icaplen=256):
    return xact(HQA_CAL_TEST_MODE, struct.pack(">II", 2, icaplen))

def arm(trigger=0, node=FOUR_WAY_ADC, length=4096, bw=CAP_BW_80, band=1,
        ring=0, event=0, stopcycle=0, mactrig=0, src=b"\0"*6, phyidx=0):
    # order: Control=1, Trigger, RingCapEn, Event, Node, Len, StopCycle, BW, MACTrig, Src(6), Band, PhyIdx
    d = struct.pack(">IIIIIIIII", 1, trigger, ring, event, node, length, stopcycle, bw, mactrig)
    d += src + struct.pack(">II", band, phyidx)
    return xact(HQA_CAP_SPECTRUM, d)

def status():
    return xact(HQA_CAP_SPECTRUM, struct.pack(">I", 2))   # Control=2 -> capture addrs/stop info

def read_iq(wf, iq_type):
    d = xact(HQA_CAP_SPECTRUM, struct.pack(">III", 3, wf, iq_type))   # Control=3 dump
    if not d or len(d) < 18: return []
    cnt = struct.unpack(">I", d[14:18])[0]
    n = min(cnt, (len(d) - 18) // 4)
    return list(struct.unpack(">%di" % n, d[18:18 + n*4]))

def mem_read(offset, words=64):
    d = xact(HQA_MEM_BULK_READ, struct.pack(">IH", offset, words))
    return d[2:2 + words*4] if d and len(d) >= 2 else None

if __name__ == "__main__":
    print("icap_mode:", (icap_mode() or b'').hex())
    print("arm:", (arm(trigger=0, node=FOUR_WAY_ADC, length=4096, bw=CAP_BW_80, band=1) or b'').hex())
    time.sleep(1.0)
    print("status:", (status() or b'').hex())
    for wf in range(3):
        iq = read_iq(wf, 0)
        nz = sum(1 for x in iq if x != 0)
        print(f"  WF{wf}: {len(iq)} samples, {nz} non-zero, first={iq[:6]}")
