"""Item-by-item on-chip sizes of the NAM kernel layout (1 slot) for a far-ring cut-off."""
import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import SHARC; sys.path.insert(0, SHARC)
import nam_multi as nm
for far_d in (int(x) for x in sys.argv[1:]):
    nm.FAR_D[1] = far_d
    lay = nm.Layout(slots=1, staging="b3")
    al = sorted(lay.alloc.items(), key=lambda x: x[1])
    ends = [x[1] for x in al[1:]] + [lay.slot[0]]
    print(f'far_d {far_d}: far layers {len(lay.far)}, near rings', {i: lay.nring[i] for i in range(nm.NL) if i not in lay.far})
    print('  globals', nm.REP + 16 - nm.B3, ' ' + ', '.join(f'{k} {e - a}' for (k, a), e in zip(al, ends) if nm.B3 <= a < nm.B3_END))
    print(f'  slot {lay.slot_size} (stream {nm.S_STREAM}+{nm.N_STREAM}, heads {3 * (nm.HEADL + 2)}, near rings rest)')
    print(f'  B2 staging/X/WBUF: {lay.b2_to - lay.b2_from if hasattr(lay, "b2_from") else "?"}  sdram/inst {lay.sdr_need}')
