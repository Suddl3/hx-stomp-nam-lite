"""List the LDR boot spans (tag, size) inside one address range, for comparing Floor and Stomp.
Usage: spans.py <entry02.bin> <lo> <hi>"""
import sys, os
sys.argv, args = sys.argv[:2], sys.argv[2:]
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "occupancy.py")).read().split("def merged")[0]
exec(src)
lo, hi = int(args[0], 0), int(args[1], 0)
for a, b, t, i in sorted(spans):
    if a < hi and b > lo:
        print(f"{a:#x}..{b:#x} {b - a:6d} {NAMES.get(t, t):10s} (stream word {i})")
