import struct, sys, collections
d = open(sys.argv[1], 'rb').read()
w = struct.unpack(('>' if len(sys.argv) > 2 else '<') + '%dI' % (len(d)//4), d[:len(d)//4*4])
nw = {5: lambda c: ((c+1)&~1)*3//2, 4: lambda c: c, 3: lambda c: (c+1)//2, 6: lambda c: c*2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
i, blocks, tags = 384, 0, collections.Counter()
while i + 3 <= len(w):
    tag, cnt, addr = w[i:i+3]
    if tag not in range(13):
        print(f"desync at word {i}: {tag:#x} {cnt:#x} {addr:#x}"); break
    tags[tag] += 1; blocks += 1
    if tag == 0:
        print(f"FINAL_INIT at word {i}, end word {i+3+384} of {len(w)}"); break
    i += 3 + nw.get(tag, lambda c: 0)(cnt)
print("blocks", blocks, dict(tags))
