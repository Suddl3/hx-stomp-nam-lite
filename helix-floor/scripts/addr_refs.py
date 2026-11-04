"""List every address the main program's code builds (PC-relative literal loads and movw/movt
pairs) that falls inside the given ranges. Read-only.
Usage: addr_refs.py <entry00.bin> <lo>:<hi> [<lo>:<hi> ...]"""
import struct, sys
import capstone

e0 = open(sys.argv[1], 'rb').read()
ranges = [tuple(int(x, 0) for x in r.split(':')) for r in sys.argv[2:]]
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off)
    segs.append((off + 12, slen, dst))
    off = nxt

def fo(v):
    for p, l, d in segs:
        if d <= v < d + l:
            return p + v - d

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
md.detail = True
md.skipdata = True
hits = {}
for p, l, d in segs:
    movw = {}
    for ins in md.disasm(e0[p:p + l], d):
        ops = ins.operands if ins.id else []
        val = None
        if ins.mnemonic.startswith('ldr') and len(ops) == 2 and ops[1].type == capstone.arm.ARM_OP_MEM \
                and ops[1].mem.base == capstone.arm.ARM_REG_PC:
            lit = ((ins.address + 4) & ~3) + ops[1].mem.disp
            o = fo(lit)
            if o is not None and o + 4 <= len(e0):
                val = struct.unpack_from('<I', e0, o)[0]
        elif ins.mnemonic in ('movw', 'mov.w', 'movs', 'mov') and len(ops) == 2 and ops[1].type == capstone.arm.ARM_OP_IMM:
            movw[ops[0].reg] = ops[1].imm & 0xffff
        elif ins.mnemonic == 'movt' and len(ops) == 2 and ops[0].reg in movw:
            val = (ops[1].imm << 16) | movw.pop(ops[0].reg)
        elif ins.mnemonic == 'adr' and len(ops) == 2:
            val = ((ins.address + 4) & ~3) + ops[1].imm
        if val is not None and any(lo <= val < hi for lo, hi in ranges):
            hits.setdefault(val, []).append(ins.address)
for v in sorted(hits):
    print(f'{v:#x} built at {[hex(a) for a in hits[v][:5]]}{" ..." if len(hits[v]) > 5 else ""}')
print(f'{len(hits)} distinct addresses in range')
