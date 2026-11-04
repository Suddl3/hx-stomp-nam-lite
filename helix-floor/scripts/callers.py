"""List bl/b.w call sites of given target addresses in the main program.
Usage: callers.py <entry00.bin> <target> [<target> ...]"""
import struct, sys
import capstone
e0 = open(sys.argv[1], 'rb').read()
tg = {int(x, 0) for x in sys.argv[2:]}
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off)
    segs.append((off + 12, slen, dst)); off = nxt
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
md.skipdata = True
for p, l, d in segs:
    for ins in md.disasm(e0[p:p + l], d):
        if ins.mnemonic in ('bl', 'b.w', 'blx') and ins.op_str.startswith('#'):
            t = int(ins.op_str[1:], 0)
            if t in tg:
                print(f'{ins.address:#x} {ins.mnemonic} {t:#x}')
