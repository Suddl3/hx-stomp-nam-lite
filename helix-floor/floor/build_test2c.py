#!/usr/bin/env python3
"""test2c_bigslot_heaps.hxf: test2b (last big slot per path graph -> normal sizes, Entry 5) plus
Entry 2's heaps a (Block 0 DM) and b (Block 3 PM) shrunk to the new budget sums, as stock sizes
them: each heap = the larger of the two graphs' sums. That frees the heap tails for our own use.

test2b (Entry 5 alone) booted. This asks: does the DSP accept smaller heaps that still match
the slot budgets? Boots and plays -> we can take memory from the blocks for NAM.

PC only, never share.
usage: build_test2c.py <stock Floor .hxf>
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import floor_hxf  # noqa: E402
from stage_slots import GRAPHS, HEAP_A, HEAP_B, sums, halfwords, from_halfwords, replace_once  # noqa: E402
from build_test2b import shrink_last_big  # noqa: E402
from build_staged import check_and_pack  # noqa: E402
import struct  # noqa: E402


def graph_sums(e5):
    w = list(struct.unpack('<%dI' % (len(e5) // 4), e5))
    ln, off = w[w[3]], w[w[3] + 1]
    b0 = w[off:off + ln]
    return [sums(b0, g) for g in GRAPHS]


def shrink_heaps_to(e2_raw, dm_size, pm_size):
    dm, pm = HEAP_A[2] - dm_size, HEAP_B[2] - pm_size
    a_end, b_end = HEAP_A[1] - dm, HEAP_B[1] - pm
    H = halfwords(e2_raw)
    rep = []
    for old, new, what in (
            ([0x0F15, HEAP_A[1] >> 16, HEAP_A[1] & 0xFFFF], [0x0F15, a_end >> 16, a_end & 0xFFFF], "heap a end"),
            ([0x0F8C, HEAP_A[2]], [0x0F8C, dm_size], "heap a size"),
            ([0x0F12, HEAP_B[1] >> 16, HEAP_B[1] & 0xFFFF], [0x0F12, b_end >> 16, b_end & 0xFFFF], "heap b end"),
            ([0x0F8C, HEAP_B[2]], [0x0F8C, pm_size], "heap b size")):
        k = replace_once(H, old, new, what)
        rep.append(f"{what}: w{k // 2} {' '.join(f'{x:04x}' for x in old)} -> {' '.join(f'{x:04x}' for x in new)}")
    rep.append(f"freed: DM {a_end:#x}..{HEAP_A[1]:#x} ({dm} words), PM {b_end:#x}..{HEAP_B[1]:#x} ({pm} words)")
    return from_halfwords(H), rep


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    e5 = pa.get_entry_swapped(data, 5)
    assert max(s[0] for s in graph_sums(e5)) == HEAP_A[2] and max(s[1] for s in graph_sums(e5)) == HEAP_B[2]
    new5, rep = shrink_last_big(e5)
    after = graph_sums(new5)
    dm_size, pm_size = max(s[0] for s in after), max(s[1] for s in after)
    ents = l6ia.parse(data)
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    new2, rep2 = shrink_heaps_to(e2, dm_size, pm_size)
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new2), 5: new5})
    nents = l6ia.parse(img)
    for i in range(len(ents)):
        if i in (2, 5):
            continue
        a = img[nents[i]['payload_off']: nents[i]['payload_off'] + nents[i]['payload_len']]
        b = data[ents[i]['payload_off']: ents[i]['payload_off'] + ents[i]['payload_len']]
        assert a == b, f"Entry {i} differs from stock"
    for line in rep + rep2:
        print(line)
    print(f"heaps: a {HEAP_A[2]:#x} -> {dm_size:#x}, b {HEAP_B[2]:#x} -> {pm_size:#x} (= larger graph sums {after})")
    check_and_pack(img, "test2c_bigslot_heaps.hxf", raw)


if __name__ == "__main__":
    main()
