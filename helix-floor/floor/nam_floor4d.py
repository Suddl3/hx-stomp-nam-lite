#!/usr/bin/env python3
"""DIAGNOSTIC variant of nam_floor4 (a test image only): where the kernel would play silence it
plays a beep code instead, so a listener can tell which path the block took on the Floor.

The pattern repeats: N short beeps (1.5 kHz, ~43 ms each, ~43 ms apart), then a pause of ~260 ms.
After a failure the block is silent for BACKOFF_N calls; those calls beep the failure's code (DCAUSE).
  1  channel 0 busy, or its interrupt (P9I) unmasked   (upstream's check: someone else uses ch0)
  2  channel 1 busy
  3  channel 1's interrupt (P13I) unmasked
  4  a DMA failed while loading the model (channel 0)
  5  no model: Model knob out of 1..128, or that IR slot is empty / not a NAM capture
  6  a channel 0 transfer (far taps / write-back) timed out during the layers
  7  a channel 1 transfer (a layer's weights, or the head's) timed out
  8  the instance's memory is not where the kernel expects it (the bounds guard)
  9  ran the whole model, but its output is exactly 0.0
  10 failed with no code set
No beep and silence: the kernel is not called at all. Dry guitar: no slot / no SDRAM block (pass-through).

Usage as nam_floor4 (NAM_KERNEL=nam_floor4d); KernelCheck does not apply (beeps where it wants silence).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor4 as n4  # noqa: E402
from nam_floor4 import *  # noqa: E402,F401,F403

DIAG_PATCHES = [
    ("""    DM(SAVE + 1) = R0;
""", """    DM(SAVE + 1) = R0;
    R0 = 0;                             // (diag) no code yet this call
    DM(DIAG) = R0;
"""),
    ("""    DM(S_INIT, I6) = R0;
    JUMP m_silent;
m_nobo:""", """    DM(S_INIT, I6) = R0;
    R0 = DM(DCAUSE);                    // (diag) the backoff beeps the failure that started it
    DM(DIAG) = R0;
    JUMP m_silent;
m_nobo:"""),
    ("""m_fail:
    R0 = 0;
    DM(S_INIT, I6) = R0;""", """m_fail:
    R0 = DM(DIAG);                      // (diag) remember why (10: no code set)
    R1 = 10;
    R0 = PASS R0;
    IF EQ R0 = PASS R1;
    DM(DCAUSE) = R0;
    R0 = 0;
    DM(S_INIT, I6) = R0;"""),
    ("""    R0 = 0;                             // never came: channel 1 off, the block fails""",
     """    R0 = 7;                             // (diag) a channel 1 fetch timed out
    DM(DIAG) = R0;
    R0 = 0;                             // never came: channel 1 off, the block fails"""),
    ("""    R12 = 1;                            // never came: the block fails (silence)""",
     """    R12 = 7;                            // (diag) the head's channel 1 fetch timed out
    DM(DIAG) = R12;
    R12 = 1;                            // never came: the block fails (silence)"""),
    ("""    R0 = DM(DMAC1);
    R1 = BUSYM;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP1IMSK;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;""", """    R0 = DM(DMAC1);
    R1 = BUSYM;
    R1 = R0 AND R1;
    IF NE JUMP m_busy2;
    R0 = LRPTL;
    R1 = EP1IMSK;
    R1 = R0 AND R1;
    IF NE JUMP m_busy3;"""),
    ("""m_busy:
    R0 = DM(REP + R_SKIPS);
    R0 = R0 + 1;
    DM(REP + R_SKIPS) = R0;
    JUMP m_fail;""", """m_busy:
    R0 = 1;
    DM(DIAG) = R0;
m_busyc:
    R0 = DM(REP + R_SKIPS);
    R0 = R0 + 1;
    DM(REP + R_SKIPS) = R0;
    JUMP m_fail;
m_busy2:
    R0 = 2;
    DM(DIAG) = R0;
    JUMP m_busyc;
m_busy3:
    R0 = 3;
    DM(DIAG) = R0;
    JUMP m_busyc;"""),
    ("""    R0 = DM(S_INIT, I6);
    R0 = PASS R0;
    IF EQ JUMP m_silent;

m_ready:""", """    R0 = DM(S_INIT, I6);
    R0 = PASS R0;
    IF NE JUMP m_ready;
    R0 = 8;
    DM(DIAG) = R0;
    JUMP m_silent;

m_ready:"""),
    ("""n_none:
    R0 = DM(S_SIG, I6);""", """n_none:
    R0 = 5;
    DM(DIAG) = R0;
    R0 = DM(S_SIG, I6);"""),
    ("""    CALL ld_model;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP m_fail;
    JUMP n_zero;""", """    CALL ld_model;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF EQ JUMP n_zero;
    R0 = 4;                             // (diag) loading the model failed
    DM(DIAG) = R0;
    JUMP m_fail;"""),
    ("""    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP m_fail;
    R0 = DM(S_T, I6);""", """    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF EQ JUMP n_dok;
    R0 = DM(DIAG);                      // (diag) 7 (channel 1) stands; else channel 0: 6
    R0 = PASS R0;
    IF NE JUMP m_fail;
    R0 = 6;
    DM(DIAG) = R0;
    JUMP m_fail;
n_dok:
    R0 = DM(S_T, I6);"""),
    ("""n_back:
// METER_EXIT
""", """n_back:
    R0 = DM(DIAG);                      // (diag) a code: its beeps instead of the output
    R0 = PASS R0;
    IF NE JUMP dg_beep;
    I11 = B11;                          // no code: an output of exactly 0.0 is code 9
    R2 = 0;
    LCNTR = 16, DO dg_z UNTIL LCE;
      R1 = PM(I11, M9);
      R1 = BCLR R1 BY 31;
dg_z: R2 = R2 OR R1;
    R2 = PASS R2;
    IF NE JUMP dg_end;
    R0 = 9;
dg_beep:
    R1 = DM(DCNT);                      // calls into the pattern: (2N + 6) units of 128 calls
    R1 = R1 + 1;
    R2 = R0 + R0;
    R3 = 6;
    R2 = R2 + R3;
    R2 = LSHIFT R2 BY 7;
    COMP(R1, R2);
    IF GE R1 = R1 - R2;
    DM(DCNT) = R1;
    R3 = LSHIFT R1 BY -7;               // this unit: a beep when even and < 2N
    R2 = R0 + R0;
    F8 = 0.0;
    COMP(R3, R2);
    IF GE JUMP dg_w;
    R4 = 1;
    R4 = R3 AND R4;
    IF NE JUMP dg_w;
    F8 = 0.25;                          // a 1.5 kHz square: the sign flips every call
    R4 = 1;
    R4 = R1 AND R4;
    IF NE F8 = -F8;
dg_w:
    I11 = B11;
    LCNTR = 16, DO dg_ww UNTIL LCE;
dg_ww: PM(I11, M9) = R8;
dg_end:
// METER_EXIT
"""),
]

_kernel_src = n4.kernel_src


def kernel_src():
    src = _kernel_src()
    for a, b in DIAG_PATCHES:
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    return src


n4.kernel_src = kernel_src          # (n4.build / code_sizes look it up at call time)
build, check, Layout, REGIONS3, RIG_BOUNDS, nf = n4.build, n4.check, n4.Layout, n4.REGIONS3, n4.RIG_BOUNDS, n4.nf
