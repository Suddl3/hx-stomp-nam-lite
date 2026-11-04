"""Thumb-2 disassembly of the main program (Entry 0) by load address.
Usage: disasm.py <entry00.bin> <start_va> <end_va>"""
import struct, sys
import capstone

e0 = open(sys.argv[1], 'rb').read()
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off)
    segs.append((off + 12, slen, dst))
    off = nxt

def fo(v):
    for p, l, d in segs:
        if d <= v < d + l:
            return p + v - d

start, end = int(sys.argv[2], 0), int(sys.argv[3], 0)
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
code = e0[fo(start):fo(start) + (end - start)]
for ins in md.disasm(code, start):
    extra = ''
    if ins.mnemonic.startswith('ldr') and 'pc' in ins.op_str and '#' in ins.op_str:
        try:
            imm = int(ins.op_str.split('#')[-1].rstrip(']'), 0)
            lit = ((ins.address + 4) & ~3) + imm
            extra = f'   ; ={struct.unpack_from("<I", e0, fo(lit))[0]:#x}'
        except (ValueError, TypeError):
            pass
    print(f'{ins.address:#x}: {ins.mnemonic:8} {ins.op_str}{extra}')
