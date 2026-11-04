"""Every on-chip piece of the NAM kernel at far_d 17 (2 slots), with sizes, for the Floor memory plan."""
import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import SHARC; sys.path.insert(0, SHARC)
import nam_multi as nm
nm.FAR_D[1] = 17
lay = nm.Layout(slots=1, staging="b3")
hot, cold = nm.code_sizes()
hot_nw = -(-(hot + (hot & 1)) * 3 // 2); cold_nw = -(-(cold + (cold & 1)) * 3 // 2)
print(f"code: hot {hot_nw}, cold {cold_nw}")
al = sorted(lay.alloc.items(), key=lambda x: x[1])
ends = [x[1] for x in al[1:]] + [lay.slot[0]]
g = {k: e - a for (k, a), e in zip(al, ends) if nm.B3 <= a < nm.B3_END}
print("globals", sum(g.values()) + 16 + (nm.REP - nm.B3), g)
print("slot", lay.slot_size, "stream", nm.S_STREAM + nm.N_STREAM, "heads", lay.hb[-1] + nm.HEADL + 2 - lay.hb[0])
near = sorted(lay.near_off.items(), key=lambda x: x[1])
for (i, o) in near:
    print(f"  near layer {i:2d} k={nm.KERNEL[i]:2d} d={nm.DILATION[i]:3d}: {nm.C * (lay.nring[i] + 2)} words")
print("far layers", lay.far)
