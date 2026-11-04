#!/usr/bin/env python3
"""test2d_heaps_only.hxf: stock slot budgets (Entry 5 untouched), but Entry 2's heaps a and b shrunk
by one big slot's worth (DM 0x75c, PM 0x30c), so the heaps are SMALLER than the summed slot budgets.

test2b showed a Cab Dual (PM 0x21e) playing with no slot big enough for it, which suggests slot
budgets only size the heaps and the DSP hands out heap memory by what each block really needs.
This asks: is the heap a shared pool (boots; normal presets play; only a worst-case preset may
lose a block), or does the DSP require heap >= summed budgets (boot failure)?
If it's a pool, NAM's memory can come from the heaps without giving up any block spaces.

PC only, never share.
usage: build_test2d.py <stock Floor .hxf>
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
from stage_slots import HEAP_A, HEAP_B, BIG  # noqa: E402
from build_test2c import shrink_heaps_to  # noqa: E402
from build_staged import check_and_pack  # noqa: E402


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    ents = l6ia.parse(data)
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    new2, rep = shrink_heaps_to(e2, HEAP_A[2] - BIG[0], HEAP_B[2] - BIG[1])
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new2)})
    nents = l6ia.parse(img)
    for i in range(len(ents)):
        if i == 2:
            continue
        a = img[nents[i]['payload_off']: nents[i]['payload_off'] + nents[i]['payload_len']]
        b = data[ents[i]['payload_off']: ents[i]['payload_off'] + ents[i]['payload_len']]
        assert a == b, f"Entry {i} differs from stock"
    for line in rep:
        print(line)
    print("test 2d: Entry 2 heaps only, below the stock slot budget sums; all other entries stock")
    check_and_pack(img, "test2d_heaps_only.hxf", raw)


if __name__ == "__main__":
    main()
