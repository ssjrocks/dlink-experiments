#!/usr/bin/env python3
# DIR-1750 / MT7615 — read the per-subcarrier TxBF (PFMU) profile over RACFG/HQA.
#
# This is the readback that crash-reboots the device in NORMAL AP mode (the
# 0xED/0x1E MCU command blocks and the 31 s watchdog resets the SoC). The fix,
# found by reverse engineering, is to put the radio in ATE/RF-test mode FIRST:
# MT_ATEStart calls MtCmdATEModeCtrl(1) and sets the completion timeout to 3 s,
# so the readback event is wired up and the command returns cleanly instead of
# hanging. In ATE mode the full sweep below runs with NO reboots.
#
# Sequence (all driver-internal, driven over SSH + one raw-Ethernet RACFG read):
#   on device:  iwpriv ra0 set ATE=ATESTART        # enter ATE mode (safe, no crash)
#               ated -f -u -b br-lan -i ra0         # QA bridge daemon
#   on PC:      RACFG HQA_BFProfileDataRead (0x1554) per subcarrier
#
# RACFG HQA_BFProfileDataRead request data = 4x u32 BE: [pfmu_idx, fgBFer, sub_start, sub_end]
# (sub_start==sub_end reads one subcarrier; a range reads many in one round trip).
# Reply payload: [00000000][u16 count][ profile bytes ... ][padding].
#
# NOTE ON MEANING: reading an *unconfigured* PFMU returns stable but structureless
# data (it is not a live channel). A meaningful profile requires either a real BF
# sounding of a transmitter (explicit BF -> channel H / AoA) or the iBF phase-cal
# path (ATEIBfInstCal -> internal per-chain phase offsets). This tool is the
# verified readback mechanism those build on.
#
# Usage:  sudo python3 bf_profile_read.py [iface] [pfmu_idx] [n_subcarriers]
#   iface defaults to ra0 (2.4GHz); use rax0 for 5GHz.  Requires an ssh alias "dir1750".
import socket, struct, time, json, sys, subprocess, math

IFACE_WIFI = sys.argv[1] if len(sys.argv) > 1 else "ra0"
PFMU       = int(sys.argv[2]) if len(sys.argv) > 2 else 0
NSUB       = int(sys.argv[3]) if len(sys.argv) > 3 else 128
SSH        = ["ssh", "-o", "ConnectTimeout=8", "dir1750"]
PC_IFACE   = "eno2"
DEV_MAC    = bytes.fromhex("bc2228109a9d")      # device br-lan MAC
ET         = 0x2880
MAGIC      = bytes([0x18, 0x14, 0x28, 0x80])

def ssh(cmd): return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=20).stdout

def src_mac():
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW); s.bind((PC_IFACE, 0))
    m = s.getsockname()[4]; s.close(); return m

SRC = src_mac()

def racfg(cmd_id, data, timeout=4.0):
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ET)); s.bind((PC_IFACE, ET)); s.settimeout(timeout)
    s.send(DEV_MAC + SRC + struct.pack(">H", ET) + MAGIC + struct.pack(">HHHH", 8, cmd_id, len(data), 0) + data)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try: pkt = s.recv(4096)
        except socket.timeout: break
        if struct.unpack(">H", pkt[12:14])[0] == ET and pkt[6:12] == DEV_MAC:
            L = struct.unpack(">H", pkt[14+8:14+10])[0]
            return pkt[14+12:14+12+max(L, 0)]
    return None

def read_subcarrier(sc):
    d = racfg(0x1554, struct.pack(">IIII", PFMU, 1, sc, sc))
    return d[6:18].hex() if (d and len(d) >= 18) else None

def main():
    print(f"[*] entering ATE mode on {IFACE_WIFI} and starting ated ...")
    ssh(f"iwpriv {IFACE_WIFI} set DebugCategory=0x40 >/dev/null 2>&1; "
        f"iwpriv {IFACE_WIFI} set ATE=ATESTART >/dev/null 2>&1; "
        f"killall ated 2>/dev/null; sleep 1; "
        f"nohup ated -f -u -b br-lan -i {IFACE_WIFI} >/tmp/ated.log 2>&1 </dev/null & sleep 2")
    up = ssh("uptime").strip()
    print(f"[*] device: {up}")
    rows = {}
    for sc in range(NSUB):
        h = read_subcarrier(sc)
        if h: rows[sc] = h
    print(f"[*] read {len(rows)}/{NSUB} subcarriers (pfmu {PFMU})")
    out = f"bf_profile_{IFACE_WIFI}_pfmu{PFMU}.json"
    json.dump(rows, open(out, "w"))
    # decode hypothesis: 3x(I,Q) int16 LE -> per-antenna magnitude/phase
    for sc in [0, 1, 2, 10, 40, 80]:
        if sc in rows:
            v = struct.unpack("<6h", bytes.fromhex(rows[sc]))
            ph = [round(math.degrees(math.atan2(v[a*2+1], v[a*2])), 1) for a in range(3)]
            print(f"    sub{sc:3d}  IQ={v}  phase(deg)={ph}")
    print(f"[*] saved {out}")
    print(f"[!] device left in ATE mode — restore with: ssh dir1750 'iwpriv {IFACE_WIFI} set ATE=ATESTOP' (or reboot)")

if __name__ == "__main__":
    main()
