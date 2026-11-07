#!/usr/bin/env python3
"""METER variant of nam_floor5 (a test image only): every NAM block plays, instead of its output,
numbers about this call, each an integer n < 32768 played as n / 32768 (exact through 16-bit USB
capture). v4 (2026-11-04): eight fields of two samples, signs + - + - + - + -:

  0  +16384 (0.5): calibration. Any gain between the block and USB 1 scales every field; the
     reader divides by field 0 / 16384. (v1..v3 had none: see below.)
  1  -(cycles / 8)            EMUCLK from the call's start to the meter
  2  +(I0 - 0x80000) / 16     the caller's DM block
  3  -(I8 / 64)               the caller's PM block
  4  +DM(3, I0) & 0x7FFF      (the stock instance word, 1 in the sim's model of it)
  5  -(DM(7, I0) >> 17)       the Model knob word's top bits (a float: sign, exponent, mantissa top)
  6  +DM(7, I0) & 0x7FFF      its low bits (an int index)
  7  -(P_SLOT*8 + DMok*4 + PMok*2 + S_INIT)  DMok/PMok = m_init's bounds guard on I0/I8

`floor/meter_read.py --v4` finds the frame (field 0) and prints each field.

Why v4: v1..v3 read 41% more in a split path for every field at once (cycles 77.1K vs 54.6K,
polls 391 vs 276, I0 field 9471 vs 6705: all x1.41 = +3 dB), the pattern of a gain on the meter
tone (Split Y / Merge balance), not of a slower block. Field 0 settles it on the unit.

Earlier versions (v3 = samples 0..3 cycles/8, 4..7 -(I8/64), 8..11 (I0-0x80000)/16, 12..15
-(SDRAM block/512)):

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
    R0 = EMUCLK;                        // (meter v4) eight 2-sample fields, signs + - + - ...
    R1 = DM(DCNT);
    R1 = R0 - R1;
    R1 = LSHIFT R1 BY -3;
    R1 = -R1;                           // 1: -cycles / 8
    R0 = 16384;                         // 0: calibration, 0.5 (any gain after the block shows here)
    R2 = DM(SAVE + 31);                 // 2: (the caller's I0 - 0x80000) / 16
    I4 = R2;
    R3 = 0x80000;
    R2 = R2 - R3;
    R2 = LSHIFT R2 BY -4;
    R3 = DM(SAVE + 46);                 // 3: -(the caller's I8 / 64)
    R3 = LSHIFT R3 BY -6;
    R3 = -R3;
    R8 = 0x7FFF;
    R4 = DM(3, I4);                     // 4: DM(3, I0), low 15 bits (stock blocks: 1)
    R4 = R4 AND R8;
    R5 = DM(7, I4);                     // 5: -(DM(7, I0) >> 17)  (a float's sign, exponent, top)
    R6 = R5 AND R8;                     // 6: DM(7, I0), low 15 bits (the Model knob as an int)
    R5 = LSHIFT R5 BY -17;
    R5 = -R5;
    R7 = DM(P_SLOT, I4);                // 7: -(P_SLOT x 8 + DM guard x 4 + PM guard x 2 + S_INIT)
    R9 = 7;
    R7 = R7 AND R9;
    R7 = LSHIFT R7 BY 3;
    R11 = 4;
    R9 = I4;
    R10 = INST_DM_LO;
    R9 = R9 - R10;
    R10 = INST_DM_SPAN;
    COMPU(R9, R10);
    IF LE R7 = R7 + R11;
    R11 = 2;
    R9 = DM(SAVE + 46);
    R10 = INST_PM_LO;
    R9 = R9 - R10;
    R10 = INST_PM_SPAN;
    COMPU(R9, R10);
    IF LE R7 = R7 + R11;
    R9 = DM(SLOTTAB);
    I5 = R9;
    R9 = DM(S_INIT, I5);
    R11 = 1;
    R9 = R9 AND R11;
    R7 = R7 + R9;
    R7 = -R7;
    F8 = 3.0517578125e-05;              // 1 / 32768
    I11 = B11;
    F0 = FLOAT R0;
    F0 = F0 * F8;
    PM(I11, M9) = R0;
    PM(I11, M9) = R0;
    F1 = FLOAT R1;
    F1 = F1 * F8;
    PM(I11, M9) = R1;
    PM(I11, M9) = R1;
    F2 = FLOAT R2;
    F2 = F2 * F8;
    PM(I11, M9) = R2;
    PM(I11, M9) = R2;
    F3 = FLOAT R3;
    F3 = F3 * F8;
    PM(I11, M9) = R3;
    PM(I11, M9) = R3;
    F4 = FLOAT R4;
    F4 = F4 * F8;
    PM(I11, M9) = R4;
    PM(I11, M9) = R4;
    F5 = FLOAT R5;
    F5 = F5 * F8;
    PM(I11, M9) = R5;
    PM(I11, M9) = R5;
    F6 = FLOAT R6;
    F6 = F6 * F8;
    PM(I11, M9) = R6;
    PM(I11, M9) = R6;
    F7 = FLOAT R7;
    F7 = F7 * F8;
    PM(I11, M9) = R7;
    PM(I11, M9) = R7;
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
    pats = list(PATCHES_M)
    if n5.P9_MODE == "nomask":            # (no x_nomsk: the meter goes after the exit's idle wait)
        body = pats[1][1]
        assert body.startswith("x_nomsk:\n")
        pats[1] = ("x_idle:\n    R0 = DM(SAVE + 1);", "x_idle:\n" + body[len("x_nomsk:\n"):] + "    R0 = DM(SAVE + 1);")
    for a, b in pats:
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    return src


n5.kernel_src = kernel_src
n5.SLOTS = 1
n5.KEEP_POLLS = True
build, check, Layout, REGIONS3, RIG_BOUNDS, nf = n5.build, n5.check, n5.Layout, n5.REGIONS3, n5.RIG_BOUNDS, n5.nf
