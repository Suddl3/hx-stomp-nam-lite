#!/usr/bin/env python3
"""Build stage B1 + C (slots): the 13-block layout.

Graph library (Entry 5): in both path graphs (0x600000, 0x600001) the block-slot pool
(members of type 0x600006: 13 normal, then 3 big) loses its last big slot and its last
two normal slots. They keep their member records (every index stays where it was, in
case anything names a slot by its place in the pool) but get DM, PM and SDRAM budgets of
0, so no block fits them.

DSP program (Entry 2): heap a (Block 0 DM) and heap b (Block 3 PM) end earlier by the
freed DM and PM, and their size immediates shrink to match: each heap stays exactly the
larger of the two graphs' summed budgets, as stock. The freed tails are the kernel's
static regions R3 (0x9aba7..0x9ba5f) and R2 (0xe6072..0xe674a) in floor/nam_floor.py.
Heap c (DDR2 SDRAM) is left as it is (bigger than needed is harmless; the kernel's SDRAM
comes from its own instance's block).

usage: stage_slots.py <in .hxf | .l6ia> <out.l6ia>
"""
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import l6ia  # noqa: E402
import patch_amp  # noqa: E402
import nam_floor  # noqa: E402

GRAPHS = (0x600000, 0x600001)
SLOT_TYPE = 0x600006
NORMAL, BIG = (0x3AE, 0x1E6), (0x75C, 0x30C)
HEAP_A = (0x96BA4, 0x9BA5F, 0x4EBB)      # start, end, size (Block 0 DM)
HEAP_B = (0xE4466, 0xE674A, 0x22E4)      # (Block 3 PM)


def graph_members(b0, comp):
    ct = b0[0x10]
    h = b0[ct + 7 * (comp - 0x600000): ct + 7 * (comp - 0x600000) + 7]
    return h[3], h[2]


def sums(b0, comp):
    base, n = graph_members(b0, comp)
    s = [0, 0, 0]
    for k in range(n):
        r = b0[base + 20 * k: base + 20 * k + 20]
        if r[4] == 0:
            s = [s[0] + r[13], s[1] + r[14], s[2] + r[15]]
    return s


def zero_slots(e5):
    """e5: Entry 5, swapped (little-endian words). Returns (new bytes, freed DM, freed PM, report)."""
    w = list(struct.unpack('<%dI' % (len(e5) // 4), e5))
    ln, off = w[w[3]], w[w[3] + 1]
    b0 = w[off:off + ln]
    rep, freed = [], None
    for g in GRAPHS:
        base, n = graph_members(b0, g)
        slots = [k for k in range(n) if b0[base + 20 * k + 4] == 0 and b0[base + 20 * k + 6] == SLOT_TYPE]
        sizes = [(b0[base + 20 * k + 13], b0[base + 20 * k + 14]) for k in slots]
        assert sizes == [NORMAL] * 13 + [BIG] * 3, f"{g:#x}: not the stock 13 + 3 pool: {sizes}"
        gone = [slots[11], slots[12], slots[15]]           # the last two normal, the last big
        before = sums(b0, g)
        for k in gone:
            r = base + 20 * k
            b0[r + 13] = b0[r + 14] = b0[r + 15] = 0
        after = sums(b0, g)
        f = (before[0] - after[0], before[1] - after[1])
        assert f == (2 * NORMAL[0] + BIG[0], 2 * NORMAL[1] + BIG[1]), f
        freed = f
        rep.append(f"{g:#x}: members {gone} zeroed; DM {before[0]:#x} -> {after[0]:#x}, PM {before[1]:#x} -> "
                   f"{after[1]:#x}, SDRAM {before[2]:#x} -> {after[2]:#x}")
    w[off:off + ln] = b0
    return struct.pack('<%dI' % len(w), *w), freed, rep, [sums(b0, g) for g in GRAPHS]


def halfwords(raw):
    w = struct.unpack('<%dI' % (len(raw) // 4), raw)
    H = []
    for x in w:
        H += [x >> 16, x & 0xFFFF]
    return H


def from_halfwords(H):
    return struct.pack('<%dI' % (len(H) // 2), *[(H[2 * i] << 16) | H[2 * i + 1] for i in range(len(H) // 2)])


def replace_once(H, old, new, what):
    n, hits = len(old), []
    for k in range(len(H) - n):
        if H[k:k + n] == old:
            hits.append(k)
    assert len(hits) == 1, f"{what}: {len(hits)} matches of {[hex(x) for x in old]}"
    H[hits[0]:hits[0] + n] = new
    return hits[0]


def shrink_heaps(e2_raw, dm, pm):
    """e2_raw: Entry 2 as stored (upstream reads it as little-endian words)."""
    H = halfwords(e2_raw)
    a_end, b_end = HEAP_A[1] - dm, HEAP_B[1] - pm
    assert (a_end, b_end) == (nam_floor.REGIONS["R3"][0], nam_floor.REGIONS["R2"][0]), "regions disagree"
    rep = []
    for old, new, what in (
            ([0x0F15, HEAP_A[1] >> 16, HEAP_A[1] & 0xFFFF], [0x0F15, a_end >> 16, a_end & 0xFFFF], "heap a end"),
            ([0x0F8C, HEAP_A[2]], [0x0F8C, HEAP_A[2] - dm], "heap a size"),
            ([0x0F12, HEAP_B[1] >> 16, HEAP_B[1] & 0xFFFF], [0x0F12, b_end >> 16, b_end & 0xFFFF], "heap b end"),
            ([0x0F8C, HEAP_B[2]], [0x0F8C, HEAP_B[2] - pm], "heap b size")):
        k = replace_once(H, old, new, what)
        rep.append(f"{what}: halfword {k} (w{k // 2}) {' '.join(f'{x:04x}' for x in old)} -> "
                   f"{' '.join(f'{x:04x}' for x in new)}")
    return from_halfwords(H), rep


def main():
    src, out = sys.argv[1], sys.argv[2]
    data, _ = patch_amp.load_l6ia_from_any(src)
    ents = l6ia.parse(data)
    e5 = patch_amp.get_entry_swapped(data, 5)
    new5, (dm, pm), rep5, after = zero_slots(e5)
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    new2, rep2 = shrink_heaps(e2, dm, pm)
    heap_dm, heap_pm = HEAP_A[2] - dm, HEAP_B[2] - pm
    assert max(s[0] for s in after) == heap_dm and max(s[1] for s in after) == heap_pm, "budgets != heaps"
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new2), 5: new5})
    open(out, 'wb').write(img)
    for line in rep5 + rep2:
        print(line)
    print(f"heaps: a {HEAP_A[2]:#x} -> {heap_dm:#x}, b {HEAP_B[2]:#x} -> {heap_pm:#x} (= the larger graph's sums)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
