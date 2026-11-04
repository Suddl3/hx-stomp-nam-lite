"""Each model blob's top type and what its tree asks for (sum of member budgets).
Usage: needs.py <graph-lib .bin>"""
import struct, sys, collections
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
n, do = w[2], w[3]
dirs = [(w[do + 2 * k], w[do + 2 * k + 1]) for k in range(n)]
b0 = w[dirs[0][1]:dirs[0][1] + dirs[0][0]]
ct, nc = b0[0x10], b0[0xf]
def hdr(c): return b0[ct + 7 * (c - 0x600000): ct + 7 * (c - 0x600000) + 7]
def csum(c):
    h = hdr(c); s = [0, 0, 0]
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        if r[4] == 0:
            s[0] += r[13]; s[1] += r[14]; s[2] += r[15]
    return s
tops = collections.Counter(); rows = []
for i in range(1, n):
    ln, of = dirs[i]
    b = w[of:of + ln]
    if ln < 4 or b[0] != 3:
        tops['bad'] += 1; continue
    tl, cnt = b[2], b[3]
    nodes = [b[tl + 4 * k: tl + 4 * k + 4] for k in range(cnt)]
    t = nodes[0][1]
    if 0x600000 <= t < 0x600000 + nc:
        tops['comp'] += 1; rows.append((i, t, csum(t), len(nodes)))
    else:
        tops['prim'] += 1; rows.append((i, t, None, len(nodes)))
print(tops)
print('node[0] samples:', [(r[0], hex(r[1]), r[3]) for r in rows[:8]])
comp = [r for r in rows if r[2]]
comp.sort(key=lambda r: -r[2][0])
print('top DM needs:')
for r in comp[:20]:
    print(f'  blob {r[0]} comp {r[1]:#x} dm {r[2][0]:#x} pm {r[2][1]:#x} sdram {r[2][2]:#x} nodes {r[3]}')
print('DM need histogram (models 3..842):')
vals = sorted(r[2][0] for r in comp if 3 <= r[0] <= 842)
for lo, hi in [(0, 0x100), (0x100, 0x200), (0x200, 0x300), (0x300, 0x38c), (0x38c, 0x3a3), (0x3a3, 0x3af), (0x3af, 0x597), (0x597, 0x800)]:
    print(f'  {lo:#x}..{hi - 1:#x}: {sum(lo <= v < hi for v in vals)}')
print('largest under 0x3af:', [hex(v) for v in vals if v < 0x3af][-12:])
print('PM largest under 0x1e7:', sorted(hex(r[2][1]) for r in comp if 3 <= r[0] <= 842 and r[2][0] < 0x3af)[-5:])
fx = sorted(r[2][1] for r in comp if 3 <= r[0] <= 842 and r[2][0] < 0x3af)
amp = sorted(r[2][1] for r in comp if 3 <= r[0] <= 842 and r[2][0] >= 0x3af)
print('FX PM top:', [hex(v) for v in fx[-8:]], ' amp-size PM top:', [hex(v) for v in amp[-8:]])
