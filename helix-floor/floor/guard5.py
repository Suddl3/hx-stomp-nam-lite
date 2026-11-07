#!/usr/bin/env python3
"""nam_floor5's instance-memory safety in the simulator (rig bounds):

1. an instance inside the bounds plays and initialises its slot;
2. one whose DM block (I0) is outside plays silence, slot uninitialised;
3. one whose PM block (I8) is outside, the same;
4. edges: the last in-range I0 plays; one word past it is refused;
5. I8 moves while I0 stays (PM_RECHECK): the slot restarts; moved outside -> silence,
   moved back inside -> plays again with its ring pointers re-made from the new I8.

usage: guard5.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor5 as n5  # noqa: E402
from nam_floor5 import nm, nam_lite  # noqa: E402
import ssim  # noqa: E402

(DLO, DHI), (PLO, PHI) = n5.RIG_BOUNDS
SIG = [[ssim.f2b(0.2 * ((i * 7 + k) % 11 - 5) / 5) for i in range(16)] for k in range(6)]


def run(asm, lay, i0, i8, moves=()):
    """Calls with SIG; moves = {call index: new I8}. Returns per call (played?, S_INIT)."""
    r = n5.Rig(asm, lay)
    nm.set_ir(r.sim, 1, nam_lite.ir_samples(nam_lite.placeholder(), None))
    inst = nm.Inst(r, "g", i0, i8, 0xB6000, 0x400000, lay.sdram_words())
    inst.knobs(model=1)
    moves = dict(moves)
    out = []
    for k, b in enumerate(SIG * 2):
        if k in moves:
            inst.i8 = moves[k]
            for j in range(13):
                r.sim.wr(inst.i8 + j, 0)
        got = inst.call(b, f"call {k}") if hasattr(inst, "call") else None
        out.append((any(got), r.sim.rd(lay.slot[0] + nm.S["S_INIT"])))
    return out


def main():
    asm, lay = n5.build(inst_bounds=n5.RIG_BOUNDS)
    nm.REP = lay.rep
    dmax = DHI - lay.inst_dm_need
    res = {}
    res["inside"] = run(asm, lay, DLO + 1, PLO + 1)
    res["dm outside"] = run(asm, lay, 0xA0001, PLO + 1)
    res["pm outside"] = run(asm, lay, DLO + 1, PHI + 0x100)
    res["dm last ok"] = run(asm, lay, dmax - (dmax & 1) - 1, PLO + 1)   # (odd, as the rig's)
    res["dm one past"] = run(asm, lay, dmax + 1, PLO + 1)
    res["i8 moves out, back"] = run(asm, lay, DLO + 1, PLO + 1, {4: PHI + 0x100, 8: PLO + 0x401})
    for k, v in res.items():
        print(f"{k:20s}", " ".join(f"{'P' if p else '-'}{s}" for p, s in v))
    assert all(s == 1 for _, s in res["inside"][1:]) and any(p for p, _ in res["inside"])
    for k in ("dm outside", "pm outside", "dm one past"):
        assert res[k] and not any(p for p, _ in res[k]) and all(s == 0 for _, s in res[k]), k
    assert all(s == 1 for _, s in res["dm last ok"][1:])
    mv = res["i8 moves out, back"]
    assert all(s == 1 for _, s in mv[1:4]), "did not start"
    assert all(not p and s == 0 for p, s in mv[4:8]), "kept playing with the old ring pointers"
    assert all(s == 1 for _, s in mv[9:]) and any(p for p, _ in mv[9:]), "did not restart"
    print("guard5: PASS")


if __name__ == "__main__":
    main()
