#!/usr/bin/env python3
# Live per-antenna RSSI display for the DIR-1750 (MT7615), cleaner than df_live.py.
#
# Uses `iwpriv <iface> stat`, whose "RSSI = a b c d" line is the driver's own
# per-chain RSSI readout -- no dmesg parsing, no DebugCategory, works in NORMAL
# operation (no ATE mode needed) as long as a station is associated and sending.
#
# This radio is 3x3:3 (AC1750 class): there are only THREE RX chains, so the 4th
# value is always -127 (noise floor). ANT0..ANT2 are the real array.
#
# Associate ANY transmitting station to the router first. The PC's own Wi-Fi radio
# works well as a controlled test station (this PC uses Ethernet for internet):
#     nmcli con up dlink-9A9D
#     ping -I <wlan-iface> -i 0.01 192.168.1.254   # steady uplink so RSSI stays fresh
#
# Ctrl-C to stop.
import subprocess, re, sys, time

SSH   = ["ssh","-o","ConnectTimeout=6","-o","ServerAliveInterval=3","dir1750"]
IFACE = sys.argv[1] if len(sys.argv) > 1 else "rax0"   # rax0 = 5GHz, ra0 = 2.4GHz
LO, HI, WIDTH = -85, -30, 46
RSSI_RE = re.compile(r'RSSI\s*=\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)')

def ssh(cmd):
    try: return subprocess.run(SSH+[cmd], capture_output=True, text=True, timeout=8).stdout
    except Exception: return ""

def bar(v):
    if v <= -127: return "·"*WIDTH + "   (no 4th chain — this is a 3x3 radio)"
    n = max(0, min(WIDTH, round((v-LO)/(HI-LO)*WIDTH)))
    return "█"*n + "·"*(WIDTH-n) + f"   {v:4d} dBm"

sys.stdout.write("\033[2J")
frame = 0
while True:
    m = RSSI_RE.search(ssh(f"iwpriv {IFACE} stat 2>/dev/null"))
    sys.stdout.write("\033[H")
    print(f"  DIR-1750 ({IFACE})  ·  LIVE per-antenna RSSI  ·  move the TX     (Ctrl-C to stop)")
    print("  "+"="*70)
    if m:
        r = [int(x) for x in m.groups()]
        act = r[:3]; strongest = act.index(max(act))
        for i, v in enumerate(r):
            mark = " ◄ strongest" if (i == strongest and v > -127) else ""
            col  = "\033[92m" if mark else ("\033[90m" if v <= -127 else "\033[97m")
            print(f"  ANT{i} {col}{bar(v)}\033[0m{mark}        ")
        spread = max(act) - min(act)
        print("  "+"-"*70)
        print(f"  strongest: ANT{strongest}    3-chain spread: {spread:2d} dB    "
              f"(big spread + shifting strongest = bearing changing)      ")
    else:
        print("  ...no station associated / transmitting on this band.                    ")
        print("  "*3)
    frame += 1
    print(f"\n  frame {frame}   ~1 Hz   source: iwpriv {IFACE} stat (RSSI line)              ")
