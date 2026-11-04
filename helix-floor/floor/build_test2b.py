#!/usr/bin/env python3
"""test2b_bigslot_normal.hxf: stock, except in Entry 5 the last big slot of each path graph
(0x600000 member 181, 0x600001 member 18) gets the normal slot's sizes (record words 13..19
copied from the last normal slot: DM 0x3ae, PM 0x1e6, SDRAM 0x63000, and word 17 0x71 instead
of 0xd4). The record is then identical in its sizes to the 13 stock normal slots. Heaps (Entry 2)
stock, so they stay bigger than the reduced sums.

test2 / test2a (slots with budget 0) failed at boot. This asks: does the Floor accept ANY change
to the slot list, as long as every slot keeps a legal size?
Boots -> yes (zero size was the problem). Fails -> the slot list itself is checked.

PC only, never share.
usage: build_test2b.py <stock Floor .hxf>
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
from stage_slots import graph_members, GRAPHS, SLOT_TYPE, NORMAL, BIG  # noqa: E402
from build_staged import check_and_pack  # noqa: E402


def shrink_last_big(e5):
    w = list(struct.unpack('<%dI' % (len(e5) // 4), e5))
    ln, off = w[w[3]], w[w[3] + 1]
    b0 = w[off:off + ln]
    rep = []
    for g in GRAPHS:
        base, n = graph_members(b0, g)
        slots = [k for k in range(n) if b0[base + 20 * k + 4] == 0 and b0[base + 20 * k + 6] == SLOT_TYPE]
        sizes = [(b0[base + 20 * k + 13], b0[base + 20 * k + 14]) for k in slots]
        assert sizes == [NORMAL] * 13 + [BIG] * 3, f"{g:#x}: not the stock 13 + 3 pool"
        src, dst = base + 20 * slots[12], base + 20 * slots[15]
        old = b0[dst + 13:dst + 20]
        b0[dst + 13:dst + 20] = b0[src + 13:src + 20]
        rep.append(f"{g:#x}: member {slots[15]} sizes {' '.join(f'{x:x}' for x in old)} -> "
                   f"{' '.join(f'{x:x}' for x in b0[dst + 13:dst + 20])}")
    w[off:off + ln] = b0
    return struct.pack('<%dI' % len(w), *w), rep


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    new5, rep = shrink_last_big(pa.get_entry_swapped(data, 5))
    img, _, _ = l6ia.rebuild_archive(data, {5: new5})
    ents, sents = l6ia.parse(img), l6ia.parse(data)
    for i in range(len(sents)):
        if i == 5:
            continue
        a = img[ents[i]['payload_off']: ents[i]['payload_off'] + ents[i]['payload_len']]
        b = data[sents[i]['payload_off']: sents[i]['payload_off'] + sents[i]['payload_len']]
        assert a == b, f"Entry {i} differs from stock"
    for line in rep:
        print(line)
    print("test 2b: Entry 5 only (last big slot per graph -> normal sizes), all other entries stock")
    check_and_pack(img, "test2b_bigslot_normal.hxf", raw)


if __name__ == "__main__":
    main()
