#!/usr/bin/env python3
"""The block title shows the selected User IR's name for NAM blocks (the Floor's version of
upstream's ir-title; the Floor's title code differs from the Stomp's).

Floor title code (Entry 0):
- site A `0x280ac164`: `ldrb r3,[r6,#12]; cmp r3,#15; beq.w 0x280ac374` (category 15 = IR ->
  the IR path, which takes r4 = subcategory and, for 0, the IR Single name branch
  `0x280ac8ee`); otherwise `0x280ac16c`.
- site B `0x280ad37c` (a knob changed): `ldrb r3,[r5,#12]; cmp r3,#15; beq 0x280ad38e` (IR:
  knob 0 redraws the title) else `0x280ad382` (return).
- r6 / r5 point at the block's descriptor: +1 its preset id (word), +12 category, +13 subcategory.

Patch: for an Amp-category (12) block whose preset id is one of PIDS, site A goes to the IR
Single name branch with r4 = 0 (as an IR Single block; the Model knob is knob 0, an IR
index like the IR block's), and site B treats it as an IR block (knob 0 redraws). Amp+Cab
(11) blocks keep the stock title (no cab-half confusion). The IR path's `[...+0x9c]` test
before the name branch is skipped for NAM blocks.

Both caves live in the seg0 cave (local SRAM, out of B.W range of seg2): site A becomes
`ldr.w pc,[pc,#0]; .word caveA|1` (its 8 bytes); site B (6 bytes) a `b.w` to a relay
`ldr.w pc,[pc,#0]; .word caveB|1` in the 8 bytes the guard trampoline left free at
0x28135078 (the old budget check's tail; nothing branches into it). The caves return
through `ldr.w pc` literals. Only r3 (and r4 = 0 on the NAM path, as the IR path sets it)
change, as at the stock sites.
"""
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arm_guards import Asm, cmpi, movs  # noqa: E402

SITE_A, SITE_A_STOCK = 0x280AC164, bytes.fromhex("337b0f2b00f00481")
SITE_B, SITE_B_STOCK = 0x280AD37C, bytes.fromhex("2b7b0f2b05d0")
IR_PATH, NON_IR, IR_NAME = 0x280AC374, 0x280AC16C, 0x280AC8EE
B_IR, B_RET = 0x280AD38E, 0x280AD382
RELAY = 0x28135078
CAT_IR, CAT_AMP = 15, 12


def ldrb_r3(rn):
    return 0x7800 | 12 << 6 | rn << 3 | 3


def ldrw_r3_1(rn):
    """ldr.w r3, [rn, #1] (T3)."""
    return [0xF8D0 | rn, 0x3001]


def cmp_r3(v):
    import patch_amp
    b = patch_amp._cmp_r3(v)
    return list(struct.unpack('<%dH' % (len(b) // 2), b))


def build(base, pids):
    a = Asm(base)

    def hs(lst):
        for h in lst:
            a.h(h)

    # caveA (site A: r6 = the block)
    a.label("caveA")
    a.h(ldrb_r3(6))
    a.h(cmpi(3, CAT_IR))
    a.b("ne", "a1")
    a.ldrpc("w_ir_path")
    a.label("a1")
    a.h(cmpi(3, CAT_AMP))
    a.b("ne", "a3")
    hs(ldrw_r3_1(6))
    for p in pids:
        hs(cmp_r3(p))
        a.b("eq", "a2")
    a.label("a3")
    a.ldrpc("w_non_ir")
    a.label("a2")
    a.h(movs(4, 0))
    a.ldrpc("w_ir_name")
    # caveB (site B: r5 = the block)
    a.label("caveB")
    a.h(ldrb_r3(5))
    a.h(cmpi(3, CAT_IR))
    a.b("eq", "b4")
    a.h(cmpi(3, CAT_AMP))
    a.b("ne", "b5")
    hs(ldrw_r3_1(5))
    for p in pids:
        hs(cmp_r3(p))
        a.b("eq", "b4")
    a.label("b5")
    a.ldrpc("w_b_ret")
    a.label("b4")
    a.ldrpc("w_b_ir")
    a.align4()
    for name, v in (("w_ir_path", IR_PATH), ("w_non_ir", NON_IR), ("w_ir_name", IR_NAME),
                    ("w_b_ret", B_RET), ("w_b_ir", B_IR)):
        a.word(name, v | 1)
    code = a.assemble()
    return code, a.labels["caveA"], a.labels["caveB"]


def site_patches(ca, cb):
    """{address: bytes} for the two sites and the relay."""
    import patch_amp
    return {SITE_A: struct.pack("<HHI", 0xF8DF, 0xF000, ca | 1),
            SITE_B: patch_amp.thumb_bw(SITE_B, RELAY) + b"\x00\xbf",
            RELAY: struct.pack("<HHI", 0xF8DF, 0xF000, cb | 1)}


STOCK = {SITE_A: SITE_A_STOCK, SITE_B: SITE_B_STOCK}
RELAY_BEFORE = bytes.fromhex("00200120704700bf")     # movhi r0,#0; movls r0,#1; bx lr; nop: the
#                                                      old budget check's tail, dead once its head jumps
