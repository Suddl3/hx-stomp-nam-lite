"""Which model-DB meta keys/values separate big-slot models from normal ones.
Usage: bigtag.py <model DB .bin> <graph-lib .bin>"""
import struct, sys, collections
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'floor'))
from upstream import TOOLS; sys.path.insert(0, TOOLS)
from patch_amp import parse_entry3_full
info = parse_entry3_full(open(sys.argv[1], 'rb').read())
d = open(sys.argv[2], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
n, do = w[2], w[3]
dirs = [(w[do + 2 * k], w[do + 2 * k + 1]) for k in range(n)]
b0 = w[dirs[0][1]:dirs[0][1] + dirs[0][0]]
ct, nc = b0[0x10], b0[0xf]
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
vals = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
nb = [0, 0]
for m in info['models']:
    s = need(m['blob_index']) if 0 < m['blob_index'] < n else None
    if not s: continue
    big = int(s[0] > 0x3ae or s[1] > 0x1e6); nb[big] += 1
    for k, v in m['meta'].items():
        vals[k][big][str(v)[:30]] += 1
print('normal/big models', nb)
for k, (a, b) in sorted(vals.items()):
    if len(a) + len(b) < 40:
        print(f'{k}: normal {dict(a)} | big {dict(b)}')
    else:
        print(f'{k}: many values (normal {sum(a.values())}, big {sum(b.values())})')
