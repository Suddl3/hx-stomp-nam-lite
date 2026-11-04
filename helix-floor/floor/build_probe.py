#!/usr/bin/env python3
"""test0_dfu_probe.hxf: the smallest install that answers "does the Floor's bootloader start
the boot ROM's USB DFU when it finds the Stomp's "BootIntoDfu!" note?" (floor-port-findings.md,
"Can the Floor reach the boot-ROM DFU?"). PC only, never share.

Stock 3.80.0 except Entry 0 (Entry 1 stays stock):
- seg0 grows by a few dozen bytes at 0x10011870 (the probe code and the note);
- in the reset routine 0x28114d88, the update-mode branch (r0 != 0) `bl 0x28110b60; b 0x28114d8c`
  at 0x28114d9c becomes `ldr.w pc, [pc, #0]; .word probe|1`. The probe copies "BootIntoDfu!\\0"
  to 0x1001ff00 (where the Stomp's app puts it, 0x28d99260), then goes on exactly as stock:
  0x28110b60(r0) saves the update-mode flag and returns to 0x28114d8c (wait, reset).
Plain restarts (r0 == 0) are not touched. If the bootloader ignores the note, the Floor enters
its normal update mode as now; if not, it shows up as 1fc9:000c.

usage: build_probe.py <stock Floor .hxf>
"""
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import floor_hxf  # noqa: E402
import stage_main  # noqa: E402
from arm_guards import Asm, ldr_imm, show  # noqa: E402
from build_staged import grow_seg0, check_and_pack  # noqa: E402

PROBE = 0x10011870
SITE, SITE_STOCK = 0x28114D8C, bytes.fromhex("054841f0affe054b")   # ldr r0,=2000000; bl wait; ldr r3,=RGU
WAIT, WAIT_US, RGU = 0x28156AF0, 0x1E8480, 0x40053000               # the stock tail: wait 2 s, core reset
NOTE_AT, NOTE = 0x1001FF00, b"BootIntoDfu!\0\0\0\0"


def str_imm(rt, rn, off):
    return 0x6000 | (off // 4) << 6 | rn << 3 | rt


def build():
    """(code + note, the note's address). Two passes: the note follows the code."""
    def asm(note_va):
        a = Asm(PROBE)
        a.lit(1, "note_at")
        a.lit(2, "note")
        for k in range(4):
            a.h(ldr_imm(3, 2, 4 * k))
            a.h(str_imm(3, 1, 4 * k))
        a.lit(0, "wait_us")                     # then the stock tail: wait 2 s ...
        a.lit(3, "wait")
        a.h(0x4798)                             # blx r3
        a.lit(3, "rgu")                         # ... and reset the core (RGU RESET_CTRL0 = 1)
        a.h(0x2201)                             # movs r2, #1
        a.h(0xF8C3)
        a.h(0x2100)                             # str.w r2, [r3, #0x100]
        a.h(0xE7FE)                             # b .
        a.align4()
        for name, v in (("note_at", NOTE_AT), ("note", note_va), ("wait_us", WAIT_US), ("wait", WAIT | 1),
                        ("rgu", RGU)):
            a.word(name, v)
        return a.assemble()
    n = len(asm(0))
    code = asm(PROBE + n)
    assert len(code) == n
    return code + NOTE, PROBE + n


def site_bytes():
    return struct.pack("<HHI", 0xF8DF, 0xF000, PROBE | 1)


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    e0 = pa.get_entry_swapped(data, 0)
    code, note_va = build()
    assert code.endswith(NOTE)
    im = stage_main.Image(e0)
    assert im.rd(SITE, 8) == SITE_STOCK, f"0x28114d9c is not stock: {im.rd(SITE, 8).hex()}"
    im.wr(SITE, site_bytes())
    g = bytearray(grow_seg0(bytes(im.b), len(code)))
    segs = stage_main.segments(g)
    h0, p0, l0, d0, n0 = segs[0]
    assert d0 + l0 - len(code) == PROBE
    g[p0 + l0 - len(code): p0 + l0] = code
    g = l6ia.fix_internal_crcs(bytes(g))
    chk = stage_main.Image(g)
    assert chk.rd(PROBE, len(code)) == code and chk.rd(SITE, 8) == site_bytes()
    img, _, _ = l6ia.rebuild_archive(data, {0: g})
    assert pa.get_entry_swapped(img, 1) == e0
    print(f"probe: {len(code)} bytes at {PROBE:#x} (note at {note_va:#x}); site {SITE:#x}:")
    show(code[:-len(NOTE)], PROBE)
    show(site_bytes(), SITE)
    print(f"seg0 {stage_main.segments(e0)[0][2]:#x} -> {segs[0][2]:#x}; Entry 1 stock")
    open(os.path.join(ROOT, "build", "probe_e0.bin"), "wb").write(g)
    check_and_pack(img, "test0_dfu_probe.hxf", raw)


if __name__ == "__main__":
    main()
