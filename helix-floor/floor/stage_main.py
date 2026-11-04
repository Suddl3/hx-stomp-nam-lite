#!/usr/bin/env python3
"""Build stage E: the main program (Entry 0 only; its identical copy, Entry 1, stays stock).

- seg0 (local SRAM, 0x10000000 + 0x11870) grows into the cave from 0x10011870 (no code
  names it, no stack or heap there: floor-port-findings.md; the bootloader's view of a
  bigger seg0 needs the hardware test). The cave holds, in order: the guard HOOK
  (floor/arm_guards.py, fixed at 0x10011870), then the relocated tables.
- The stock budget check 0x28135070 jumps to HOOK (8 bytes).
- As upstream's add_model_entry0, with the Floor's addresses (no Table 2 "+5" pointer on
  the Floor): Table 1 + the NAM row (a free preset id), Table 2 + the NAM row (short name,
  8 parameters), every browser list holding Clarity relocated with a NAM item, and a new
  folder "NAM" under Amp (category 12) with one item.

usage: stage_main.py <in.l6ia> <out.l6ia>
"""
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import arm_guards  # noqa: E402
import ir_title  # noqa: E402

E_MAIN, E_COPY, E_DB = 0, 1, 4
TAB1_BASE_PTRS = (0x28134D70, 0x28134DBC, 0x28134DD4, 0x28134EC8, 0x28134F80)
TAB1_END_PTR = 0x28134DB8
TAB1_CNT_INSN = 0x28134DC0
TAB1_CNT_M1_INSNS = (0x28134DA8, 0x28134E32, 0x28134EDA)
TAB2_BASE_PTR, TAB2_CNT_INSN = 0x280E027C, 0x280E01DC
BLIST_PTR_TAB, BLIST_CNT_TAB = 0x28134220, 0x28134350
SUBCAT_CNT, SUBCAT_NAMES = 0x28134480, 0x281344CC
CAVE, CAVE_END = 0x10011870, 0x10020000
SEG0 = (0x10000000, 0x11870)
DSP_COST = 2700            # ~30% of a DSP's 9000; upstream's measured-Stomp 2345 plus margin for Block 3 code
NAME, DISPLAY, SHORT, FOLDER = 'HD2_AmpNAMLite', 'NAM A2 Lite', 'NAM A2 Lite', (12, 'NAM')


def segments(e0):
    magic, size, icrc, ver, nsegs = struct.unpack_from('<5I', e0, 0)
    assert magic == 0x230B0C5E and size == len(e0), (hex(magic), size, len(e0))
    segs, off = [], 0x34
    for _ in range(nsegs):
        slen, dst, nxt = struct.unpack_from('<3I', e0, off)
        assert nxt == off + 12 + slen
        segs.append([off, off + 12, slen, dst, nxt])
        off = nxt
    return segs


class Image:
    def __init__(self, e0):
        self.b = bytearray(e0)
        self.segs = segments(self.b)

    def fo(self, va, n=4):
        for _, p, l, d, _ in self.segs:
            if d <= va and va + n <= d + l:
                return p + va - d
        raise SystemExit(f"{va:#x} not mapped")

    def rd(self, va, n):
        return bytes(self.b[self.fo(va, n): self.fo(va, n) + n])

    def wr(self, va, data):
        f = self.fo(va, len(data))
        self.b[f: f + len(data)] = data

    def u32(self, va):
        return struct.unpack('<I', self.rd(va, 4))[0]


def tables(im, src_ni, new_ni, n_params):
    """The new Table 1, Table 2 and browser lists (upstream add_model_entry0's steps 1-3)."""
    log = []
    tab1 = im.u32(TAB1_BASE_PTRS[0])
    assert all(im.u32(p) == tab1 for p in TAB1_BASE_PTRS)
    rd_cnt, n1 = pa._decode_thumb_movw(im.rd(TAB1_CNT_INSN, 4))
    assert n1 == 823 and im.u32(TAB1_END_PTR) == tab1 + 12 * n1
    for a in TAB1_CNT_M1_INSNS:
        assert pa._decode_thumb_movw(im.rd(a, 4))[1] == n1 - 1
    t1 = bytearray(im.rd(tab1, 12 * n1))
    rows = [struct.unpack_from('<IHHI', t1, 12 * i) for i in range(n1)]
    assert new_ni not in [r[0] for r in rows]
    src = next(r for r in rows if r[0] == src_ni)
    free = sorted(set(range(1, 833)) - {r[1] for r in rows})
    pid = free[0]
    t1 += struct.pack('<IHHI', new_ni, pid, 0, DSP_COST)
    log.append(f"Table 1: {n1} -> {n1 + 1} rows; NAM preset id {pid} (free: {free[:8]}...), DSP cost {DSP_COST} "
               f"(Clarity {src[3]})")
    tab2 = im.u32(TAB2_BASE_PTR)
    rd2, n2 = pa._decode_thumb_movw(im.rd(TAB2_CNT_INSN, 4))
    assert n2 == 823
    t2 = bytearray(im.rd(tab2, 44 * n2))
    row = bytearray(next(t2[44 * i: 44 * i + 44] for i in range(n2) if struct.unpack_from('<I', t2, 44 * i)[0] == src_ni))
    struct.pack_into('<I', row, 0, new_ni)
    row[4:20] = SHORT.encode('latin1')[:16].ljust(16, b'\0')
    counts = struct.unpack_from('<3I', row, 24)
    assert len(set(counts)) == 1
    struct.pack_into('<3I', row, 24, n_params, n_params, n_params)
    t2 += row
    log.append(f"Table 2: {n2} -> {n2 + 1} rows")
    dname = DISPLAY.encode('latin1')[:25].ljust(26, b'\0')
    lists, folder_item = [], None
    for idx in range(pa.E0_BLIST_SLOTS):
        lp, lc = im.u32(BLIST_PTR_TAB + 4 * idx), im.u32(BLIST_CNT_TAB + 4 * idx)
        if not lp or not lc:
            continue
        raw = bytearray(im.rd(lp, 48 * lc))
        item = None
        for k in range(lc):
            bt, mi, ci, u12 = struct.unpack_from('<IIiH', raw, 48 * k)
            if mi == src_ni:
                item = bytearray(raw[48 * k: 48 * k + 48])
                struct.pack_into('<IIiH', item, 0, bt, new_ni, ci, pid if ci == -1 else u12)
                item[14:40] = dname
                struct.pack_into('<2I', item, 40, 1, 0)
                break
        if item is None:
            continue
        if idx // 4 == FOLDER[0]:
            if folder_item is None and ci == -1:
                folder_item = bytes(item)
        else:
            lists.append((idx, lc + 1, bytes(raw + item)))
            log.append(f"browser list ({idx // 4},{idx % 4}): {lc} -> {lc + 1} items")
    cat, fname = FOLDER
    nsub = im.u32(SUBCAT_CNT + 4 * cat)
    fb = fname.encode('latin1')[:25].ljust(26, b'\0')
    assert nsub < 4 and not im.u32(BLIST_PTR_TAB + 4 * (4 * cat + nsub))
    assert not any(im.rd(SUBCAT_NAMES + 104 * cat + 26 * nsub, 26))
    assert folder_item is not None
    lists.append((4 * cat + nsub, 1, folder_item))
    log.append(f"new folder '{fname}' = subcategory {nsub} of category {cat}, 1 item")
    return pid, (rd_cnt, n1 + 1, bytes(t1)), (rd2, n2 + 1, bytes(t2)), lists, (cat, nsub, fb), log


def build_e0(e0, src_ni, new_ni, n_params):
    im = Image(e0)
    assert (im.segs[0][3], im.segs[0][2]) == SEG0, "seg0 is not the stock one"
    pid, (rd1, c1, t1), (rd2, c2, t2), lists, (cat, nsub, fb), log = tables(im, src_ni, new_ni, n_params)
    hook = arm_guards.build().assemble()
    assert arm_guards.CAVE == CAVE
    cave = bytearray(hook)
    cave += bytes((-len(cave)) & 3)

    def put(data):
        nonlocal cave
        va = CAVE + len(cave)
        cave += data
        cave += bytes((-len(cave)) & 3)
        return va

    a1, a2 = put(t1), put(t2)
    la = [(idx, cnt, put(raw)) for idx, cnt, raw in lists]
    title_base = CAVE + len(cave)
    tcode, ca, cb = ir_title.build(title_base, [pid])
    put(tcode)
    assert CAVE + len(cave) <= CAVE_END, f"cave {len(cave)} bytes, room {CAVE_END - CAVE}"
    # pointers and counts (all in seg2: the file offsets don't move with seg0's growth... they do,
    # so everything is written before the cave is spliced in)
    for p in TAB1_BASE_PTRS:
        im.wr(p, struct.pack('<I', a1))
    im.wr(TAB1_END_PTR, struct.pack('<I', a1 + len(t1)))
    im.wr(TAB1_CNT_INSN, pa._encode_thumb_movw(rd1, c1))
    for a in TAB1_CNT_M1_INSNS:
        im.wr(a, pa._encode_thumb_movw(pa._decode_thumb_movw(im.rd(a, 4))[0], c1 - 1))
    im.wr(TAB2_BASE_PTR, struct.pack('<I', a2))
    im.wr(TAB2_CNT_INSN, pa._encode_thumb_movw(rd2, c2))
    for idx, cnt, va in la:
        im.wr(BLIST_PTR_TAB + 4 * idx, struct.pack('<I', va))
        im.wr(BLIST_CNT_TAB + 4 * idx, struct.pack('<I', cnt))
    im.wr(SUBCAT_CNT + 4 * cat, struct.pack('<I', nsub + 1))
    im.wr(SUBCAT_NAMES + 104 * cat + 26 * nsub, fb)
    stock_check = im.rd(arm_guards.TRAMP, 16)
    assert stock_check[:4] == bytes.fromhex("42f22830"), f"0x28135070 is not the stock budget check: {stock_check.hex()}"
    im.wr(arm_guards.TRAMP, arm_guards.tramp_bytes())
    for va, want in ir_title.STOCK.items():
        assert im.rd(va, len(want)) == want, f"title site {va:#x} is not stock: {im.rd(va, len(want)).hex()}"
    assert im.rd(ir_title.RELAY, 8) == ir_title.RELAY_BEFORE, "the relay's 8 bytes are not the old check's tail"
    for va, b in ir_title.site_patches(ca, cb).items():
        im.wr(va, b)
    # splice the cave after seg0's bytes and move every later segment
    b, segs = im.b, im.segs
    h0, p0, l0, d0, n0 = segs[0]
    out = bytearray(b[:n0]) + cave + b[n0:]
    delta = len(cave)
    struct.pack_into('<3I', out, h0, l0 + delta, d0, n0 + delta)
    for h, p, l, d, n in segs[1:]:
        struct.pack_into('<3I', out, h + delta, l, d, n + delta)
    struct.pack_into('<I', out, 4, len(out))
    out = l6ia.fix_internal_crcs(bytes(out))
    log.append(f"seg0 {l0:#x} -> {l0 + delta:#x} bytes (cave {CAVE:#x}..{CAVE + delta:#x}, "
               f"{CAVE_END - CAVE - delta} bytes left); Entry 0 {len(e0):#x} -> {len(out):#x}")
    log.append(f"guards: HOOK {len(hook)} bytes at {CAVE:#x}; 0x28135070 -> ldr.w pc, [pc] ; .word {CAVE | 1:#x}")
    log.append(f"IR-name title: caves {ca:#x} / {cb:#x} ({len(tcode)} B); sites {ir_title.SITE_A:#x}, "
               f"{ir_title.SITE_B:#x} (via relay {ir_title.RELAY:#x}) for preset id {pid}")
    log.append(f"tables at Table 1 {a1:#x}, Table 2 {a2:#x}, lists " + ", ".join(f"({i // 4},{i % 4}) {v:#x}" for i, _, v in la))
    return out, pid, log, (a1, a2, la, ca, cb, tcode)


def verify(e0, src_ni, new_ni, addrs):
    """Read the result back: segments chain, pointers and counts, the new rows, and the guard
    code in the cave run through the guard tests' interpreter."""
    im = Image(e0)
    a1, a2, la, ca, cb, tcode = addrs
    for va, b in ir_title.site_patches(ca, cb).items():
        assert im.rd(va, len(b)) == b
    assert im.rd(ca, len(tcode)) == tcode
    assert all(im.u32(p) == a1 for p in TAB1_BASE_PTRS)
    assert pa._decode_thumb_movw(im.rd(TAB1_CNT_INSN, 4))[1] == 824 and im.u32(TAB1_END_PTR) == a1 + 12 * 824
    assert im.u32(TAB2_BASE_PTR) == a2 and pa._decode_thumb_movw(im.rd(TAB2_CNT_INSN, 4))[1] == 824
    assert struct.unpack_from('<I', im.rd(a1 + 12 * 823, 12))[0] == new_ni
    assert struct.unpack_from('<I', im.rd(a2 + 44 * 823, 44))[0] == new_ni
    for idx, cnt, va in la:
        assert im.u32(BLIST_PTR_TAB + 4 * idx) == va and im.u32(BLIST_CNT_TAB + 4 * idx) == cnt
        assert struct.unpack_from('<I', im.rd(va + 48 * (cnt - 1), 48), 4)[0] == new_ni
    assert im.rd(arm_guards.TRAMP, 8) == arm_guards.tramp_bytes()
    assert im.rd(CAVE, len(arm_guards.build().assemble())) == arm_guards.build().assemble()
    return "read back: pointers, counts, new rows, trampoline and HOOK bytes as built"


def main():
    src, out = sys.argv[1], sys.argv[2]
    data, _ = pa.load_l6ia_from_any(src)
    db = pa.parse_entry3_full(pa.get_entry_swapped(data, E_DB))
    src_ni = pa.find_model(db, 'HD2_AmpLine6Clarity')['words'][2]
    nam = pa.find_model(db, NAME)
    assert nam['name'] == NAME, "run stage_model first"
    new_ni, n_params = nam['words'][2], len(nam['params'])
    e0 = pa.get_entry_swapped(data, E_MAIN)
    assert e0 == pa.get_entry_swapped(data, E_COPY), "Entries 0 and 1 are not identical"
    new0, pid, log, addrs = build_e0(e0, src_ni, new_ni, n_params)
    msg = verify(new0, src_ni, new_ni, addrs)
    # Entry 1 stays stock: on the Floor the app itself runs update mode ("Entered Update Mode!"),
    # so an untouched copy may be the way back if the patched one fails; it also shows which copy runs.
    img, _, _ = l6ia.rebuild_archive(data, {E_MAIN: new0})
    assert pa.get_entry_swapped(img, E_COPY) == e0, "Entry 1 changed"
    open(out, 'wb').write(img)
    for line in log + [msg]:
        print(line)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
