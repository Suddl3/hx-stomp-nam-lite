"""Summarize the path graphs: block-slot members and their dm/pm/sdram budgets.
Usage: paths.py <graph-lib .bin> <comp ids>"""
import struct, sys, collections
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
ln, off = w[w[3]], w[w[3] + 1]
b0 = w[off:off + ln]
ct = b0[0x10]
def hdr(c): return b0[ct + 7 * (c - 0x600000): ct + 7 * (c - 0x600000) + 7]
for c in sys.argv[2].split(','):
    c = int(c, 0); h = hdr(c)
    tot = [0, 0, 0]; kinds = collections.Counter()
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        if r[4] == 0:
            tot[0] += r[13]; tot[1] += r[14]; tot[2] += r[15]
            kinds[(r[6], r[13], r[14], r[15])] += 1
    print(f'{c:#x}: members {h[2]}  sum dm {tot[0]:#x} ({tot[0]}) pm {tot[1]:#x} sdram {tot[2]:#x}')
    for (t, dm, pm, sd), n in sorted(kinds.items(), key=lambda x: -x[0][1] * x[1])[:12]:
        print(f'   {n:3d} x type {t:#x} dm {dm:#x} pm {pm:#x} sdram {sd:#x}')
