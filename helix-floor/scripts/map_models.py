"""Read-only: list amps in a Line 6 model DB entry and their graph-library composites.
Usage: map_models.py <modeldb.bin> <graphlib.bin> [model-name]"""
import struct, sys, collections

db = open(sys.argv[1], 'rb').read()
gl = open(sys.argv[2], 'rb').read()
w4 = struct.unpack('<%dI' % (len(gl) // 4), gl)

magic, ver, tsize, str_off, scrc, str_len, mtab_off, mcnt, gtab_off, gcnt = struct.unpack_from('<10I', db, 0)
assert magic == 0x4023245e
nstr, _ = struct.unpack_from('<2I', db, str_off)
base = str_off + 8 + 12 * nstr
strings = []
for i in range(nstr):
    roff, _, ln = struct.unpack_from('<3I', db, str_off + 8 + 12 * i)
    strings.append(db[base + roff: base + roff + ln].decode('latin1'))

def meta(off, cnt):
    out = {}
    for k in range(cnt):
        ks, kt, kv = struct.unpack_from('<3I', db, off + 12 * k)
        out[strings[ks]] = strings[kv] if kt == 7 and kv < len(strings) else kv
    return out

models = []
for i in range(mcnt):
    m = struct.unpack_from('<14I', db, mtab_off + 56 * i)
    params = []
    for p in range(m[7]):
        pc, po, pn, pt, ps, pmin, pmax, pdef = struct.unpack_from('<5I3f', db, m[11] + 32 * p)
        params.append((strings[pn], pt, ps, pmin, pmax, pdef))
    models.append(dict(name=strings[m[2]], id=m[3], blob=m[13], meta=meta(m[1], m[0]), params=params))

assert w4[0] == 0x28267e5e
nblob, dir_off = w4[2], w4[3]
dirs = [(w4[dir_off + 2 * k], w4[dir_off + 2 * k + 1]) for k in range(nblob)]
def blob(i):
    ln, off = dirs[i]
    return w4[off:off + ln]
b0 = blob(0)

def top(b):
    return b[b[2] + 1] if len(b) > 4 and b[0] == 3 else None

def composite(cid):
    idx = cid - 0x600000
    hdr = b0[b0[0x10] + 7 * idx: b0[0x10] + 7 * idx + 7]
    n_in, n_out, n_mem, mem_off = hdr[:4]
    mems = [b0[mem_off + 20 * k: mem_off + 20 * k + 20] for k in range(n_mem)]
    return n_in, n_out, mems

def leaves(cid):
    out = []
    for r in composite(cid)[2]:
        if r[4] == 0:
            out += leaves(r[6]) if 0x600000 <= r[6] < 0x601000 else [r[6]]
    return out

print(f"model DB: {mcnt} models, {nstr} strings; graph lib: {nblob} blobs, blob0 {len(b0):#x} words, "
      f"{b0[0xf]} composites")
amps = [m for m in models if m['name'].startswith('HD2_Amp')]
print(f"{len(amps)} HD2_Amp models; preset ids {min(m['id'] for m in amps)}..{max(m['id'] for m in amps)}; "
      f"all model ids max {max(m['id'] for m in models)}")
q = sys.argv[3] if len(sys.argv) > 3 else 'HD2_AmpLine6Clarity'
for m in models:
    if m['name'] == q:
        print(f"\n{m['name']} id={m['id']} blob={m['blob']} meta={m['meta']}")
        for p in m['params']:
            print("   param", p)
        b = blob(m['blob'])
        t = top(b)
        print(f"  blob len {len(b)} top composite {t:#x}")
        n_in, n_out, mems = composite(t)
        print(f"  composite in={n_in} out={n_out} members={len(mems)}")
        for r in mems:
            print(f"    flags={r[4]} type={r[6]:#x} dm={r[13]} pm={r[14]}")
            if 0x600000 <= r[6] < 0x601000 and r[4] == 0:
                print("      leaves:", dict(collections.Counter(hex(x) for x in leaves(r[6]))))
