"""Pair Floor and Stomp LDR spans in boot-stream order and show the ones whose size or block differs.
Usage: diff_spans.py <floor entry02> <stomp entry02>"""
import sys, os, difflib
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "occupancy.py")).read().split("i, spans = 384")[0]

def load(path):
    g = {"__name__": "x"}
    sys.argv = ["x", path]
    exec(src + "\ni, spans = 384" + open(os.path.join(here, "occupancy.py")).read().split("i, spans = 384")[1].split("def merged")[0], g)
    return [(i, lo, hi, t) for lo, hi, t, i in g["spans"]]

def blk(a):
    for n, lo in (("B0", 0x80000), ("B1", 0xa0000), ("B2", 0xc0000), ("B3", 0xe0000)):
        if lo <= a < lo + 0x8000: return n
    return "B0/1hi" if a < 0xc0000 else ("on" if a < 0x200000 else "ext")

A1, A2 = sys.argv[1], sys.argv[2]
F, S = sorted(load(A1)), sorted(load(A2))
key = lambda s: (s[3], blk(s[1]) if blk(s[1]) not in ("B2", "B3") else "B23")
sm = difflib.SequenceMatcher(None, [key(x) for x in F], [key(x) for x in S], autojunk=False)
tot = {}
for op, a0, a1, b0, b1 in sm.get_opcodes():
    for k in range(max(a1 - a0, b1 - b0)):
        f = F[a0 + k] if a0 + k < a1 else None
        s = S[b0 + k] if b0 + k < b1 else None
        fs = f[2] - f[1] if f else 0
        ss = s[2] - s[1] if s else 0
        fb = blk(f[1]) if f else "-"
        if fb in ("B2", "B3") or (s and blk(s[1]) in ("B2", "B3")):
            tot[fb] = tot.get(fb, 0) + fs
            if fs != ss or (f and s and blk(f[1]) != blk(s[1])) or not (f and s):
                print(f"{op:7s} floor {f[1] if f else 0:#8x} {fs:6d} {fb:3s} | stomp {s[1] if s else 0:#8x} {ss:6d} {blk(s[1]) if s else '-':3s}  diff {fs - ss:+6d}")
