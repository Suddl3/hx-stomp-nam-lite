import struct, sys
d = open(sys.argv[1], 'rb').read()
w = struct.unpack('<%dI' % (len(d)//4), d[:len(d)//4*4])
print("words", len(w), "first nonzero at", next(i for i, x in enumerate(w) if x))
for pat in [(0x0f000007, 0x7aac1901), (0x00293eac,), (0x002ab243,)]:
    hits = [i for i in range(len(w)-len(pat)+1) if w[i:i+len(pat)] == pat]
    print([hex(p) for p in pat], "hits", hits[:10])
for i in (37192, 41966, 41971, 41975):
    if i < len(w): print(i, hex(w[i]))
