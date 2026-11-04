#!/usr/bin/env python3
"""Pack an L6IA image into a Helix Floor .hxf, using the stock Floor .hxf as the donor.

Upstream's tools/hxf.py pack updates the dinf records only for the Stomp's two-dinf
layout. The Floor's .hxf has one dinf (kind 0, offset 0, length = the whole L6IA) and no
trailer, so its length must follow the payload. Everything else (HEAD's product words,
zlib level 9, FORM sizes) is as upstream.

usage: floor_hxf.py pack <in.l6ia> <out.hxf> --donor <stock Floor .hxf>
       floor_hxf.py selftest <stock Floor .hxf> <scratch dir>
"""
import hashlib
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import hxf  # noqa: E402

FLOOR_MD5 = "805caa03e8a30fd6ff7892f32ed5a9f4"


def pack(payload, donor_raw):
    chunks = hxf._chunks(donor_raw)
    head = bytearray([b for c, p, s, b in chunks if c == b'HEAD'][0])
    dinfs = [bytearray(b) for c, p, s, b in chunks if c == b'dinf']
    assert len(dinfs) == 1 and struct.unpack('>IIII', dinfs[0][:16])[0::2] == (0, 0), \
        "not the Floor's one-dinf layout (kind 0, offset 0)"
    assert payload[:4] == b'L6IA', "payload is not an L6IA image"
    struct.pack_into('>I', head, 16, len(payload))
    head[20:36] = hashlib.md5(payload).digest()
    struct.pack_into('>I', dinfs[0], 12, len(payload))
    body = bytearray(b'L6FF')
    for cid, data in [(b'HEAD', bytes(head)), (b'dinf', bytes(dinfs[0])), (b'data', zlib.compress(payload, 9))]:
        body += cid + struct.pack('>I', len(data)) + data
        if len(data) & 1:
            body += b'\x00'
    return b'FORM' + struct.pack('>I', len(body)) + bytes(body)


def selftest(stock, scratch):
    raw = open(stock, 'rb').read()
    assert hashlib.md5(raw).hexdigest() == FLOOR_MD5, "not the stock Floor 3.80.0 .hxf"
    data = [b for c, p, s, b in hxf._chunks(raw) if c == b'data'][0]
    payload = zlib.decompress(data)
    same = pack(payload, raw)
    assert same == raw, "stock payload does not round-trip byte for byte"
    grown = payload + b'\0' * 16                       # (not a valid image: only the container is checked)
    out = pack(grown, raw)
    ch = {c: b for c, p, s, b in hxf._chunks(out)}
    assert struct.unpack('>I', ch[b'dinf'][12:16])[0] == len(grown)
    assert struct.unpack('>I', ch[b'HEAD'][16:20])[0] == len(grown)
    assert ch[b'HEAD'][20:36] == hashlib.md5(grown).digest()
    assert zlib.decompress(ch[b'data']) == grown
    print("selftest: stock round trip identical; a grown payload updates dinf length, HEAD size and MD5: OK")


def main():
    a = sys.argv[1:]
    if a[:1] == ["pack"] and "--donor" in a:
        payload = open(a[1], 'rb').read()
        raw = open(a[a.index("--donor") + 1], 'rb').read()
        assert hashlib.md5(raw).hexdigest() == FLOOR_MD5, "the donor must be the stock Floor 3.80.0 .hxf"
        out = pack(payload, raw)
        open(a[2], 'wb').write(out)
        print(f"[+] wrote {a[2]}: {len(out)} bytes, payload md5 {hashlib.md5(payload).hexdigest()}")
    elif a[:1] == ["selftest"]:
        selftest(a[1], a[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
