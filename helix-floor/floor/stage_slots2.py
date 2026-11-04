#!/usr/bin/env python3
"""Build stage 1 for the 2-NAM-per-DSP build: test2c's layout (hardware-proven 2026-11-01).

Entry 5: the last big slot of each path graph gets the normal slot's sizes (record words 13..19);
Entry 2: heaps a and b shrink to the new budget sums (the larger graph's). Frees per DSP
DM 0x9b6b1..0x9ba5f and PM 0xe6624..0xe674a (floor/nam_floor4.py's R3 and R2).

usage: stage_slots2.py <in.l6ia> <out.l6ia>
"""
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
from build_test2b import shrink_last_big  # noqa: E402
from build_test2c import graph_sums, shrink_heaps_to  # noqa: E402
import nam_floor2  # noqa: E402


def main():
    src, out = sys.argv[1], sys.argv[2]
    data, _ = pa.load_l6ia_from_any(src)
    ents = l6ia.parse(data)
    new5, rep = shrink_last_big(pa.get_entry_swapped(data, 5))
    after = graph_sums(new5)
    dm, pm = max(s[0] for s in after), max(s[1] for s in after)
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    new2, rep2 = shrink_heaps_to(e2, dm, pm)
    assert (nam_floor2.HEAP_A2[1], nam_floor2.HEAP_B2[1]) == (0x9ba5f - (0x4ebb - dm), 0xe674a - (0x22e4 - pm)), \
        "the kernel's regions disagree with the shrunk heaps"
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new2), 5: new5})
    open(out, "wb").write(img)
    for line in rep + rep2:
        print(line)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
