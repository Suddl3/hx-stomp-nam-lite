#!/usr/bin/env python3
"""TAP-LIST PROBE image (test only; NOMASK kernel + meter): at each call's exit, with channel 0 idle,
one scatter/gather (tap list) DMA of 2 taps x 4 words from the instance's own SDRAM block (G_SDR,
offsets 5 and 21) into PRB+10, polled (DMAC0) at most 2000 times; then the NAM output is replaced
by eight 2-sample fields (meter v4 framing, field 0 = +16384):
  1 -polls   2 +(DMAC0 after >> 16) & 0x7FFF   3 -match bits: 1 d0==S6 (pre-modify), 2 d0==S5 (post),
  4 d4==S22, 8 d4==S21, 16 d0==S0, 32 d0 poison kept
  4 +d0 & 0x7FFF   5 -S5 & 0x7FFF   6 +S6 & 0x7FFF   7 -d4 & 0x7FFF
usage: NAM_KERNEL=nam_floor5t (build_floor2.py --probe)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor5 as n5  # noqa: E402
from nam_floor5 import *  # noqa: E402,F401,F403

assert n5.P9_MODE == "nomask"
POISON = 0x7FC0BAD0
PROBE = ("""x_idle:
    R0 = DM(SAVE + 1);""", f"""x_idle:
    R0 = DM(G_SDR);                     // (probe v2) E = the weights + 64: distinct words
    R1 = W_OFF + 64;
    R0 = R0 + R1;
    DM(PRB + 4) = R0;                   // (the TCBs and tap lists are static data: words())
    DM(PRB + 12) = R0;
    R1 = {POISON:#x};
    DM(PRB + 20) = R1;
    DM(PRB + 24) = R1;
    DM(PRB + 28) = R1;
    R1 = DFLSH;
    DM(DMAC0) = R1;
    R1 = 0;
    DM(CPEP0) = R1;
    R1 = DEN_CHEN | TLEN;
    DM(DMAC0) = R1;
    R1 = (PRB + 7) & 0x7FFFF;
    DM(CPEP0) = R1;
    R2 = 0;
pr_w: R2 = R2 + 1;
    R1 = DM(DMAC0);
    R3 = 0x1300000;                     // DMAS | CHS | EXTS (DEN stays set)
    R3 = R1 AND R3;
    IF EQ JUMP pr_d;
    R3 = 2000;
    COMP(R2, R3);
    IF LT JUMP pr_w;
pr_d: DM(PRB + 29) = R1;
    R1 = 0;
    DM(DMAC0) = R1;
    // ---- the fields
    I4 = R0;                            // E (the core reads DDR2 directly)
    I5 = PRB + 20;
    R8 = 0x7FFF;
    R0 = 16384;                         // 0
    R1 = -R2;                           // 1: -polls
    R2 = DM(PRB + 29);                  // 2: DMAC0 >> 16
    R2 = LSHIFT R2 BY -16;
    R2 = R2 AND R8;
    R9 = DM(0, I5);                     // d0
    R10 = DM(4, I5);                    // d4
    R12 = DM(8, I5);                    // the TCB 1 word
    R3 = 0;                             // 3: bits
    R11 = DM(6, I4);
    COMP(R9, R11);
    IF EQ R3 = R3 + 1;
    R11 = DM(5, I4);
    R4 = 2;
    COMP(R9, R11);
    IF EQ R3 = R3 + R4;
    R11 = DM(22, I4);
    R4 = 4;
    COMP(R10, R11);
    IF EQ R3 = R3 + R4;
    R11 = DM(21, I4);
    R4 = 8;
    COMP(R10, R11);
    IF EQ R3 = R3 + R4;
    R11 = DM(41, I4);
    R4 = 16;
    COMP(R12, R11);
    IF EQ R3 = R3 + R4;
    R11 = DM(40, I4);
    R4 = 32;
    COMP(R12, R11);
    IF EQ R3 = R3 + R4;
    R11 = {POISON:#x};
    R4 = 64;
    COMP(R12, R11);
    IF EQ R3 = R3 + R4;
    R4 = 128;
    COMP(R9, R11);
    IF EQ R3 = R3 + R4;
    R3 = -R3;
    R4 = R9 AND R8;                     // 4: d0
    R5 = DM(6, I4);                     // 5: -S6
    R5 = R5 AND R8;
    R5 = -R5;
    R6 = R12 AND R8;                    // 6: the TCB 1 word
    R7 = DM(41, I4);                    // 7: -S41
    R7 = R7 AND R8;
    R7 = -R7;
    F8 = 3.0517578125e-05;
    I11 = B11;
""" + "".join(f"""    F{k} = FLOAT R{k};
    F{k} = F{k} * F8;
    PM(I11, M9) = R{k};
    PM(I11, M9) = R{k};
""" for k in range(8)) + """    R0 = DM(SAVE + 1);""")
_kernel_src = n5.kernel_src


def kernel_src():
    s = _kernel_src()
    assert s.count(PROBE[0]) == 1, "x_idle anchor"
    return s.replace(*PROBE)


n5.kernel_src = kernel_src
n5.SLOTS = 1
n5.PRB_WORDS = 30
_names = n5.names
n5.names = lambda: _names() + ["PRB"] + ([] if "TLEN" in _names() else ["TLEN"]) + ([] if "W_OFF" in _names() else ["W_OFF"])
_init = n5.Layout.__init__


def _layout_init(self, *a, **kw):
    _init(self, *a, **kw)
    self.v["TLEN"] = n5.TLEN


n5.Layout.__init__ = _layout_init
_words = n5.Layout.words


def _words_prb(self):
    mem = _words(self)
    p = self.v["PRB"]
    for i, x in enumerate([(p + 15) & 0x7FFFF, p + 16, 2, 1, 0, 4, 1, p + 20,     # TCB 0 -> TCB 1
                           0, p + 18, 1, 1, 0, 1, 1, p + 28,                      # TCB 1
                           5, 21, 40]):
        mem[p + i] = x & 0xFFFFFFFF
    return mem


n5.Layout.words = _words_prb
build, check, Layout, REGIONS3, RIG_BOUNDS, nf = n5.build, n5.check, n5.Layout, n5.REGIONS3, n5.RIG_BOUNDS, n5.nf
n5.nm.ChainDma = n5.GatherDma   # (sim) the probe DMA is a tap-list chain
