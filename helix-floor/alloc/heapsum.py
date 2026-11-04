"""Compare each path graph's summed member budgets with the heap sizes, and sum buffers (r16)."""
import struct, sys
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
ln, off = w[w[3]], w[w[3] + 1]
b0 = w[off:off + ln]
ct = b0[0x10]
def hdr(c): return b0[ct + 7 * (c - 0x600000): ct + 7 * (c - 0x600000) + 7]
for c in sys.argv[2].split(','):
    c = int(c, 0); h = hdr(c); s = [0] * 20
    for k in range(h[2]):
        r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
        if r[4] == 0:
            for j in range(13, 20): s[j] += r[j]
    print(f'{c:#x} hdr {[hex(x) for x in h]}  sums r13..19 {[hex(x) for x in s[13:20]]}')
