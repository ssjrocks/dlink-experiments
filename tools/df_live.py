#!/usr/bin/env python3
# Live per-antenna RSSI display for the DIR-1750 (MT7615). Watch it move as you carry the phone.
# Reads the associated station's RSSI0/1/2/3 off the router (5GHz rax0, falls back to 2.4 ra0).
# Ctrl-C to stop.
import subprocess, re, time, sys

SSH = ["ssh","-o","ConnectTimeout=6","-o","ServerAliveInterval=3","dir1750"]
LO, HI = -85, -30           # dBm -> bar scale
WIDTH = 46

def ssh(cmd):
    try: return subprocess.run(SSH+[cmd], capture_output=True, text=True, timeout=8).stdout
    except Exception: return ""

def bar(v):
    if v <= -127:
        return "·"*WIDTH + "   (idle / floor)"
    n = max(0, min(WIDTH, round((v-LO)/(HI-LO)*WIDTH)))
    return "█"*n + "·"*(WIDTH-n) + f"   {v:4d} dBm"

ssh("iwpriv rax0 set DebugCategory=0x1 >/dev/null 2>&1; iwpriv ra0 set DebugCategory=0x1 >/dev/null 2>&1")
CMD = ("dmesg -c >/dev/null 2>&1; iwpriv rax0 show stainfo >/dev/null 2>&1; "
       "iwpriv ra0 show stainfo >/dev/null 2>&1; sleep 1; "
       "dmesg 2>/dev/null | grep -E ':[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2} +[0-9]'")
sys.stdout.write("\033[2J")
last=[None]*4; frame=0
while True:
    out = ssh(CMD)
    m = re.search(r'(-\d+)/(-\d+)/(-\d+)/(-\d+)', out)
    sys.stdout.write("\033[H")   # cursor home
    print("  DIR-1750  ·  LIVE per-antenna RSSI  ·  move the phone     (Ctrl-C to stop)")
    print("  "+"="*70)
    if m:
        r=[int(x) for x in m.groups()]; last=r
        act=r[:3]; strongest=act.index(max(act))
        names="ANT0 ANT1 ANT2 ANT3".split()
        for i,v in enumerate(r):
            mark=" ◄ strongest" if (i==strongest and v>-127) else ""
            col="\033[92m" if mark else ("\033[90m" if v<=-127 else "\033[97m")
            print(f"  {names[i]} {col}{bar(v)}\033[0m{mark}        ")
        spread=max(act)-min(act)
        # crude lean: compare ant0 vs ant2 difference
        print("  "+"-"*70)
        print(f"  strongest: ANT{strongest}    antenna spread: {spread:2d} dB    "
              f"(big spread + shifting strongest = direction changing)      ")
    else:
        print("  ...waiting for station (is the phone connected + transmitting?)                 ")
        print("  "*3)
    frame+=1
    print(f"\n  frame {frame}   ~1 Hz   data: router station table (rax0/ra0)                   ")
