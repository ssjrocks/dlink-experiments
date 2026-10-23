#!/usr/bin/env python3
# Live per-antenna RSSI monitor for the DIR-1750 (MT7615) — coarse amplitude direction finding.
# Reads RSSI0/1/2/3 of the associated S23 from the router's station table, displays live bars.
import subprocess, re, time, sys

SSH = ["ssh","-o","ConnectTimeout=6","dir1750"]
S23 = "AA:BB:CC"   # client (phone) wlan0 MAC prefix — set to your test device's OUI
DUR = int(sys.argv[1]) if len(sys.argv)>1 else 30

def sh(cmd):
    try: return subprocess.run(SSH+[cmd],capture_output=True,text=True,timeout=8).stdout
    except: return ""

def bar(rssi):
    # map -90..-30 dBm -> 0..40 chars
    if rssi<=-127: return "(no signal)"
    n=max(0,min(40,int((rssi+90)/60*40)))
    return "█"*n + "·"*(40-n) + f"  {rssi:4d} dBm"

sh("iwpriv ra0 set DebugCategory=0x1 >/dev/null 2>&1")
print(f"Live per-antenna RSSI (S23) — move the phone to see it change. {DUR}s\n")
t0=time.time()
# one persistent device loop would be faster; keep per-sample for clarity
while time.time()-t0<DUR:
    out=sh("dmesg -c >/dev/null 2>&1; iwpriv ra0 show stainfo >/dev/null 2>&1; sleep 0.3; dmesg 2>/dev/null | grep '"+S23+"'")
    m=re.search(r'(-?\d+)/(-?\d+)/(-?\d+)/(-?\d+)', out)
    if m:
        r=[int(x) for x in m.groups()]
        print("\033[2J\033[H", end="")   # clear
        print(f"  DIR-1750 per-antenna RSSI (live)   t+{time.time()-t0:4.0f}s\n")
        for i,v in enumerate(r):
            print(f"  ant{i}  {bar(v)}")
        active=[v for v in r if v>-127]
        if active:
            strongest=r.index(max(active))
            print(f"\n  strongest: ant{strongest}   spread: {max(active)-min(active)} dB")
    time.sleep(0.4)
print("\ndone.")
