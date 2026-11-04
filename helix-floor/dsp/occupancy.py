"""Floor SHARC (Entry 2) memory occupancy from the LDR boot stream, in normal-word addresses.
Usage: occupancy.py <entry02.bin>"""
import struct, sys

d = open(sys.argv[1], 'rb').read()
W = struct.unpack('>%dI' % (len(d) // 4), d)
NW = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2, 6: lambda c: c * 2,
      0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
NAMES = {1: 'ZERO_L32', 2: 'ZERO_L48', 3: 'INIT_L16', 4: 'INIT_L32', 5: 'INIT_L48', 6: 'INIT_L64',
         7: 'ZERO_EXT8', 8: 'ZERO_EXT16', 9: 'INIT_EXT8', 10: 'INIT_EXT16'}
# 21469 internal blocks: normal-word base, short-word base, 48-bit (instruction) base, size in normal words
BLK = [(0x80000, 0x100000, 0x80000, 0x8000), (0xa0000, 0x140000, 0xa0000, 0x8000),
       (0xc0000, 0x180000, 0xc0000, 0x8000), (0xe0000, 0x1c0000, 0xe0000, 0x8000)]

def to_normal(tag, cnt, addr):
    if tag in (2, 5):                                   # 48-bit instruction addresses
        for nb, sb, ib, sz in BLK:
            if ib <= addr < ib + sz * 2 // 3:
                return nb + (addr - ib) * 3 // 2, nb + ((addr + cnt - ib) * 3 + 1) // 2
    if tag == 3:                                        # 16-bit short-word addresses
        for nb, sb, ib, sz in BLK:
            if sb <= addr < sb + 2 * sz:
                return nb + (addr - sb) // 2, nb + (addr + cnt - sb + 1) // 2
    if tag == 6:
        return addr, addr + 2 * cnt
    return addr, addr + cnt

i, spans = 384, []
while i + 3 <= len(W):
    tag, cnt, addr = W[i:i + 3]
    if tag == 0:
        break
    lo, hi = to_normal(tag, cnt, addr)
    spans.append((lo, hi, tag, i))
    i += 3 + NW.get(tag, lambda c: 0)(cnt)

def merged(lo_lim, hi_lim):
    s = sorted((max(lo, lo_lim), min(hi, hi_lim), t) for lo, hi, t, _ in spans if lo < hi_lim and hi > lo_lim)
    out = []
    for lo, hi, t in s:
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi), out[-1][2] | {t})
        else:
            out.append((lo, hi, {t}))
    return out

for name, lo, hi in (('Block 0', 0x80000, 0x88000), ('Block 1', 0xa0000, 0xa8000),
                     ('Block 2', 0xc0000, 0xc8000), ('Block 3', 0xe0000, 0xe8000),
                     ('External (DDR2)', 0x200000, 0x1000000)):
    m = merged(lo, hi)
    print(f"== {name} {lo:#x}..{hi:#x}")
    prev = lo
    for a, b, tags in m:
        if a > prev:
            print(f"   FREE  {prev:#x}..{a:#x}  ({a - prev:#x} words)")
        print(f"   used  {a:#x}..{b:#x}  {sorted(NAMES.get(t, t) for t in tags)}")
        prev = b
    if prev < hi and name != 'External (DDR2)':
        print(f"   FREE  {prev:#x}..{hi:#x}  ({hi - prev:#x} words)")
    elif name == 'External (DDR2)':
        print(f"   (last LDR-initialized external word: {prev:#x})")
