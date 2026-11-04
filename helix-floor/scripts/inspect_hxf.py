"""Read-only inspector for a Line 6 .hxf: lists container chunks and the inner archive's entries."""
import struct, zlib, hashlib, sys, os

path, outdir = sys.argv[1], sys.argv[2]
raw = open(path, 'rb').read()
print(f"file {len(raw)} bytes, magic {raw[:4]} {raw[8:12]}")
pos, data = 12, None
while pos < len(raw):
    cid = raw[pos:pos+4]; sz = struct.unpack('>I', raw[pos+4:pos+8])[0]
    body = raw[pos+8:pos+8+sz]
    line = f"  {cid} @{pos:#x} size={sz:#x}"
    if cid == b'HEAD':
        words = struct.unpack('>13I', body[:52]) if sz >= 52 else ()
        line += f" words={[hex(w) for w in words]}"
    elif cid == b'dinf':
        line += f" {[hex(x) for x in struct.unpack('>IIII', body[:16])]}"
    elif cid == b'data':
        data = zlib.decompress(body)
        line += f" -> {len(data):#x} bytes md5={hashlib.md5(data).hexdigest()}"
    print(line)
    pos += 8 + sz + (sz & 1)

os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, 'payload.bin'), 'wb').write(data)
print("payload magic", data[:4])
if data[:4] != b'L6IA':
    sys.exit("not L6IA")
hdr = struct.unpack('>6I', data[:0x18])
print("root", [hex(x) for x in hdr])
off = 0x18
for i in range(hdr[5]):
    idx, marker, typ, four, words, h1, h2, z1, z2 = struct.unpack('>9I', data[off:off+0x24])
    sub = data[off+0x24:off+0x224]
    smagic, sver, scrc, plen = struct.unpack('>4I', sub[:16])
    payload = data[off+0x224:off+0x224+plen]
    # payloads are stored big-endian word-swapped; swap back to native little-endian
    n = len(payload) & ~3
    sw = bytearray(payload)
    for j in range(0, n, 4):
        sw[j:j+4] = payload[j:j+4][::-1]
    sw = bytes(sw)
    head = sw[:16]
    print(f"entry {idx:2} type={typ} marker={marker:#x} words={words:#x} plen={plen:#x} "
          f"submagic={smagic:#x} crcok={zlib.crc32(sw) & 0xffffffff == scrc} head={head.hex()} {head[:16]!r}")
    open(os.path.join(outdir, f"entry{idx:02}.bin"), 'wb').write(sw)
    off += 0x24 + words * 4
print(f"end of entries at {off:#x}, payload length {len(data):#x}, trailer {len(data)-off:#x} bytes")
