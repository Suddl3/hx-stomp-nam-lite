"""Print the SHARC heap-init immediate loads (ureg = imm32) around the Heap 6 setup.
Usage: heaps.py <entry02.bin> <heap6_start>"""
import struct, sys

d = open(sys.argv[1], 'rb').read()
W = struct.unpack('>%dI' % (len(d) // 4), d)
H = []
for w in W:
    H += [w >> 16, w & 0xffff]
h6 = int(sys.argv[2], 0)
k6 = next(k for k in range(len(H) - 2) if (H[k] >> 8) == 0x0f and ((H[k + 1] << 16) | H[k + 2]) == h6)
for k in range(k6 - 340, k6 + 140):
    if (H[k] >> 8) == 0x0f:
        print(f"w{k // 2}{'.5' if k % 2 else ''}  reg{H[k] & 0xff:#04x} = {(H[k + 1] << 16) | H[k + 2]:#x}")
