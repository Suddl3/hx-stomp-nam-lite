#!/usr/bin/env python3
"""test2a_slots_e5_only.hxf: stock, except Entry 5 (graph library) gets stage_slots' zero-budget
slots; Entry 2's heaps stay stock. test2 (both changes) failed at boot ("Boot Failure - Entered
Update Mode!"); this splits the cause. Stock heaps are larger than the reduced budget sums, so
the only new thing the DSP sees is 3 slots per path graph with DM/PM/SDRAM budget 0.
Boots -> the heap shrink (Entry 2) was the fault. Fails -> zero-budget slots are rejected.

PC only, never share.
usage: build_test2a.py <stock Floor .hxf>
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
from stage_slots import zero_slots, HEAP_A, HEAP_B  # noqa: E402
from build_staged import check_and_pack  # noqa: E402


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    new5, freed, rep, after = zero_slots(pa.get_entry_swapped(data, 5))
    assert all(s[0] <= HEAP_A[2] and s[1] <= HEAP_B[2] for s in after), "budgets over stock heaps"
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
    print(f"test 2a: Entry 5 only (freed DM {freed[0]:#x} / PM {freed[1]:#x} per graph left unused), all other entries stock")
    check_and_pack(img, "test2a_slots_e5_only.hxf", raw)


if __name__ == "__main__":
    main()
