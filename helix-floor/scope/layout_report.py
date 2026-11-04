"""Print the NAM kernel's memory needs (upstream nam_multi.Layout) for slot counts, far-ring cut-offs, staging."""
import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import SHARC; sys.path.insert(0, SHARC)
import nam_multi as nm

hot, cold = nm.code_sizes()
hot_nw = -(-(hot + (hot & 1)) * 3 // 2)
print(f"hot code {hot} instr = {hot_nw} nw; cold {cold} instr; weights {nm.nam_lite.N_WEIGHTS}; "
      f"dilations {sorted(set(nm.DILATION))}; stock FAR_D {nm.FAR_D}")
FLOOR_B3_FREE = 0xd67
for slots in (1, 2):
    for far_d in (41, 17, 9, 5, 3, 2, 1):
        nm.FAR_D[slots] = far_d
        for staging in ("b3",):
            try:
                lay = nm.Layout(slots=slots, staging=staging)
            except SystemExit as e:
                print(f"slots={slots} far_d={far_d}: {e}"); continue
            b3 = lay.b3_to - nm.B3
            cold_nw = nm.B3_END - lay.cold_nw
            print(f"slots={slots} far_d>={far_d:2}: B3 data {b3:5} (slot {lay.slot_size:5}) + cold {cold_nw} "
                  f"| + hot code {hot_nw} => on-chip total {b3 + cold_nw + hot_nw:5} vs Floor B3 free {FLOOR_B3_FREE} "
                  f"| far layers {len(lay.far):2}, sdram/inst {lay.sdr_need}")
