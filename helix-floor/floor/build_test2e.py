#!/usr/bin/env python3
"""test2e_normal_half.hxf: test2c (last big slot per path graph -> normal sizes, heaps shrunk to
match) plus one normal slot per path graph (the last normal one) shrunk to half its DM and PM
(0x3ae -> 0x1d7, 0x1e6 -> 0xf3; its other size words unchanged), heaps shrunk to the new sums.

test2/2a (DM/PM/SDRAM zero, word 17 left) failed at boot; test2b/2c (a full legal record) passed.
This asks: does the Floor accept a slot smaller than the normal size? If yes, the freed words
(about 470 DM + 240 PM per DSP more than test2c) can go to a second NAM block on the same DSP;
the cost is that the heaviest effects (DM over 0x1d7 or PM over 0xf3) can't bind in that slot.

PC only, never share.
usage: build_test2e.py <stock Floor .hxf>
"""
import hashlib
import os
import struct
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
from stage_slots import graph_members, GRAPHS, SLOT_TYPE, NORMAL  # noqa: E402
from build_test2b import shrink_last_big  # noqa: E402
from build_test2c import graph_sums, shrink_heaps_to  # noqa: E402
from build_staged import check_and_pack  # noqa: E402

HALF = (NORMAL[0] // 2, NORMAL[1] // 2)


def halve_last_normal(e5):
    w = list(struct.unpack('<%dI' % (len(e5) // 4), e5))
    ln, off = w[w[3]], w[w[3] + 1]
    b0 = w[off:off + ln]
    rep = []
    for g in GRAPHS:
        base, n = graph_members(b0, g)
        slots = [k for k in range(n) if b0[base + 20 * k + 4] == 0 and b0[base + 20 * k + 6] == SLOT_TYPE]
        r = base + 20 * slots[12]
        assert (b0[r + 13], b0[r + 14]) == NORMAL
        b0[r + 13], b0[r + 14] = HALF
        rep.append(f"{g:#x}: member {slots[12]} DM/PM {NORMAL[0]:#x}/{NORMAL[1]:#x} -> {HALF[0]:#x}/{HALF[1]:#x}")
    w[off:off + ln] = b0
    return struct.pack('<%dI' % len(w), *w), rep


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    new5, rep = shrink_last_big(pa.get_entry_swapped(data, 5))
    new5, rep2 = halve_last_normal(new5)
    after = graph_sums(new5)
    dm_size, pm_size = max(s[0] for s in after), max(s[1] for s in after)
    ents = l6ia.parse(data)
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    new2, rep3 = shrink_heaps_to(e2, dm_size, pm_size)
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new2), 5: new5})
    nents = l6ia.parse(img)
    for i in range(len(ents)):
        if i in (2, 5):
            continue
        a = img[nents[i]['payload_off']: nents[i]['payload_off'] + nents[i]['payload_len']]
        b = data[ents[i]['payload_off']: ents[i]['payload_off'] + ents[i]['payload_len']]
        assert a == b, f"Entry {i} differs from stock"
    for line in rep + rep2 + rep3:
        print(line)
    print(f"heaps: a -> {dm_size:#x}, b -> {pm_size:#x} (sums {after})")
    check_and_pack(img, "test2e_normal_half.hxf", raw)


if __name__ == "__main__":
    main()
