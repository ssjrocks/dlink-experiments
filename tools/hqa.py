#!/usr/bin/env python3
# Working MediaTek RACFG/HQA client for the DIR-1750 (MT7615) via ated.
# RE'd from ated + mt_wifi.ko (Ghidra). Talks raw Ethernet (ethertype 0x2880) to ated,
# which forwards to the driver. Validated: returns live chip ID, fw build, per-antenna RSSI.
#
# RACFG frame: Ethernet{dst=device, src=PC, ethertype 0x2880} + payload:
#   +0 magic  = 18 14 28 80
#   +4 cmd_type u16 BE = 0x0008   (MUST be 8 or 9, else ated drops it)
#   +6 cmd_id   u16 BE
#   +8 length   u16 BE = len(data)
#   +0xa seq    u16
#   +0xc data...
# Reply: same, cmd_type |= 0x8000 (response bit).
#
# Usage:  sudo python3 hqa.py <cmd_id|name> [data_hex]
#         sudo python3 hqa.py chipid
#         sudo python3 hqa.py rxstat        # per-antenna RSSI (needs a signal to be meaningful)
import socket, struct, sys, time, binascii

IFACE   = "eno2"
DEV_MAC = bytes.fromhex("bc222810 9a9d".replace(" ",""))
ET      = 0x2880
MAGIC   = bytes([0x18,0x14,0x28,0x80])

CMDS = {  # RE'd from the driver HQA dispatch table
 "fwinfo":0x1500, "chipid":0x1514, "rxsnr":0x1510, "fft":0x1512, "rxstat":0x1506,
 "calmode":0x1509, "bandmode":0x152c, "wifipoweroff":0x152b,
 "bf_sounding":0x1556, "bf_qdread":0x155b, "bf_profread":0x1554, "manual_assoc":0x155a,
 "txbf_tag_matrix":0x1546, "starec_bf":0x1553,
}

def mac_of(iface):
    s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW); s.bind((iface,0))
    m=s.getsockname()[4]; s.close(); return m

def xact(cmd_id, data=b"", timeout=3.0):
    src=mac_of(IFACE)
    s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(ET)); s.bind((IFACE,ET)); s.settimeout(timeout)
    payload=MAGIC+struct.pack(">HHHH",8,cmd_id,len(data),0)+data
    s.send(DEV_MAC+src+struct.pack(">H",ET)+payload)
    t0=time.time()
    while time.time()-t0<timeout:
        try: pkt=s.recv(4096)
        except socket.timeout: break
        if struct.unpack(">H",pkt[12:14])[0]==ET and pkt[6:12]==DEV_MAC:
            rac=pkt[14:]; L=struct.unpack(">H",rac[8:10])[0]
            return rac[6:8], L, rac[12:12+L] if L else rac[12:12+32]
    return None,0,None

def main():
    a=sys.argv[1]; cmd=CMDS[a] if a in CMDS else int(a,0)
    data=bytes.fromhex(sys.argv[2]) if len(sys.argv)>2 else b""
    cid,L,d=xact(cmd,data)
    if d is None: print("no reply"); return
    print(f"cmd=0x{cmd:04x} resp_len={L} data={binascii.hexlify(d).decode()}")
    if cmd==0x1514 and len(d)>=6: print(f"  chip_id=0x{d[4]<<8|d[5]:04x}")
    if cmd==0x1500: print("  fw:",d.split(b'\x00')[0][1:].decode('latin1',' '), d[4:].split(b'\x00')[0].decode('latin1',' '))
    if cmd==0x1506 and len(d)>=0x40:
        # per-antenna RSSI = four int32 near offset 0x2c (0xffffff80 = -128 = no signal)
        vals=[struct.unpack('<i',d[i:i+4])[0] for i in range(0,len(d)-3,4)]
        ants=[v for v in vals if -130<v<30]
        print("  candidate per-antenna RSSI (dBm):", ants[:8])

if __name__=="__main__": main()
