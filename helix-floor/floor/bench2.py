"""Quick speed bench for nam_floor / nam_floor2 layouts: one instance, model loaded, steady calls.
Usage: bench2.py [floor|floor2] [calls]"""
import sys, os
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
which = sys.argv[1] if len(sys.argv) > 1 else "floor2"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 24
mod = __import__("nam_floor2" if which == "floor2" else "nam_floor")
nm, nam_lite = mod.nm, mod.nam_lite


def bench(asm, lay, n=n, two=True):
    nm.REP = lay.rep
    r = mod.Rig(asm, lay)
    w = nam_lite.placeholder()
    nm.set_ir(r.sim, 1, nam_lite.ir_samples(w, None))
    insts = [r.inst("A", 0)] + ([r.inst("B", 1)] if two else [])
    for i in insts:
        i.knobs(model=1)
    sig = [[mod.nf.ssim_f2b(0.2 * ((k * 7) % 11 - 5) / 5) for k in range(16)] if hasattr(mod, "nf") else
           [mod.ssim_f2b(0.2 * ((k * 7) % 11 - 5) / 5) for k in range(16)]][0]
    for b in range(n):
        for i in insts:
            i.call(sig, f"{i.name} {b}")
    st = [c for _, c in r.cycles[-2 * 8:]]
    busy = r.dma.cycles_busy if hasattr(r, "dma") else None
    return sum(st) / len(st), max(st), r.rep()[nm.REPW["R_MAXPOLLS"]], busy


if __name__ == "__main__":
    asm, lay = mod.build(inst_bounds=mod.RIG_BOUNDS)
    print(which, "steady mean %.0f worst %d maxpolls %d dma_busy_total %s" % bench(asm, lay))
