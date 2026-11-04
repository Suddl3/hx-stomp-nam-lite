"""Functions (push-started) in the main program with no direct calls/branches and no address
references (literal pools, movw/movt, adr). Read-only. Usage: deadfuncs.py <entry00.bin> [min bytes]"""
import struct, sys, bisect
import capstone
e0 = open(sys.argv[1], 'rb').read(); minb = int(sys.argv[2]) if len(sys.argv) > 2 else 160
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off); segs.append((off + 12, slen, dst)); off = nxt
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS); md.skipdata = True
starts, targets, words = [], set(), set()
for p, l, d in segs:
    for k in range(0, l - 3, 2):
        words.add(struct.unpack_from('<I', e0, p + k)[0])       # any 32-bit value anywhere (literals, tables)
    movw = {}
    for ins in md.disasm(e0[p:p + l], d):
        m, o = ins.mnemonic, ins.op_str
        if m.startswith('push') and 'lr' in o:
            starts.append(ins.address)
        if m in ('bl', 'b.w', 'b', 'blx', 'cbz', 'cbnz', 'beq', 'bne') or m.startswith('b'):
            t = o.split('#')[-1]
            try: targets.add(int(t, 0))
            except ValueError: pass
        if m == 'movw' and '#' in o:
            movw[o.split(',')[0]] = int(o.split('#')[-1], 0) & 0xffff
        if m == 'movt' and '#' in o and o.split(',')[0] in movw:
            words.add((int(o.split('#')[-1], 0) << 16) | movw.pop(o.split(',')[0]))
starts.sort()
for i, s in enumerate(starts[:-1]):
    size = starts[i + 1] - s
    if size < minb: continue
    if s in targets or (s | 1) in words or s in words: continue
    # the function may start a few bytes before its push (sub sp / mov): check those too
    if any((s - k) in targets or ((s - k) | 1) in words for k in (2, 4, 6, 8)): continue
    print(f'{s:#x} ~{size} bytes')
