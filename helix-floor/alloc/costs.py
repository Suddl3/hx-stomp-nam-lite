"""DSP cost (main program model table) of big-slot vs normal models; how many big ones fit 9000.
Usage: costs.py <entry00.bin> <model DB .bin> <graph-lib .bin> <table va> <rows>"""
import struct, sys, collections
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import TOOLS; sys.path.insert(0, TOOLS)
from patch_amp import parse_entry3_full
e0 = open(sys.argv[1], 'rb').read()
segs, off = [], 0x34
for _ in range(struct.unpack_from('<I', e0, 16)[0]):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off); segs.append((off + 12, slen, dst)); off = nxt
va, rows = int(sys.argv[4], 0), int(sys.argv[5], 0)
fo = next(p + va - d for p, l, d in segs if d <= va < d + l)
cost = {}
for i in range(rows):
    ni, pid, z, c = struct.unpack_from('<IHHI', e0, fo + 12 * i); cost[ni] = c
info = parse_entry3_full(open(sys.argv[2], 'rb').read())
d = open(sys.argv[3], 'rb').read(); w = struct.unpack('<%dI' % (len(d) // 4), d)
n, do = w[2], w[3]; dirs = [(w[do + 2 * k], w[do + 2 * k + 1]) for k in range(n)]
b0 = w[dirs[0][1]:dirs[0][1] + dirs[0][0]]; ct, nc = b0[0x10], b0[0xf]
def need(i):
    ln, of = dirs[i]; b = w[of:of + ln]
    if ln < 4 or b[0] != 3: return None
    t = b[b[2] + 1]
    if not (0x600000 <= t < 0x600000 + nc): return None
    h = b0[ct + 7 * (t - 0x600000): ct + 7 * (t - 0x600000) + 7]; s = [0, 0]
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        if r[4] == 0: s[0] += r[13]; s[1] += r[14]
    return s
big = []
for m in info['models']:
    s = need(m['blob_index']) if 0 < m['blob_index'] < n else None
    c = cost.get(m['words'][2])
    if s and c is not None and (s[0] > 0x3ae or s[1] > 0x1e6):
        big.append((c, m['meta'].get('category'), m['displayName'] or m['name']))
big.sort()
print('big models', len(big), 'cost min/max', big[0][:2], big[-1][:2])
print('cheapest 8:', big[:8])
print('max big models within 9000 at cheapest costs:', sum(1 for k in range(1, 10) if sum(c for c, *_ in big[:k]) <= 9000))
