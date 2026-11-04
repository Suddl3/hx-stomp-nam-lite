#!/usr/bin/env python3
"""Build stages B2 + B3: the NAM kernel (floor/nam_floor.py, Floor layout and addresses) into
the SHARC boot stream (Entry 2), and the unused primitive HOOK_ID pointed at it.

As upstream's patch_amp patch: every .section pm becomes an INIT_L48 block and every
.section dm an INIT_L32 block, inserted before FINAL_INIT; the primitive's registry record
gets primitive 0x822's handlers (the Floor's copies) and the kernel's entry. Differences:
the record's instance sizes are the kernel's Floor needs (the same numbers stage_model puts
in the graph member), and every section is checked to lie in a region the 13-block layout
freed (or the DDR2 run past Heap 6's new place). Entry 2's size is checked against the
Floor's eMMC slot (sector 0x8007 to Entry 4's 0x880a, less the sub-header sector).

usage: stage_kernel.py <in.l6ia> <out.l6ia> [--no-check]
"""
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import sasm  # noqa: E402
import importlib, os  # noqa: E402
nam_floor = importlib.import_module(os.environ.get("NAM_KERNEL", "nam_floor"))   # (nam_floor4: 2 NAM per DSP)
import nam_lite  # noqa: E402
from stage_model import HOOK_ID, BLOB0_BASE, BLOB0_CAP  # noqa: E402

HOOK_REC = 0x200088                       # the registry record of primitive 0x128
STOCK_HOOK_REC = [0x128, 0x60C266, 0x0, 0x60C2B1, 0x60C1F5, 0x8CF39, 0x9, 0x4]
H822 = [0x61343A, 0x0, 0x61349E, 0x613387]   # primitive 0x822's init, -, f3, parameter handlers
REGIONS = {k: v for k, v in getattr(nam_floor, "REGIONS3", getattr(nam_floor, "REGIONS", {})).items() if k != "RX"}
E2_MAX = 0x400 * 512                # Entry 2's partition: 0x400 sectors (the app's partition table 0x28116124)


def registry_record(w):
    NW = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2,
          6: lambda c: c * 2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
    i = 384
    while i + 3 <= len(w):
        tag, cnt, addr = w[i:i + 3]
        if tag == 0:
            break
        if tag == 4 and addr <= HOOK_REC < addr + cnt:
            k = i + 3 + HOOK_REC - addr
            return list(w[k:k + 8])
        i += 3 + NW.get(tag, lambda c: 0)(cnt)
    return None


def blob0_tail(e5):
    """(Blob 0 length in words, its directory index pairs): Entry 5 after stage_model."""
    w = list(struct.unpack('<%dI' % (len(e5) // 4), e5))
    ln, off = w[w[3]], w[w[3] + 1]
    return w, ln, off


def append_to_blob0(e5, words):
    """Entry 5 with `words` appended to Blob 0; every blob stored after Blob 0 moves up."""
    w, ln, off = blob0_tail(e5)
    n, d, nb = len(words), w[3], w[2]
    end = off + ln
    pairs = [(w[d + 2 * k], w[d + 2 * k + 1]) for k in range(nb)]
    assert d < off, "the directory is not before Blob 0"
    out = w[:end] + list(words) + w[end:]
    for k, (l, o) in enumerate(pairs):
        if k == 0:
            out[d] = l + n
        elif o >= end:
            out[d + 2 * k + 1] = o + n
    out[5] = len(out)
    return struct.pack('<%dI' % len(out), *out)


def ldr_dm(addr, words):
    """INIT_L32 blocks, with every run of 8 or more zero words as a ZERO_LDATA (tag 1)
    block (no payload), as stock Entry 2 does 90 times."""
    out, k, n = [], 0, len(words)
    while k < n:
        if words[k] == 0:
            j = k
            while j < n and words[j] == 0:
                j += 1
            if j - k >= 8:
                out += [1, j - k, addr + k]
                k = j
                continue
        j = k
        while j < n and not (words[j] == 0 and j + 8 <= n and not any(words[j:j + 8])):
            j += 1
        out += pa.pack_init_l32(addr + k, words[k:j])
        k = j
    return out


def main():
    src, out = sys.argv[1], sys.argv[2]
    data, _ = pa.load_l6ia_from_any(src)
    ents = l6ia.parse(data)
    e5 = pa.get_entry_swapped(data, 5)
    _, b0_len, _ = blob0_tail(e5)
    base = BLOB0_BASE + b0_len                     # the read-only tables follow Blob 0 in its buffer
    asm, lay = nam_floor.build(tables_base=base)
    if "RX" in getattr(nam_floor, "REGIONS3", {}):
        assert lay.rg.spare()["RX"] == nam_floor.REGIONS3["RX"][1] - nam_floor.REGIONS3["RX"][0], "kernel spills past the freed regions"
    assert lay.ddr2_to <= BLOB0_BASE + BLOB0_CAP, "the tables do not fit Blob 0's buffer"
    if os.environ.get("NAM_MAX_STEADY"):                 # (the channel-0 kernel is slower: its own limit)
        nam_floor.nm.MAX_STEADY = int(os.environ["NAM_MAX_STEADY"])
    if "--no-check" not in sys.argv and not os.environ.get("NAM_DIAG"):
        casm, clay = nam_floor.build(tables_base=base, inst_bounds=nam_floor.RIG_BOUNDS)
        nam_floor.nm.REP = clay.rep
        if hasattr(nam_floor, "check_bounds"):
            print("bounds guard:", nam_floor.check_bounds(casm, clay))
        ok, res, _ = nam_floor.check(casm, clay, nam_lite.placeholder())
        assert ok, f"KernelCheck failed: {res}"
        print(f"KernelCheck (Floor layout, rig bounds): PASS, steady mean {res['steady_mean']:.0f} instructions")
    e2 = data[ents[2]['payload_off']: ents[2]['payload_off'] + ents[2]['payload_len']]
    w = struct.unpack('<%dI' % (len(e2) // 4), e2)
    assert registry_record(w) == STOCK_HOOK_REC, f"primitive 0x128's record is not the stock one: {registry_record(w)}"
    secs, syms = sasm.assemble(asm, "nam_floor.asm")
    entry = syms["CUSTOM_AMP_ENTRY"]
    ldr, n_pm, n_dm, tail = [], 0, 0, {}
    for s in secs:
        if s.kind == "pm":
            nw0 = nam_floor.nm.NW3 + (s.addr - nam_floor.nm.NW3) * 3 // 2
            nw1 = nw0 + (nam_floor.nf.nw(len(s.words)) if hasattr(nam_floor, "nf") else nam_floor.nw(len(s.words)))
            assert any(a <= nw0 and nw1 <= b for a, b in REGIONS.values()), f"code at PM {s.addr:#x}"
            ldr += pa.pack_init_l48(s.addr, s.words)
            n_pm += len(s.words)
        elif s.kind == "dm" and base <= s.addr < lay.ddr2_to:
            assert s.addr + len(s.words) <= lay.ddr2_to
            for k, x in enumerate(s.words):
                tail[s.addr + k] = x
        elif s.kind == "dm":
            assert any(a <= s.addr and s.addr + len(s.words) <= b for a, b in REGIONS.values()),                 f"data at {s.addr:#x}"
            ldr += ldr_dm(s.addr, s.words)
            n_dm += len(s.words)
    assert sorted(tail) == list(range(base, lay.ddr2_to)), "the tables are not one run after Blob 0"
    new5 = append_to_blob0(e5, [tail[a] for a in range(base, lay.ddr2_to)])
    w5, l5, o5 = blob0_tail(new5)
    err = pa.sharc_blob0_check(list(w5[o5: o5 + l5]), BLOB0_CAP)
    assert err is None, err
    rec = [HOOK_ID, H822[0], H822[1], H822[2], H822[3], entry, lay.inst_dm_need, lay.inst_pm_need]
    ldr += pa.pack_init_l32(HOOK_REC, rec)
    w2 = list(w)
    fin = None
    i = 384
    NW = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2,
          6: lambda c: c * 2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
    while i + 3 <= len(w2):
        tag, cnt, addr = w2[i:i + 3]
        if tag == 0:
            fin = i
            break
        i += 3 + NW.get(tag, lambda c: 0)(cnt)
    assert fin is not None
    w2 = w2[:fin] + ldr + w2[fin:]
    new_e2 = struct.pack('<%dI' % len(w2), *w2)
    assert len(new_e2) <= E2_MAX, f"Entry 2 {len(new_e2):#x} bytes > its partition's {E2_MAX:#x}"
    assert registry_record(w2[:fin] + w2[fin + len(ldr):]) == STOCK_HOOK_REC
    img, _, _ = l6ia.rebuild_archive(data, {2: l6ia.swap32(new_e2), 5: new5})
    open(out, "wb").write(img)
    print(f"kernel: {n_pm} instructions, {n_dm} data words in Entry 2 (zero runs as ZERO_LDATA); entry {entry:#x}")
    print(f"read-only tables: {lay.ddr2_to - base} words after Blob 0 at {base:#x}..{lay.ddr2_to:#x} "
          f"(Blob 0 {b0_len:#x} -> {l5:#x} words, cap {BLOB0_CAP:#x}, relocation check OK)")
    print(f"primitive {HOOK_ID:#x} @ {HOOK_REC:#x} -> {[hex(x) for x in rec]}")
    print(f"Entry 2: {len(e2):#x} -> {len(new_e2):#x} bytes of its partition's {E2_MAX:#x} "
          f"({E2_MAX - len(new_e2)} spare)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
