"""Grep the main program's Thumb disassembly for a regex. Usage: grepasm.py <entry00.bin> <regex>"""
import struct, sys, re
import capstone
e0 = open(sys.argv[1], 'rb').read(); rx = re.compile(sys.argv[2])
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off); segs.append((off + 12, slen, dst)); off = nxt
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS); md.skipdata = True
for p, l, d in segs:
    for ins in md.disasm(e0[p:p + l], d):
        s = f'{ins.mnemonic} {ins.op_str}'
        if rx.search(s): print(f'{ins.address:#x}: {s}')
