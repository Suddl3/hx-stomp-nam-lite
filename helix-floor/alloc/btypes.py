"""Browser lists of the main program: block type byte (bt) per category, with sample models.
Usage: btypes.py <entry00.bin> <model DB .bin> <BLIST_PTR_TAB va>"""
import struct, sys, collections
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import TOOLS; sys.path.insert(0, TOOLS)
from patch_amp import parse_entry3_full
e0 = open(sys.argv[1], 'rb').read()
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off); segs.append((off + 12, slen, dst)); off = nxt
def fo(va):
    return next((p + va - d for p, l, d in segs if d <= va < d + l), None)
u32 = lambda va: struct.unpack_from('<I', e0, fo(va))[0]
info = parse_entry3_full(open(sys.argv[2], 'rb').read())
byname = {m['words'][2]: m for m in info['models']}
ptab = int(sys.argv[3], 0); ctab = ptab + 76 * 4
out = collections.defaultdict(lambda: collections.Counter())
for idx in range(76):
    lp, lc = u32(ptab + 4 * idx), u32(ctab + 4 * idx)
    if not lp or fo(lp) is None or lc > 400: continue
    for k in range(lc):
        bt, mi, ci = struct.unpack_from('<IIi', e0, fo(lp + 48 * k))
        m = byname.get(mi)
        out[bt][(idx // 4, idx % 4, m['meta'].get('category') if m else '?', ci >= 0)] += 1
for bt in sorted(out):
    print(f'bt {bt:#04x}:', dict(out[bt]))
