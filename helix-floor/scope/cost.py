"""Simulated per-block instruction counts of the NAM kernel for far-ring cut-offs (Stomp addresses)."""
import sys, time
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import SHARC; sys.path.insert(0, SHARC)
import nam_multi as nm, nam_lite
w = nam_lite.placeholder()
for far_d in (int(x) for x in sys.argv[1:]):
    nm.FAR_D[2] = far_d
    t = time.time()
    asm, lay = nm.build(2)
    ok, res, k = nm.check(asm, lay, w)
    print(f"slots 2, far_d {far_d}: ok={ok} {res} ({time.time() - t:.0f}s)", flush=True)
