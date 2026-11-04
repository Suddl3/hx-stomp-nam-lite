"""List the path graph's block-slot members (type 0x600006) in order with ports and budgets."""
import struct, sys
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d) // 4), d)
ln, off = w[w[3]], w[w[3] + 1]
b0 = w[off:off + ln]
ct = b0[0x10]
c = int(sys.argv[2], 0)
h = b0[ct + 7 * (c - 0x600000): ct + 7 * (c - 0x600000) + 7]
acc = 0
for k in range(h[2]):
    r = b0[h[3] + 20 * k: h[3] + 20 * k + 20]
    if r[4] == 0:
        if r[6] == 0x600006:
            ins = [b0[r[8] + j] for j in range(r[7])]; outs = [b0[r[10] + j] for j in range(r[9])]
            print(f'm{k:3d} dm@{acc:#06x} dm {r[13]:#x} pm {r[14]:#x} parent {r[5]} in {ins} out {outs} r16..19 {[hex(x) for x in r[16:20]]}')
        acc += r[13]
