"""Dump the amp harnesses' members (dm/pm/sdram) and the biggest stock per-member DM.
Usage: harness.py <graph-lib entry .bin> <harness ids comma-separated>"""
import struct, sys
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
ln, off = w[w[3]], w[w[3] + 1]
b0 = w[off:off + ln]
nc, ct = b0[0xf], b0[0x10]
def hdr(c): return b0[ct + 7 * (c - 0x600000): ct + 7 * (c - 0x600000) + 7]
def show(c, ind=''):
    h = hdr(c)
    print(f'{ind}{c:#x}: n_in {h[0]} n_out {h[1]} members {h[2]} bufs {h[4]} flags {h[6]:#x}')
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        print(f'{ind}  m{k} flags {r[4]} type {r[6]:#x} dm {r[13]:#x} pm {r[14]:#x} sdram {r[15]:#x} r16..19 {[hex(x) for x in r[16:20]]}')
print('composites', nc)
for c in sys.argv[2].split(','):
    show(int(c, 0))
big = []
for c in range(0x600000, 0x600000 + nc):
    h = hdr(c)
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        if r[4] == 0:
            big.append((r[13], r[14], r[15], c, k, r[6]))
big.sort(reverse=True)
print('top member DM:')
for x in big[:15]:
    print(f'  dm {x[0]:#x} pm {x[1]:#x} sdram {x[2]:#x}  in {x[3]:#x} m{x[4]} type {x[5]:#x}')
