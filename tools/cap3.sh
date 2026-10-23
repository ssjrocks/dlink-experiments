#!/bin/bash
LOG="$1"; DUR="${2:-40}"; : > "$LOG"
ssh -o ConnectTimeout=6 dir1750 "iwpriv rax0 set DebugCategory=0x1 >/dev/null 2>&1; iwpriv ra0 set DebugCategory=0x1 >/dev/null 2>&1" 2>/dev/null
t0=$(date +%s)
while [ $(( $(date +%s) - t0 )) -lt $DUR ]; do
  r=$(ssh -o ConnectTimeout=6 dir1750 "dmesg -c >/dev/null 2>&1; iwpriv rax0 show stainfo >/dev/null 2>&1; iwpriv ra0 show stainfo >/dev/null 2>&1; sleep 1; dmesg 2>/dev/null | grep -E ':[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2} +[0-9]'" 2>/dev/null | grep -oE '\-[0-9]+/\-[0-9]+/\-[0-9]+/\-[0-9]+' | head -1)
  [ -n "$r" ] && echo "$(( $(date +%s) - t0 )) $r" >> "$LOG"
done
echo "DONE $(wc -l < "$LOG") samples"
