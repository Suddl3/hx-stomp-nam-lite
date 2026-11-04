#!/usr/bin/env python3
"""DIAGNOSTIC variant of nam_floor5 (test image only): the beep codes of nam_floor4d (see its
docstring) where they apply to the channel 0 design. Channel 1 codes (2, 3, 7) cannot occur.
v3: the beeps repeat the FIRST failure since boot; 1 = channel 0 busy (DMAC0), 11 = its interrupt
(P9I) unmasked; the channel is waited idle after it is switched off.
v4 (v3 beeped 11): P9_SHARE, P9I masked for each call instead of failing (no code 11).

One NAM slot per DSP (SLOTS = 1): the beep code is ~100 words more than test2c has spare, and the
second slot frees 190. A second NAM block on the same DSP finds no slot and passes the dry signal."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor5 as n5  # noqa: E402
from nam_floor5 import *  # noqa: E402,F401,F403
import nam_floor4d  # noqa: E402

_kernel_src = n5.kernel_src

# v3 (after the first Floor run beeped 1): the beeps name the FIRST failure since boot (a later
# "channel busy" may only be the aftermath of an earlier abort), code 1 split from 11 (P9I
# unmasked). (Its idle waits after the channel is switched off are now nam_floor5's SHARE_PATCHES.)
PATCHES_V3 = [
    ("""    IF EQ JUMP m_idle;
m_busy:
    R0 = 1;""", """    IF EQ JUMP m_idle;
    R0 = 11;                            // (diag) channel 0's interrupt unmasked
    DM(DIAG) = R0;
    JUMP m_busyc;
m_busy:
    R0 = 1;"""),
    ("""    IF EQ R0 = PASS R1;
    DM(DCAUSE) = R0;""", """    IF EQ R0 = PASS R1;
    R1 = DM(DCAUSE);                    // (diag) only the first failure since boot
    R1 = PASS R1;
    IF NE JUMP m_fdc;
    DM(DCAUSE) = R0;
m_fdc:"""),
]


# Slower beeps, easier to count by ear: units of 512 calls (~171 ms), a beep every 3rd unit
# (~0.5 s apart), 8 silent units (~1.4 s) after the last one.
SLOW_BEEPS = ("""    R2 = R0 + R0;
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
    IF NE JUMP dg_w;""", """    R2 = R0 + R0;                       // (3N + 6) units of 512 calls
    R2 = R2 + R0;
    R3 = 6;
    R2 = R2 + R3;
    R2 = LSHIFT R2 BY 9;
    COMP(R1, R2);
    IF GE R1 = R1 - R2;
    DM(DCNT) = R1;
    R3 = LSHIFT R1 BY -9;               // this unit: a beep when a multiple of 3 and < 3N
    R2 = R0 + R0;
    R2 = R2 + R0;
    F8 = 0.0;
    COMP(R3, R2);
    IF GE JUMP dg_w;
    R4 = 3;
dg_m3: COMP(R3, R4);
    IF LT JUMP dg_m3d;
    R3 = R3 - R4;
    JUMP dg_m3;
dg_m3d: R3 = PASS R3;
    IF NE JUMP dg_w;""")


def kernel_src():
    src = _kernel_src()
    used = 0
    for a, b in nam_floor4d.DIAG_PATCHES:
        if src.count(a) == 1:
            src = src.replace(a, b)
            used += 1
    assert used >= 8, f"only {used} diag patches applied"
    for k, (a, b) in enumerate(PATCHES_V3):
        if k == 0 and n5.P9_SHARE:      # (v4: an unmasked P9I is masked for the call, no code 11)
            continue
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    assert src.count(SLOW_BEEPS[0]) == 1
    return src.replace(*SLOW_BEEPS)


n5.kernel_src = kernel_src
n5.SLOTS = 1
n5.P9_SHARE = True                  # v4: after v3 beeped 11 on the Floor
build, check, Layout, REGIONS3, RIG_BOUNDS, nf = n5.build, n5.check, n5.Layout, n5.REGIONS3, n5.RIG_BOUNDS, n5.nf
