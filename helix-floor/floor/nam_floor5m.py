#!/usr/bin/env python3
"""METER variant of nam_floor5 (a test image only): every NAM block plays, instead of its output,
numbers about this call, each an integer n < 32768 played as n / 32768 (exact through 16-bit USB
capture), four samples each:

  samples 0..3    this call's cycles / 8 (EMUCLK, from the call's start to the meter)
  samples 4..7    -(the instance's PM block I8 / 64)          (v3; v2: the call's wait polls)
  samples 8..11   (the instance's DM block I0 - 0x80000) / 16
  samples 12..15  -(the instance's SDRAM block / 512)          (v3; v2: I8's, clipped in a split)

`floor/meter_read.py --v2` finds the frame and prints each field.

v2 on the Floor: plain path I0 0x9a310 / I8 0xe5de0, 276 polls; split path I0 0xa4ff0 (outside
heap a!) / I8 beyond 0x100000, 391 polls, 77K cycles. v3 shows I8 and the SDRAM block in full.

v1 (2026-11-03, one value: cycles x 2^-18 with the sign flipping each call) showed one NAM at
~55K cycles in a plain path and ~78K in a split path (one NAM, or two). v2 asks why: waits
(DMA) or compute, and where the Floor put the instance's memory.

One NAM slot per DSP (SLOTS = 1: the room for the meter and the poll counts); the report words
R_DMAC / R_ICEP / R_CLAIMS go. No KernelCheck on a meter image (its output is the meter).

usage: as nam_floor5 (NAM_KERNEL=nam_floor5m; build_floor2.py --meter)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor5 as n5  # noqa: E402
from nam_floor5 import *  # noqa: E402,F401,F403

PATCHES_M = [
    ("// METER_ENTRY\n", """    R0 = EMUCLK;                        // (meter) this call's start
    DM(DCNT) = R0;
"""),
    ("""x_nomsk:
""", """x_nomsk:
    R0 = EMUCLK;                        // (meter) cycles / 8, -PM block, DM block, -SDRAM block
    R1 = DM(DCNT);
    R0 = R0 - R1;
    R0 = LSHIFT R0 BY -3;
    R1 = DM(SAVE + 46);                 // (v3) the caller's I8 / 64
    R1 = LSHIFT R1 BY -6;
    R1 = -R1;
    R2 = DM(SAVE + 31);                 // (the caller's I0: the instance's DM block)
    R3 = 0x80000;
    R2 = R2 - R3;
    R2 = LSHIFT R2 BY -4;
    R3 = DM(G_SDR);                     // (v3) the instance's SDRAM block / 512
    R3 = LSHIFT R3 BY -9;
    R3 = -R3;
    F4 = 3.0517578125e-05;              // 1 / 32768
    F0 = FLOAT R0;
    F0 = F0 * F4;
    F1 = FLOAT R1;
    F1 = F1 * F4;
    F2 = FLOAT R2;
    F2 = F2 * F4;
    F3 = FLOAT R3;
    F3 = F3 * F4;
    I11 = B11;
    LCNTR = 4, DO mt_0 UNTIL LCE;
mt_0: PM(I11, M9) = R0;
    LCNTR = 4, DO mt_1 UNTIL LCE;
mt_1: PM(I11, M9) = R1;
    LCNTR = 4, DO mt_2 UNTIL LCE;
mt_2: PM(I11, M9) = R2;
    LCNTR = 4, DO mt_3 UNTIL LCE;
mt_3: PM(I11, M9) = R3;
"""),
    ("""    DM(REP + R_DMAC) = R0;
""", ""),
    ("""    DM(REP + R_ICEP) = R0;
""", ""),
    ("""    R0 = DM(REP + R_CLAIMS);
    R0 = R0 + 1;
    DM(REP + R_CLAIMS) = R0;
""", ""),
]

_kernel_src = n5.kernel_src


def kernel_src():
    src = _kernel_src()
    for a, b in PATCHES_M:
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    return src


n5.kernel_src = kernel_src
n5.SLOTS = 1
n5.KEEP_POLLS = True
build, check, Layout, REGIONS3, RIG_BOUNDS, nf = n5.build, n5.check, n5.Layout, n5.REGIONS3, n5.RIG_BOUNDS, n5.nf
