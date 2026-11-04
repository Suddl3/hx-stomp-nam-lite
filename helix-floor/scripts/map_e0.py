"""Read-only: find the Stomp patch's Entry 0 tables and code sites in another unit's main program.
Usage: map_e0.py <entry00.bin> <entry04.bin (model DB)>"""
import struct, sys, collections

e0 = open(sys.argv[1], 'rb').read()
db = open(sys.argv[2], 'rb').read()

segs, off = [], 0x34
nsegs = struct.unpack_from('<I', e0, 16)[0]
for _ in range(nsegs):
    slen, dst, nxt = struct.unpack_from('<3I', e0, off)
    segs.append((off + 12, slen, dst))
    off = nxt

def va(fo):
    for p, l, d in segs:
        if p <= fo < p + l:
            return d + fo - p

def fo(v, n=4):
    for p, l, d in segs:
        if d <= v and v + n <= d + l:
            return p + v - d

def u32v(v):
    return struct.unpack_from('<I', e0, fo(v))[0]

str_off = struct.unpack_from('<I', db, 12)[0]
nstr = struct.unpack_from('<I', db, str_off)[0]
base = str_off + 8 + 12 * nstr
strings = []
for i in range(nstr):
    roff, _, ln = struct.unpack_from('<3I', db, str_off + 8 + 12 * i)
    strings.append(db[base + roff: base + roff + ln].decode('latin1'))
CLARITY = strings.index('HD2_AmpLine6Clarity')

words = {}
for o in range(0, len(e0) - 3, 2):
    words.setdefault(struct.unpack_from('<I', e0, o)[0], []).append(o)

def refs(v):
    return [va(o) for o in words.get(v, []) if o % 4 == 0 and va(o)]

def movw(o):
    hw1, hw2 = struct.unpack_from('<2H', e0, o)
    if (hw1 & 0xfbf0) != 0xf240 or hw2 & 0x8000:
        return None
    return (hw2 >> 8) & 0xf, ((hw1 & 0xf) << 12) | (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xff)

def movws(lo, hi, imm):
    out = []
    for v in range(lo, hi, 2):
        o = fo(v)
        if o is not None:
            m = movw(o)
            if m and m[1] == imm:
                out.append((hex(v), f'r{m[0]}'))
    return out

print("segments:", [(hex(d), hex(l)) for p, l, d in segs])

# --- Table 1 ---------------------------------------------------------------
def row_ok(o):
    i, pid, z, c = struct.unpack_from('<IHHI', e0, o)
    return z == 0 and 0 < i < nstr and pid <= 1000 and c < 100000
hit = next(o for o in range(0, len(e0) - 12, 4)
           if struct.unpack_from('<I', e0, o)[0] == CLARITY and row_ok(o) and row_ok(o - 12) and row_ok(o + 12))
s = hit
while row_ok(s - 12): s -= 12
e = hit
while row_ok(e): e += 12
t1, t1n, t1end = va(s), (e - s) // 12, va(e)
print(f"\nTAB1 {t1:#x} rows={t1n} end={t1end:#x}")
p_start, p_end = refs(t1), refs(t1end)
print("  TAB1_BASE_PTRS", [hex(x) for x in p_start])
print("  TAB1_END_PTR  ", [hex(x) for x in p_end])
lo, hi = min(p_start + p_end) - 0x400, max(p_start + p_end) + 0x100
print(f"  movw {t1n} (count) near:", movws(lo, hi, t1n))
print(f"  movw {t1n - 1} (count-1) near:", movws(lo, hi, t1n - 1))

# --- Table 2 (44-byte rows, short name at +4) ------------------------------
def t2_ok(o):
    if o < 0 or o + 44 > len(e0): return False
    i = struct.unpack_from('<I', e0, o)[0]
    nm = e0[o + 4:o + 20]
    return 0 < i < nstr and 0x20 <= nm[0] < 0x7f and all(b == 0 or 0x20 <= b < 0x7f for b in nm)
c2 = next(o for o in range(0, len(e0) - 44, 4)
          if struct.unpack_from('<I', e0, o)[0] == CLARITY and e0[o + 4:o + 17] == b'Line6 Clarity')
s = c2
while t2_ok(s - 44): s -= 44
e = c2
while t2_ok(e): e += 44
t2, t2n = va(s), (e - s) // 44
print(f"\nTAB2 {t2:#x} rows={t2n} (first name idx {struct.unpack_from('<I', e0, s)[0]} = {strings[struct.unpack_from('<I', e0, s)[0]]})")
for cand in (t2, t2 + 44, t2 - 44):
    r0, r5 = refs(cand), refs(cand + 5)
    if r0 or r5:
        print(f"  base {cand:#x}: ptr refs {[hex(x) for x in r0]}  +5 refs {[hex(x) for x in r5]}")
        near = min(r0 + r5)
        print(f"  movw {t2n} near:", movws(near - 0x200, near + 0x80, t2n))

# --- Browser lists (48-byte items) ------------------------------------------
def item_ok(o):
    if o < 0 or o + 48 > len(e0): return False
    bt, m, c, u = struct.unpack_from('<IIiH', e0, o)
    nm = e0[o + 14:o + 40]
    return bt < 64 and 0 < m < nstr and -1 <= c < nstr and 0x20 <= nm[0] < 0x7f
starts = set()
for o in range(0, len(e0) - 48, 2):
    if struct.unpack_from('<I', e0, o + 4)[0] == CLARITY and item_ok(o) and b'Clarity' in e0[o + 14:o + 40]:
        s = o
        while item_ok(s - 48): s -= 48
        starts.add(s)
print("\nbrowser lists holding Clarity:", [hex(va(s)) for s in sorted(starts)])
ptr_locs = collections.Counter()
for s in starts:
    for r in refs(va(s)):
        ptr_locs[r] += 1
print("  literal locations:", [hex(x) for x in sorted(ptr_locs)])
# a 76-entry pointer table: find an aligned run of words whose nonzero members are all list starts
for r in sorted(ptr_locs):
    for k in range(76):
        tab = r - 4 * k
        vals = [u32v(tab + 4 * j) for j in range(76)]
        cnts = [u32v(tab + 0x130 + 4 * j) for j in range(76)]
        nz = [(v, c) for v, c in zip(vals, cnts) if v]
        if nz and all(fo(v) is not None and item_ok(fo(v)) and 0 < c < 200 for v, c in nz) and sum(1 for v in vals if v) >= 19:
            print(f"  BLIST_PTR_TAB {tab:#x} ({len(nz)} lists)  BLIST_CNT_TAB {tab + 0x130:#x}")
            sc = tab + 0x260
            print(f"  SUBCAT_CNT {sc:#x}: {[u32v(sc + 4 * j) for j in range(19)]}")
            sn = sc + 0x4c
            names = [e0[fo(sn + 104 * c + 26 * j):fo(sn + 104 * c + 26 * j) + 26].rstrip(b'\0') for c in range(19) for j in range(4)]
            print(f"  SUBCAT_NAMES {sn:#x}: {[n.decode('latin1') for n in names if n]}")
            print(f"  amp category lists (cat 11): {[(hex(vals[44 + j]), cnts[44 + j]) for j in range(4)]}")
            break
    else:
        continue
    break

# --- IR-title sites ----------------------------------------------------------
print("\nIR-title sites (ldrb r3,[rN,#12]; cmp r3,#15; b<cc>):")
for o in range(0, len(e0) - 6, 2):
    h0, h1, h2 = struct.unpack_from('<3H', e0, o)
    if (h0 & 0xffc7) == 0x7b03 and h1 == 0x2b0f and (h2 & 0xfe00) == 0xd000:   # ldrb r3,[rN,#12]
        rn = (h0 >> 3) & 7
        cond = 'beq' if (h2 >> 8) & 0xf == 0 else 'bne' if (h2 >> 8) & 0xf == 1 else f'b{(h2 >> 8) & 0xf}'
        tgt = va(o) + 4 + 4 + 2 * (((h2 & 0xff) ^ 0x80) - 0x80)
        print(f"  {va(o):#x}: ldrb r3,[r{rn},#12]; cmp r3,#15; {cond} {tgt:#x}   bytes {e0[o:o + 6].hex()}")

# --- SDRAM above the program -------------------------------------------------
top = max(d + l for p, l, d in segs if d >= 0x28000000)
hi_refs = sorted({w for w in words if top <= w < 0x2a000000})
print(f"\nSDRAM program image ends at {top:#x}; highest SDRAM addresses the code names: "
      f"{[hex(x) for x in hi_refs[-8:]]} ({len(hi_refs)} distinct above the image)")
