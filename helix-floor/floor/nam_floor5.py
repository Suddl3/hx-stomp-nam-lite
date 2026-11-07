#!/usr/bin/env python3
"""NAM kernel, two blocks per Floor DSP, weights streamed on EP DMA channel 1 (DESIGN_2NAM.md).

nam_floor2.py (phase 1) put the weight fetches in channel 0's job queue: bit-exact, but layers
waited behind the far-tap jobs (steady ~38K instructions against ~28K of compute). Here the far
taps and write-backs keep channel 0 and its queue exactly as upstream, and the weights have
channel 1 to themselves: at each layer's start the kernel waits for that layer's weights (its
buffer's flag), then starts the next layer's fetch into the other buffer, so a fetch always runs
under one layer's compute.

Channel 1's registers (DMAC1 0x180C, EIEP1..CPEP1 0x1828..0x182E) follow channel 0's pattern
(0x180B, 0x1820..0x1826); TO CONFIRM against the ADSP-2146x HRM before a hardware build, and
that the stock DSP program never uses channel 1 (no 32-bit references to either channel's
registers in Entry 2, the same evidence as for channel 0).

Memory beyond the test2c regions spills into RX (simulator only); the report shows how much.

usage: nam_floor5.py [--check] [--bench]
"""
import inspect
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nam_floor as nf  # noqa: E402
import nam_floor2 as n2  # noqa: E402
import nam_floor3 as n3  # noqa: E402
from nam_floor import nm, nam_lite, nam_pack, sasm, C, NL, KERNEL, DILATION, FAR_D  # noqa: E402

REGIONS3 = n2.REGIONS2
HDR, SIL = n2.HDR, n2.SIL
LB_N = 153                          # the largest layer's weights (k = 15), exactly
EP1IMSK = 0x20000                   # LIRPTL P13IMSK (P6IMSK..P15IMSK = bits 10..19; P9IMSK = 0x2000 as upstream)
DMAC1, EIEP1, EMEP1, ECEP1, IIEP1, IMEP1, ICEP1, CPEP1 = 0x180C, 0x1830, 0x1831, 0x1832, 0x1833, 0x1834, 0x1835, 0x1836   # ADSP-214xx HRM rev 1.1, register table
# A layer's row now comes fetched with its weights: layer buffer b = [flag][row T_SIZE3][weights].
# Its last four words say what to fetch next (offset in SDRAM, count, buffer, the row in DDR2).
T3 = dict(nm.T, T_NXO=18, T_NXN=19, T_NXB=20, T_NXR=21)
T_SIZE3 = 22
FT_SIZE = 12                        # the far layers' rows on chip for pump (fields 0..11)
HEAD_FETCH = True                   # the head's 49 weights fetched on channel 1 (slot keeps rechannel + scale)
SIL_SDRAM = True                    # the silence state in SDRAM after the weights, not in the slot
WB = "group"                        # write-back: "group" (one shared 4-layer buffer) or "sb" (from SB)
SLOTS = 2                           # NAM blocks per DSP (nam_floor5d: 1, its beep code needs the room)
lw = n2.lw

PATCHES3 = [
    # each layer waits for its buffer (row + weights, fetched by a type 2 job on channel 0)
    ("""    I4 = TABLE;
    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;""", """    I4 = LBROW0;
    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;
      CALL lwait;
      R0 = DM(DMA_FAIL);                // a transfer failed: this layer's row and weights may
      R0 = PASS R0;                     // never have come, so the rest of the layers are skipped
      IF NE JUMP n_lskip;               // (their loop counts and pointers come from the row)"""),
    # every layer computed counts (a fetch waits for its buffer's layer before last)
    ("""      IF NE R0 = R0 + R1;
      DM(EVENTS) = R0;
n_layer:""", """      R0 = R0 + R1;
      DM(EVENTS) = R0;
n_layer:"""),
    # the next layer's row is in the other buffer
    ("""n_layer: MODIFY(I4, T_SIZE);""", """n_lskip:
      R0 = LBSUM;
      R1 = I4;
      R0 = R0 - R1;
n_layer: I4 = R0;
    R9 = POLLMAX;                       // the head's weights (into LB1 after layer 21): wait,
n_hw0: R0 = DM(HFLAG);                  // moving the queue on
    R1 = MAGIC;
    COMP(R0, R1);
    IF EQ JUMP n_hw1;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP n_hw1;
    CALL pump;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP n_hw0;
    CALL dma_abort;
n_hw1:
    CALL pump;"""),
    # a call's start: both buffers' flags clear (a stale MAGIC would pass a wait)
    ("""    // ---- the DMA jobs of this block, then the model
    R0 = 0;
    DM(J_NEXT) = R0;""", """    // ---- the DMA jobs of this block, then the model
    R0 = 0;
    DM(LBF0) = R0;
    DM(LBF1) = R0;
    DM(J_NEXT) = R0;"""),
    # job type 2: a layer's row (DDR2) and weights (the instance's SDRAM) into its buffer
    ("""    R0 = DM(J_TYPE, I5);
    R0 = PASS R0;
    IF NE JUMP p_w;""", """    R0 = DM(J_TYPE, I5);
    R0 = R0 - 1;
    IF EQ JUMP p_w;
    IF GT JUMP p_f;"""),
    ("""    DM(CPEP0) = R1;
    RTS;

// Wait (bounded) for this far layer's taps""", """    DM(CPEP0) = R1;
    RTS;
p_f:
    I0 = DM(J_CHAIN, I5);
    R1 = DM(J_ROW, I5);                 // TCB 0: the layer's row, from DDR2
    DM(TCB_EI, I0) = R1;
    R1 = DM(G_SDR);                     // TCB 1: its weights, from the instance's SDRAM
    R2 = DM(J_N, I5);
    R1 = R1 + R2;
    DM(TCB_EI + 6, I0) = R1;
    R1 = DM(7, I5);
    DM(TCB_IC + 6, I0) = R1;
    R1 = DM(G_SDR);                     // TCB 2, the sentinel: MAGIC from SENT into the flag
    R2 = SENT_OFF;
    R1 = R1 + R2;
    DM(TCB_EI + 12, I0) = R1;
    I0 = DM(J_FLAG, I5);
    R1 = 0;
    DM(0, I0) = R1;
    R1 = I0;
    DM(J_CHKADR) = R1;
    R1 = MAGIC;
    DM(J_CHKVAL) = R1;
    R0 = 0;                             // external -> internal
    JUMP p_go;

// This layer's buffer (its flag, just before it, MAGIC once its fetch ended), moving the
// queue on while waiting; then pump notes the job's end and the flag is cleared for the
// buffer's next fetch. Uses R0, R1, R9 (and pump's).
lwait:
    R0 = DM(DMA_FAIL);                  // after a failure: no waits
    R0 = PASS R0;
    IF NE RTS;
    R9 = POLLMAX;
lw_l: R1 = MAGIC;
    R0 = DM(-1, I4);
    COMP(R0, R1);
    IF EQ JUMP lw_ok;
    CALL pump;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE RTS;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP lw_l;
    JUMP dma_abort;
lw_ok:
    CALL pump;
    R0 = 0;
    DM(-1, I4) = R0;
    RTS;

// Wait (bounded) for this far layer's taps"""),
    # a write-back's far layers: their FTAB rows are FT_SIZE apart (no FARTAB)
    ("""      R1 = DM(I1, 1);
      I3 = R1;
      R6 = DM(T_STRIDE, I3);""", """      I3 = I1;
      MODIFY(I1, FT_SIZE);
      R6 = DM(T_STRIDE, I3);"""),
] + [p for p in n2.PATCHES2 if "where they go" in p[0]]

# a load: the header into the slot (and, without SIL_SDRAM, the silence state after it)
LD_COPY = ("""    IF LT JUMP ld_chunk;
    R0 = 0;
    DM(DMAC0) = R0;""", """    IF LT JUMP ld_chunk;
    R0 = 0;
    DM(DMAC0) = R0;
    R0 = DM(G_SDR);
    R1 = W_OFF;
    R0 = R0 + R1;
    I5 = R0;
    R0 = I6;
    R1 = S_STREAM;
    R0 = R0 + R1;
    I3 = R0;
    LCNTR = HDR_RECH, DO ld_h UNTIL LCE;
      R1 = DM(I5, 1);
ld_h: DM(I3, 1) = R1;
    R0 = DM(G_SDR);                     // (the scale, stream word 52, after them)
    R1 = W_OFF + 52;
    R0 = R0 + R1;
    I5 = R0;
    R1 = DM(0, I5);
    DM(I3, 1) = R1;""")
LD_SIL = """    R0 = N_WEIGHTS - HDR;
    M2 = R0;
    MODIFY(I5, M2);
    LCNTR = SIL_N, DO ld_s UNTIL LCE;
      R1 = DM(I5, 1);
ld_s: DM(I3, 1) = R1;"""
SIL_PATCHES = [
    # the ring clear at a load and the far rings' patch read the silence state from SDRAM
    ("""    R3 = S_STREAM + ST_SIL;
    R3 = R3 + R11;""", """    R3 = DM(G_SDR);
    R1 = W_OFF + N_WEIGHTS;
    R3 = R3 + R1;"""),
    ("""    R2 = DM(T_SIL, I4);
    R6 = I6;
    R2 = R2 + R6;""", """    R2 = DM(T_SIL, I4);
    R6 = DM(G_SDR);
    R2 = R2 + R6;"""),
]


SB_WB = ("""fc_l:   DM(I0, M7) = F0, PM(I8, M10) = F0;""", """fc_l:   DM(I0, M7) = F0;""")


def patch_head(src):
    """The head's weights: wait for their fetch into WBUF (= LB1) instead of copying them there."""
    a = src.index("    R7 = S_STREAM + ST_HEAD;")
    b = src.index("    R7 = WBUF;\n", a)
    return src[:a] + """    R7 = POLLMAX;                       // the head's weights, fetched into WBUF during layer 22
n_hw: R12 = DM(HFLAG);
    R13 = MAGIC;
    COMP(R12, R13);
    IF EQ JUMP n_hgo;
    R7 = R7 - 1;
    IF NE JUMP n_hw;
    R12 = 1;                            // never came: the block fails (silence)
    DM(DMA_FAIL) = R12;
n_hgo:
""" + src[b:]


def kernel_src():
    src = nf.kernel_src()
    if WB == "sb":                       # the newest taps stay in SB (tap K-1); the write-back reads them there
        assert src.count(SB_WB[0]) == 1
        src = src.replace(*SB_WB)
    pats = PATCHES3 + [(LD_COPY[0], LD_COPY[1] + ("" if SIL_SDRAM else "\n" + LD_SIL))]
    pats += SIL_PATCHES if SIL_SDRAM else []
    for a, b in pats:
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    a = src.index("      R15 = DM(T_WT, I4);               // this layer's weights")
    b = src.index("n_wfar:\n", a)
    src = src[:a] + """      R0 = I4;                          // this layer's weights: after its row in the buffer
      R1 = T_SIZE;
      R0 = R0 + R1;
      I9 = R0;
      M8 = DM(T_NW, I4);
""" + src[b:]
    if P9_MODE == "nomask":
        for a, b in NOMASK_PATCHES:
            assert src.count(a) == 1, a[:70]
            src = src.replace(a, b)
    elif P9_SHARE:
        for a, b in SHARE_PATCHES:
            assert src.count(a) == 1, a[:70]
            src = src.replace(a, b)
        if P9_KEEP_LATCH:
            assert src.count(LATCH_CLR) == 1
            src = src.replace(LATCH_CLR, "")
    src = patch_head(src) if HEAD_FETCH else src
    if PM_RECHECK:
        for a, b in (PMB_PATCH, GUARD_PATCH):
            assert src.count(a) == 1, a[:70]
            src = src.replace(a, b)
    if GATHER:
        for a, b in (G_TAP, G_GO) + ((G_W,) if GATHER_W else ()):
            assert src.count(a) == 1, a[:70]
            src = src.replace(a, b)
    if MID_PUMP:
        for a, b in (MP_LOOP, MP_END):
            assert src.count(a) == 1, a[:70]
            src = src.replace(a, b)
        a = "\nlwait:\n"
        assert src.count(a) == 1
        src = src.replace(a, MP_SUB + a)
    if P9_SHARE and not KEEP_POLLS:      # room for it: the wait-poll count (REP R_POLLS /
        n = src.count(POLL_INC)          # R_MAXPOLLS) only fed the simulator's bench and the meters
        src = src.replace(POLL_INC, "")
        assert n == 4 and src.count(POLL_MAX) == 1
        src = src.replace(POLL_MAX, "")
        assert src.count(POLL_CLR) == 1
        src = src.replace(POLL_CLR, "")
    return src


# Safety (2026-11-04): the near rings' pointers (S_RP) and the bounds guard are m_init's, from
# I0 and I8. A new I0 already restarts the slot (I0 is the owner key), but a new I8 with the same
# I0 would leave the PM rings writing into another block's memory. So every call compares I8
# with the slot's S_PMB (state word 71, free: S_LW is 48..70, the stream starts at 72); a change
# restarts the slot, and m_init's guard then accepts the new blocks or the block plays silence.
PM_RECHECK = True
S_PMB = 71
PMB_PATCH = ("""m_slot:
    DM(S_LAST, I6) = R12;
""", """m_slot:
    DM(S_LAST, I6) = R12;
    R0 = DM(SAVE + 46);                 // the instance's PM block (I8) changed: start again
    R1 = DM(S_PMB, I6);                 // (m_init's guard and ring pointers come from I0, I8)
    COMP(R0, R1);
    IF EQ JUMP m_pmok;
    DM(S_PMB, I6) = R0;
    R1 = 0;
    DM(S_INIT, I6) = R1;
m_pmok:
""")
# Room for it: m_init's bounds guard as two unsigned range checks (I0 - LO <= HI - NEED - LO,
# the same for I8): the same accept/reject rule as nam_floor's four signed compares, 6 fewer.
GUARD_PATCH = ("""m_init:
    R0 = I0;
    R1 = INST_DM_LO;
    COMP(R0, R1);
    IF LT RTS;
    R1 = INST_DM_NEED;
    R0 = R0 + R1;
    R1 = INST_DM_HI;
    COMP(R0, R1);
    IF GT RTS;
    R0 = DM(SAVE + 46);
    R1 = INST_PM_LO;
    COMP(R0, R1);
    IF LT RTS;
    R1 = INST_PM_NEED;
    R0 = R0 + R1;
    R1 = INST_PM_HI;
    COMP(R0, R1);
    IF GT RTS;
""", """m_init:
    R0 = I0;                            // the DM block: I0 - LO <= HI - NEED - LO, unsigned
    R1 = INST_DM_LO;                    // (below LO wraps to a huge value: out too)
    R0 = R0 - R1;
    R1 = INST_DM_SPAN;
    COMPU(R0, R1);
    IF GT RTS;
    R0 = DM(SAVE + 46);                 // the PM block (I8 at entry), the same
    R1 = INST_PM_LO;
    R0 = R0 - R1;
    R1 = INST_PM_SPAN;
    COMPU(R0, R1);
    IF GT RTS;
""")


POLL_INC = """    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
"""
POLL_MAX = """    R0 = DM(REP + R_POLLS);
    R1 = DM(REP + R_MAXPOLLS);
    R1 = MAX(R0, R1);
    DM(REP + R_MAXPOLLS) = R1;
"""
POLL_CLR = """    DM(REP + R_POLLS) = R0;
"""


# The Floor's stock DSP program unmasks channel 0's interrupt (P9I; the Stomp's stays masked):
# diag v3 on the Floor beeped 11 with the channel itself idle. With P9_SHARE the kernel, finding
# the channel idle, masks P9I for the call (so its own chain ends do not run Line 6's handler),
# then waits the channel idle, clears the P9I latch unless it was already set at entry (Line 6's
# own completion, still due), and unmasks again on every way out.
P9_SHARE = True                     # (hardware: the Floor needs it, diag v4 played)
KEEP_POLLS = False                  # (nam_floor5m: the meter reports the wait polls)
EP0LAT = 0x8                        # LIRPTL P9I latch (P6I..P15I = bits 0..9)
# 2026-11-06 freeze suspect: the exit clears the P9I latch unless set at entry. A Line 6 channel-0
# completion during our call (their transfer started by a higher-priority ISR) would be wiped, and
# their handler never runs: their side waits forever (UI freezes, audio plays on). P9_KEEP_LATCH
# leaves the latch alone: Line 6's handler then runs once after each NAM call (for our own chain
# ends too, a spurious completion it has to tolerate). Test image NAM2_KEEPLATCH.
P9_KEEP_LATCH = os.environ.get("NAM_KEEP_LATCH") == "1"
LATCH_CLR = f"""    R1 = {EP0LAT:#x};
    R1 = R0 AND R1;
    IF NE JUMP x_lat;
    BIT CLR LRPTL {EP0LAT:#x};                 // (our own chain ends' latch)
x_lat:
"""
SHARE_PATCHES = [
    ("""    DM(SAVE + 1) = R0;
""", """    DM(SAVE + 1) = R0;
    R0 = 0;                             // (P9I not masked by this call yet)
    DM(MSKD) = R0;
"""),
    ("""    R0 = LRPTL;
    R1 = EP0IMSK;
    R1 = R0 AND R1;
    IF EQ JUMP m_idle;
m_busy:""", f"""    R0 = LRPTL;
    R1 = EP0IMSK;
    R1 = R0 AND R1;
    IF EQ JUMP m_idle;
    R1 = {nm.EP0IMSK | EP0LAT:#x};                    // unmasked (the Floor): masked for this call,
    R1 = R0 AND R1;                     // its mask and latch bits kept for the way out
    DM(MSKD) = R1;
    BIT CLR LRPTL EP0IMSK;
    JUMP m_idle;
m_busy:"""),
    ("""// METER_EXIT
    R0 = DM(SAVE + 1);""", f"""// METER_EXIT
    R0 = DM(MSKD);                      // P9I masked by this call: the channel idle, then back
    R0 = PASS R0;
    IF EQ JUMP x_nomsk;
    R2 = 1000;
x_w: R1 = DM(DMAC0);
    R3 = BUSYM;
    R1 = R1 AND R3;
    IF EQ JUMP x_idle;
    R2 = R2 - 1;
    IF NE JUMP x_w;
x_idle:
    R1 = {EP0LAT:#x};
    R1 = R0 AND R1;
    IF NE JUMP x_lat;
    BIT CLR LRPTL {EP0LAT:#x};                 // (our own chain ends' latch)
x_lat:
    BIT SET LRPTL EP0IMSK;
x_nomsk:
    R0 = DM(SAVE + 1);"""),
    # an aborted chain: the channel fully idle (every status bit) before P9I is unmasked
    ("""    R2 = 100;
da_w: R0 = DM(DMAC0);
    R1 = EXTSM;""", """    R2 = 1000;
da_w: R0 = DM(DMAC0);
    R1 = BUSYM;"""),
]


# 2026-11-06 ROOT CAUSE of the freezes: P9I is NOT EP DMA channel 0 on the Floor (nor the Stomp).
# Both stock DSP programs rewrite PICR0..2 at boot (0x8c12c..0x8c133: 0x0A821C66 / 0x241D6570 /
# 0x000DDC13): P9I = code 0x1A = LP1I (link port 1), P8I = LP0I; EPDM0I (0x09) and EPDM1I (0x0D)
# are routed nowhere, so neither EP DMA channel raises any interrupt. The Floor keeps P9I unmasked
# because it runs link port 1 between its two SHARCs (the Stomp has one DSP: masked). P9_SHARE
# masked the inter-DSP link interrupt for ~37% of every block (lag) and HONEST cleared its latch:
# a lost link-port interrupt hangs the DSP<->DSP/host messaging -> UI frozen, audio on.
# P9_MODE "nomask": never touch LIRPTL; use channel 0 whenever DMAC0 is idle (no interrupt can fire),
# keep the waits for a fully idle channel at exit and in dma_abort.
P9_MODE = os.environ.get("NAM_P9_MODE", "nomask")      # "nomask" (fix) | "share" (old images)
NOMASK_PATCHES = [
    ("""    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP0IMSK;
    R1 = R0 AND R1;
    IF EQ JUMP m_idle;
m_busy:""", """    IF EQ JUMP m_idle;                  // (P9I is link port 1 here, not this channel: leave it)
m_busy:"""),
    ("""// METER_EXIT
    R0 = DM(SAVE + 1);""", """// METER_EXIT
    R2 = 1000;                          // the channel fully idle before Line 6 runs again
x_w: R1 = DM(DMAC0);
    R3 = BUSYM;
    R1 = R1 AND R3;
    IF EQ JUMP x_idle;
    R2 = R2 - 1;
    IF NE JUMP x_w;
x_idle:
    R0 = DM(SAVE + 1);"""),
    SHARE_PATCHES[3],
]


# 2026-11-07 speed: the channel idles mid-layer (sim: 41.7K/call with real DMA timing, 29.0K with
# instant DMA). MID_PUMP = n splits each layer's 8-pair loop into n chunks; between chunks, out of SIMD,
# if channel 0 is idle, pump starts the next ready job (I0-I3, I5, L1, L2 kept in MPS; M4 = 0, R3 = 0
# restored). 0 = off (the installed NOMASK).
MID_PUMP = int(os.environ.get("NAM_MID_PUMP", "0"))
MP_LOOP = ("""      LCNTR = 8, DO n_pair UNTIL LCE;""", """      LCNTR = MP_OUTER, DO n_mp UNTIL LCE;
      LCNTR = MP_INNER, DO n_pair UNTIL LCE;""")
MP_END = ("""n_pair: DM(I3, M6) = F13;
      BIT CLR MODE1 PEYEN | BDCST9;""", """n_pair: DM(I3, M6) = F13;
      BIT CLR MODE1 PEYEN | BDCST9;
      CALL mpump;
      BIT SET MODE1 PEYEN | BDCST9;
      NOP;                              // (no CALL in a loop's last three instructions)
      NOP;
n_mp: NOP;
      BIT CLR MODE1 PEYEN | BDCST9;""")
MP_SUB = """
// Mid-layer pump (out of SIMD): channel 0 idle -> pump, keeping the pair loop's pointers.
mpump:
    R0 = DM(DMAC0);
    R1 = BUSYM;
    R0 = R0 AND R1;
    IF NE RTS;
    DM(MPS + 0) = I0;
    DM(MPS + 1) = I1;
    DM(MPS + 2) = I2;
    DM(MPS + 3) = I3;
    DM(MPS + 4) = I5;
    DM(MPS + 5) = L1;
    DM(MPS + 6) = L2;
    CALL pump;
    I0 = DM(MPS + 0);
    I1 = DM(MPS + 1);
    I2 = DM(MPS + 2);
    I3 = DM(MPS + 3);
    I5 = DM(MPS + 4);
    L1 = DM(MPS + 5);
    L2 = DM(MPS + 6);
    M4 = 0;
    R3 = 0;
    RTS;
"""


# 2026-11-07 speed: half the sim's DMA time is per-TCB overhead (303 TCBs a call). GATHER: a far layer's
# taps as ONE scatter/gather (tap list) TCB (HRM 4-133; TCB Table 3-26: CP, TPEP, TCEP, EMEP, EIEP, ICEP,
# IMEP, IIEP; DMACx TLEN; block i word k at EIEP + TL[i] + EMEP * k, measured on the unit) with 18 entries,
# 6c + t = tap t of channel c (t = 5: the next window, overwritten by fcopy), + a 1-word tap-list
# sentinel. 192 -> 24 TCBs a call for the tap jobs.
GATHER = os.environ.get("NAM_GATHER") == "1"
PRB_WORDS = 0                       # (nam_floor5t: the tap-list probe's buffer)
TLEN = 0x200
GTCB = 8
G_TAP = ("""    // a far layer's taps: TCB 3t + c reads tap t (oldest first) of channel c
    I3 = DM(J_ROW, I5);
    I0 = DM(J_CHAIN, I5);
    MODIFY(I0, TCB_EI);
    R8 = DM(G_SDR);
    R1 = DM(T_RB, I3);
    R8 = R8 + R1;                       // channel 0's ring
    M4 = DM(T_LW, I3);
    R2 = DM(M4, I6);                    // this block's write offset
    R10 = DM(T_L, I3);
    R1 = DM(T_KD, I3);
    R2 = R2 + R1;                       // the oldest tap's window
    IF LT R2 = R2 + R10;
    R3 = DM(T_D, I3);
    R6 = DM(T_STRIDE, I3);
    LCNTR = KM1, DO p_rl UNTIL LCE;
      R1 = R8 + R2;
      R1 = R1 + R6, DM(I0, 6) = R1;     // (each store with the next channel's address)
      R1 = R1 + R6, DM(I0, 6) = R1;
      R2 = R2 + R3, DM(I0, 6) = R1;
      COMP(R2, R10);
p_rl: IF GE R2 = R2 - R10;
    R1 = DM(G_SDR);                     // the sentinel TCB: MAGIC from SENT into the flag
    R2 = SENT_OFF;
    R1 = R1 + R2;
    DM(0, I0) = R1;
    I0 = DM(J_FLAG, I5);""", """    // a far layer's taps (GATHER): one tap-list TCB; entry 6c + t = tap t of channel c, as
    // offsets from EIEP = channel 0's ring (block i at EIEP + TL[i]: measured, TLPROBE2)
    I3 = DM(J_ROW, I5);
    I0 = DM(J_CHAIN, I5);
    R8 = DM(G_SDR);
    R1 = DM(T_RB, I3);
    R8 = R8 + R1;                       // channel 0's ring
    DM(4, I0) = R8;                     // TCB 0's EIEP (post-modify: block i at EIEP + TL[i], unit 11-07)
    M4 = DM(T_LW, I3);
    R2 = DM(M4, I6);                    // this block's write offset
    R10 = DM(T_L, I3);
    R1 = DM(T_KD, I3);
    R2 = R2 + R1;                       // the oldest tap's window
    IF LT R2 = R2 + R10;
    R3 = DM(T_D, I3);
    R6 = DM(T_STRIDE, I3);
    R1 = DM(G_SDR);                     // TCB 1, the sentinel: MAGIC from SENT into the flag
    R0 = SENT_OFF;
    R1 = R1 + R0;
    DM(12, I0) = R1;
    MODIFY(I0, 16);                     // the tap list, after the two TCBs
    LCNTR = 6, DO p_rl UNTIL LCE;
      R1 = R2 + R6, DM(0, I0) = R2;     // channel 0 at entry t, 1 at 6 + t, 2 at 12 + t
      R1 = R1 + R6, DM(6, I0) = R1;
      R2 = R2 + R3, DM(12, I0) = R1;
      COMP(R2, R10);
      IF GE R2 = R2 - R10;
p_rl: MODIFY(I0, 1);
    I0 = DM(J_FLAG, I5);""")
# GATHER_W: a write-back group as one scatter TCB per far layer (tap list [0, s, 2s] from its ring's
# write address - 1) + the sequence-number TCB, all tap-list TCBs: 3 * gmax + 1 -> gmax + 1 TCBs.
GATHER_W = GATHER and os.environ.get("NAM_GATHER_W", "1") == "1"
G_W = ("""    L1 = 0;
    L2 = 0;
    R1 = DM(J_CHAIN, I5);
    R2 = TCB_EI;
    R1 = R1 + R2;
    I0 = R1;
    I1 = DM(J_ROW, I5);                 // (FARTAB + the group's first far layer)
    I2 = DM(J_FLAG, I5);                // (WADDR + the same)
    R2 = DM(J_N, I5);
    LCNTR = R2, DO p_wl UNTIL LCE;
      I3 = I1;
      MODIFY(I1, FT_SIZE);
      R6 = DM(T_STRIDE, I3);
      R1 = DM(I2, 1);
      DM(I0, 6) = R1;
      R1 = R1 + R6;
      DM(I0, 6) = R1;
      R1 = R1 + R6;
p_wl: DM(I0, 6) = R1;
    R1 = DM(G_SDR);
    R2 = SENT2_OFF;
    R1 = R1 + R2;
    DM(0, I0) = R1;
    DM(J_CHKADR) = R1;
    R1 = I6;
    R2 = S_SEQ;
    R1 = R1 + R2;
    DM(3, I0) = R1;                     // (TCB_II - TCB_EI)
    R1 = DM(S_SEQ, I6);
    R1 = R1 + 1;
    DM(S_SEQ, I6) = R1;
    DM(J_CHKVAL) = R1;
    R0 = TRAN;                          // internal -> external""", """    L1 = 0;
    L2 = 0;
    I0 = DM(J_CHAIN, I5);               // (GATHER_W) the group's first scatter TCB
    I1 = DM(J_ROW, I5);                 // (FARTAB + the group's first far layer)
    I2 = DM(J_FLAG, I5);                // (WADDR + the same)
    R2 = DM(J_N, I5);
    LCNTR = R2, DO p_wl UNTIL LCE;
      I3 = I1;
      MODIFY(I1, FT_SIZE);
      R6 = DM(T_STRIDE, I3);
      R1 = DM(I2, 1);
      DM(4, I0) = R1;                   // EIEP: channel 0's window
      I3 = DM(1, I0);                   // its tap list [0, s, 2s]
      DM(1, I3) = R6;
      R6 = R6 + R6;
      DM(2, I3) = R6;
p_wl: MODIFY(I0, GTCB);
    R1 = DM(G_SDR);                     // the sequence-number TCB
    R2 = SENT2_OFF;
    R1 = R1 + R2;
    DM(J_CHKADR) = R1;
    DM(4, I0) = R1;
    R1 = I6;
    R2 = S_SEQ;
    R1 = R1 + R2;
    DM(7, I0) = R1;
    R1 = DM(S_SEQ, I6);
    R1 = R1 + 1;
    DM(S_SEQ, I6) = R1;
    DM(J_CHKVAL) = R1;
    R0 = TRAN | TLEN;                   // internal -> external, tap list""")
G_GO = ("""    R1 = MAGIC;
    DM(J_CHKVAL) = R1;
    R0 = 0;                             // external -> internal
    JUMP p_go;
p_w:""", """    R1 = MAGIC;
    DM(J_CHKVAL) = R1;
    R0 = TLEN;                          // external -> internal, tap list
    JUMP p_go;
p_w:""")


def names():
    return nf.names() + ["HFLAG", "HDR_RECH", "T_NXN", "T_NXO", "T_NXB", "T_NXR", "W_OFF", "HDR", "SIL_N",
                         "N_WEIGHTS", "LBROW0", "LBSUM", "LBF0", "LBF1", "DIAG", "DCNT", "DCAUSE", "FT_SIZE",
                         "S_PMB", "INST_DM_SPAN", "INST_PM_SPAN"] + \
        (["MSKD"] if P9_SHARE and P9_MODE != "nomask" else []) + (["MPS", "MP_INNER", "MP_OUTER"] if MID_PUMP else []) +         (["TLEN", "GTCB"] if GATHER else [])


def equs(v):
    return "".join(f".equ {k}, {v[k]:#x}\n" for k in names())


def code_sizes():
    v = {k: 0 for k in names()}
    secs, _ = sasm.assemble(kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(v)),
                            "nam_floor5.asm")
    pm = [len(s.words) for s in secs if s.kind == "pm"]
    return pm[0], sum(pm[1:])


class Regions(nf.Regions):
    def __init__(self):
        self.free = {k: list(v) for k, v in REGIONS3.items()}


def queue5(far, groups):
    """Channel 0's one queue, in start order: (threshold, need, kind, index). EVENTS: +1 when a
    far layer has its newest tap, +1 when any layer is computed.
      F i   layer i's row + weights into LB[i % 2]: after layer i - 2 (its buffer free); F NL is
            the head's weights into LB1, after layer NL - 2
      R j   far layer j's taps into SB[j % 2]: after far layer j - 2
      W g   group g's write-back from the shared OUTBUF: after its last fcopy, and before the next
            group's first taps (whose fcopy refills OUTBUF)."""
    ev, done, fc = 0, {}, {}
    for i in range(NL):
        if i in far:
            ev += 1
            fc[i] = ev
        ev += 1
        done[i] = ev
    jobs = {}
    for i in range(NL + 1):
        jobs[("F", i)] = [0 if i < 2 else done[i - 2], (i, 0)]
    for j, i in enumerate(far):
        jobs[("R", j)] = [0 if j < 2 else done[far[j - 2]], (i, 1)]
    for g, grp in enumerate(groups):
        thr = fc[far[grp[-1]]]
        if g + 1 < len(groups):
            nxt = groups[g + 1][0]
            jobs[("R", nxt)][0] = max(jobs[("R", nxt)][0], thr)
            jobs[("W", g)] = [thr, (far[nxt], 0.5)]
        else:
            jobs[("W", g)] = [thr, (NL + 1, 0)]
    out = sorted(((t, n, k, j) for (k, j), (t, n) in jobs.items()), key=lambda x: (x[0], x[1]))
    pos = {(k, j): q for q, (_, _, k, j) in enumerate(out)}
    for g in range(len(groups) - 1):
        assert pos[("W", g)] < pos[("R", groups[g + 1][0])]
    return out


class Layout(n2.Layout):
    def __init__(self, backoff=nm.BACKOFF_N, inst_bounds=None, tables_base=None):
        slots = self.slots = SLOTS
        self.far_d, self.staging = FAR_D, "b3"
        self.n_code, self.n_cold = code_sizes()
        self.far = [i for i, (k, d) in enumerate(zip(KERNEL, DILATION)) if k == 6 and d >= FAR_D]
        F = self.nfar = len(self.far)
        # channel 0: each far layer's taps (R j into SB[j % 2]) and its own write-back (W j, from
        # SB[j % 2]'s newest tap), W j before R j+2 (which refills that buffer)
        if WB == "sb":
            self.groups = [[j] for j in range(F)]
            self.queue = [("R", 0), ("R", 1)]
            for j in range(2, F):
                self.queue += [("W", j - 2), ("R", j)]
            self.queue += [("W", F - 2), ("W", F - 1)]
        else:                            # upstream's groups, one shared buffer: a group's write-back
            self.groups = []             # goes before the next group's first taps (so it is done
            for j, i in enumerate(self.far):     # before that group's first fcopy refills it)
                if j and i == self.far[j - 1] + 1:
                    self.groups[-1].append(j)
                else:
                    self.groups.append([j])
            self.gmax = max(len(g) for g in self.groups)
        assert WB == "group"
        self.jobs = queue5(self.far, self.groups)
        self.queue = [(k, j) for _, _, k, j in self.jobs]
        self.ring = [(k - 1) * d + 16 for k, d in zip(KERNEL, DILATION)]
        self.nring = [L + (L & 1) for L in self.ring]
        near = [i for i in range(NL) if i not in self.far]
        v = {k: x for k, x in list(nm.S.items()) + list(nm.ST.items()) + list(nm.REPW.items()) + list(T3.items())
             + list(nm.J.items()) + list(nm.P.items())}
        v["ST_SIL"] = (4 if HEAD_FETCH else HDR)
        assert nm.S["S_LW"] + NL <= S_PMB < nm.S_STREAM, "S_PMB is not a free state word"
        v["S_PMB"] = S_PMB
        if HEAD_FETCH:
            v["ST_SCALE"] = 3
        rg = self.rg = Regions()
        rg.free["R3"][0] += nf.GUARD
        rg.free["R2"][0] += nf.GUARD
        r1 = REGIONS3["R1"][0]
        pm = nm.NW3 + -(-(r1 - nm.NW3) * 2 // 3)
        pm += pm & 1
        self.code_pm = pm
        code_nw = nm.NW3 + (pm - nm.NW3) * 3 // 2
        rg.free["R1"][0] = code_nw + nf.nw(self.n_code)
        cw = nf.nw(self.n_cold)
        cpm = nm.NW3 + (nm.COLD_END - cw - nm.NW3) * 2 // 3
        self.cold_pm = cpm - (cpm & 1)
        self.cold_nw = nm.NW3 + (self.cold_pm - nm.NW3) * 3 // 2
        rg.free["R1"][1] = self.cold_nw
        assert rg.free["R1"][0] <= rg.free["R1"][1], "the code does not fit R1"
        self.hdr = (3 + 1) if HEAD_FETCH else HDR
        h0 = nm.S_STREAM + self.hdr + (0 if SIL_SDRAM else SIL)
        h0 += h0 & 1
        self.hb = [h0 + (nm.HEADL + 2) * j for j in range(C)]
        self.s_rp = self.hb[-1] + nm.HEADL + 2
        self.rp_index = {i: j for j, i in enumerate(sorted(near))}
        self.nrp = len(near) + 1
        o = self.s_rp + self.nrp
        o += o & 1
        self.slot_size = o
        self.near_at, off = {}, {1: 0, 2: 0}
        for sel, layers in ((1, nf.DM_LAYERS), (2, nf.PM_LAYERS)):
            for i in layers:
                self.near_at[i] = (sel, off[sel])
                off[sel] += C * (self.nring[i] + 2)
        self.inst_dm_need, self.inst_pm_need = nf.INST_DM + 1 + off[1], nf.INST_PM + 1 + off[2]
        alloc = {}
        nj = len(self.queue)
        self.lbw = 1 + T_SIZE3 + LB_N                    # a layer buffer: flag, row, weights
        sizes = dict(FLAGREP=32, SAVE=64, SLOTTAB=slots, IN=16, X=48, HS=48, LB=2 * self.lbw, SB=2 * nm.SB_WORDS,
                     **({} if WB == "sb" else {"OUTBUF": 48 * max(len(g) for g in self.groups)}), RCH0=(2 * GTCB + 19) if GATHER else 16 * nm.TCB, RCH1=(2 * GTCB + 19) if GATHER else 16 * nm.TCB, LCH=2 * nm.TCB, JOBS=nj * nm.JOB,
                     FTAB=F * FT_SIZE, WADDR=F, FCH0=3 * nm.TCB, FCH1=3 * nm.TCB,
                     **{f"SLOT{j}": self.slot_size for j in range(slots)}, **({"MSKD": 1} if P9_SHARE and P9_MODE != "nomask" else {}),
                     **({"MPS": 8} if MID_PUMP else {}), **({"PRB": PRB_WORDS} if PRB_WORDS else {}))
        if WB == "sb":
            for b in range(2):
                sizes[f"WCH{b}"] = (3 + 1) * nm.TCB
        else:
            sizes["WCH0"] = (self.gmax + 1) * GTCB + 3 * self.gmax + 1 if GATHER_W else (3 * self.gmax + 1) * nm.TCB
        self.nclr = C + C * len(near)
        for name, n in sorted(sizes.items(), key=lambda x: -x[1]):
            even = name.startswith("SLOT")
            r = next((r for r in ("R1", "R3", "R2", "RX") if rg.spare()[r] >= n + 1), None)
            if r is None:
                raise SystemExit(f"no room for {name} ({n} words): {rg.spare()}")
            alloc[name] = rg.take(r, n, even=even)
        self.alloc = alloc
        self.slot = [alloc[f"SLOT{j}"] for j in range(slots)]
        self.lb = [alloc["LB"] + 1 + self.lbw * b for b in range(2)]     # each buffer's row (its flag at -1)
        self.b3 = alloc["FLAGREP"]
        self.rep = self.b3 + 16
        b3 = self.b3
        g = dict(G_SDR=b3, G_LEVEL=b3 + 1, J_NEXT=b3 + 2, J_BUSY=b3 + 3, J_DONE=b3 + 4, EVENTS=b3 + 5,
                 DMA_FAIL=b3 + 6, J_CHKADR=b3 + 7, J_CHKVAL=b3 + 8, FLAGL=b3 + 9, G_JOBS=b3 + 12)
        self.flags = [b3 + 10, b3 + 11]
        self.fflags = [lb - 1 for lb in self.lb]
        v.update(g)
        self.sb = [alloc["SB"], alloc["SB"] + nm.SB_WORDS]
        self.xhi_b2 = self.wbuf_b2 = False
        self.wbuf = self.lb[1] + T_SIZE3
        self.b2_to = self.b2_data = 0
        self.lp = {i: nm.rup16(self.ring[i]) for i in self.far}
        o, self.far_off = 0, {}
        for i in self.far:
            self.far_off[i] = o
            o += C * (self.lp[i] + 16)
        self.hist_off = o
        self.sent_off = o + nm.HIST_N
        self.w_off = nm.rup16(self.sent_off + 2)
        self.sdr_need = self.w_off + nm.N_STREAM
        self.eq_tab = nm.DDR2 if tables_base is None else tables_base
        self.stomp_gain = self.eq_tab + 4 * 101 * 5
        a = self.stomp_gain + 1
        for name, n in (("RPTAB", 3 * self.nrp), ("CLR", 3 * self.nclr), ("DRIVE_TAB", 101), ("FADE_TAB", 18),
                        ("TROWS", (NL + 1) * T_SIZE3)):          # (+ a blank row: the head's fetch)
            alloc[name] = a
            a += n
        self.ddr2_to = a
        (dlo, dhi), (plo, phi) = inst_bounds or (n2.HEAP_A2, n2.HEAP_B2)
        v["INST_DM_SPAN"] = dhi - self.inst_dm_need - dlo      # (GUARD_PATCH's unsigned checks)
        v["INST_PM_SPAN"] = phi - self.inst_pm_need - plo
        assert v["INST_DM_SPAN"] >= 0 and v["INST_PM_SPAN"] >= 0
        v.update(SAVE=alloc["SAVE"], REP=self.rep, SLOTTAB=alloc["SLOTTAB"], NSLOTS=slots, IN=alloc["IN"],
                 X=alloc["X"], HS=alloc["HS"], TABLE=0, NLAYERS=NL, JOBS=alloc["JOBS"],
                 LBROW0=self.lb[0], LBSUM=self.lb[0] + self.lb[1], LBF0=self.fflags[0], LBF1=self.fflags[1], FT_SIZE=FT_SIZE,
                 NJOBS=nj, CLR=alloc["CLR"], NCLR=self.nclr, DRIVE_TAB=alloc["DRIVE_TAB"],
                 FADE_TAB=alloc["FADE_TAB"], EQ_TAB=self.eq_tab, STOMP_GAIN=self.stomp_gain, COLD_PM=self.cold_pm,
                 WBUF=self.wbuf, HEADL=nm.HEADL, LBUF=self.sb[0], LBUF_N=2 * nm.SB_WORDS, LCH=alloc["LCH"],
                 LCH_CP=(alloc["LCH"] + nm.TCB_II) & 0x7FFFF, FARTAB=alloc["FTAB"], WADDR=alloc["WADDR"],
                 NFAR=F, S_STREAM=nm.S_STREAM, S_HB0=self.hb[0], S_HB1=self.hb[1], S_HB2=self.hb[2],
                 HIST_OFF=self.hist_off, SENT_OFF=self.sent_off, SENT2_OFF=self.sent_off + 1,
                 SDR_NEED=self.sdr_need, MAGIC=nm.MAGIC, POLLMAX=nm.POLLMAX, LPOLLMAX=nm.LPOLLMAX,
                 BACKOFF_N=backoff, T_MAX=nm.T_MAX, N_STREAM=nm.N_STREAM, KM1=5, T_SIZE=T_SIZE3,
                 TCB_EI=nm.TCB_EI, TCB_IC=nm.TCB_IC, TCB_II=nm.TCB_II, IR_FLAG=nm.IR_FLAG, IR_TOP=nm.IR_TOP,
                 DMAC0=nm.DMAC0, EIEP0=nm.EIEP0, EMEP0=nm.EMEP0, ICEP0=nm.ICEP0, IIEP0=nm.IIEP0, IMEP0=nm.IMEP0,
                 CPEP0=nm.CPEP0, DFLSH=nm.DFLSH, DEN_CHEN=nm.DEN | nm.CHEN, TRAN=nm.TRAN,
                 BUSYM=nm.DEN | nm.DMAS | nm.CHS | nm.EXTS, EXTSM=nm.EXTS, EP0IMSK=nm.EP0IMSK, HXK_ENTRY_INST=2,
                 HXK_INST_SDRAM=6, HXK_INST_SDRAM_END=7, CODE_PM=self.code_pm, RPTAB=alloc["RPTAB"],
                 NRP=self.nrp, INST_DM=nf.INST_DM, INST_PM=nf.INST_PM, INST_DM_LO=dlo, INST_DM_HI=dhi,
                 INST_PM_LO=plo, INST_PM_HI=phi, INST_DM_NEED=self.inst_dm_need, INST_PM_NEED=self.inst_pm_need,
                 W_OFF=self.w_off, HDR=HDR, HDR_RECH=3 if HEAD_FETCH else HDR,
                 HFLAG=self.fflags[1], SIL_N=SIL, N_WEIGHTS=nam_lite.N_WEIGHTS, 
                 DIAG=b3 + 13, DCNT=b3 + 14, DCAUSE=b3 + 15, **({"MSKD": alloc["MSKD"]} if P9_SHARE and P9_MODE != "nomask" else {}),
                 **({"MPS": alloc["MPS"], "MP_INNER": 8 // MID_PUMP, "MP_OUTER": MID_PUMP} if MID_PUMP else {}),
                 **({"TLEN": TLEN, "GTCB": GTCB} if GATHER else {}),
                 **({"PRB": alloc["PRB"]} if PRB_WORDS else {}))
        self.v = v
        self.b3_to = None

    def words(self):
        v, al, F = self.v, self.alloc, self.nfar
        mem = {}

        def put(a, vals):
            for i, x in enumerate(vals):
                assert a + i not in mem, hex(a + i)
                mem[a + i] = x & 0xFFFFFFFF

        put(self.b3, [0] * 16)
        put(self.sb[0], [0] * (2 * nm.SB_WORDS))
        put(self.rep, [nm.MAGIC] + [0] * 15)
        put(al["SLOTTAB"], self.slot)
        for s in self.slot:
            put(s + nm.S["S_OWNER"], [0])
        wo = nm.stream_offsets()
        rpos = {self.far[j]: q for q, (t, j) in enumerate(self.queue) if t == "R"}

        trows = al["TROWS"]

        def nx(row, i):                                  # the fetch of layer i (none past the last)
            if i < NL:
                row[T3["T_NXN"]] = lw(KERNEL[i])
                row[T3["T_NXO"]] = self.w_off + wo[i]
                row[T3["T_NXB"]] = 3 * (i % 2)
                row[T3["T_NXR"]] = trows + T_SIZE3 * i

        r_1 = [0] * T_SIZE3
        nx(r_1, 0)
        tab, ftab = [], []
        for i, (k, d) in enumerate(zip(KERNEL, DILATION)):
            row = [0] * T_SIZE3
            row[T3["T_LW"]] = nm.S["S_LW"] + i
            row[T3["T_K"]] = k
            row[T3["T_KD"]] = -(k - 1) * d
            row[T3["T_D"]] = d
            row[T3["T_NW"]] = -lw(k)
            nx(row, i + 1)
            if HEAD_FETCH and i == NL - 1:              # after the last layer: the head's 49 into LB1
                assert NL % 2 == 1                      # (with the blank row NL: its row area zeroed)
                row[T3["T_NXN"]] = 49
                row[T3["T_NXO"]] = self.w_off + 3
                row[T3["T_NXB"]] = 3
                row[T3["T_NXR"]] = trows + T_SIZE3 * NL
            if i in self.far:
                j = self.far.index(i)
                L = self.lp[i]
                row[T3["T_RB"]] = self.far_off[i]
                row[T3["T_STRIDE"]] = L + 16
                row[T3["T_L"]] = L
                row[T3["T_S"]] = 16
                row[T3["T_KS"]] = -(k - 1) * 16
                row[T3["T_FAR"]] = j + 1
                row[T3["T_RPOS"]] = rpos[i]
                row[T3["T_SB"]] = self.sb[j % 2]
                if WB == "sb":
                    row[T3["T_OB"]] = self.sb[j % 2] + 80     # (unused: no write-back buffer)
                else:
                    g = next(g for g in self.groups if j in g)
                    row[T3["T_OB"]] = al["OUTBUF"] + 48 * g.index(j)
                row[T3["T_WA"]] = al["WADDR"] + j
                row[T3["T_SIL"]] = ((self.w_off + nam_lite.N_WEIGHTS) if SIL_SDRAM else (nm.S_STREAM + self.hdr)) + C + C * i
            else:
                L = self.nring[i]
                row[T3["T_RB"]] = self.s_rp + self.rp_index[i]
                row[T3["T_STRIDE"]] = L + 2
                row[T3["T_L"]] = L
                row[T3["T_S"]] = d
                row[T3["T_KS"]] = -(k - 1) * d
            tab += row
            if i in self.far:
                ftab += row[:FT_SIZE]
        put(trows, tab + [0] * T_SIZE3)
        put(al["FTAB"], ftab)
        put(al["WADDR"], [0] * F)
        rp_slot = self.s_rp + self.nrp - 1
        rpt = []
        for i, j in sorted(self.rp_index.items(), key=lambda x: x[1]):
            sel, off = self.near_at[i]
            rpt += [self.s_rp + j, sel, off]
        rpt += [rp_slot, 0, 0]
        put(al["RPTAB"], rpt)
        clr = [((rp_slot << 16) | self.hb[c], nm.HEADL + 1, c) for c in range(C)]
        for i in sorted(self.rp_index):
            for c in range(C):
                clr.append((((self.s_rp + self.rp_index[i]) << 16) | (c * (self.nring[i] + 2)), self.nring[i] + 1,
                            C + C * i + c))
        put(al["CLR"], [x for r in clr for x in r])
        put(al["DRIVE_TAB"], [nam_pack.f2b(10.0 ** ((step - 50) * 0.4 / 20)) for step in range(101)])
        put(al["FADE_TAB"], nam_lite.fade_table())

        def tcb(cp, ic, ii):
            return [cp & 0x7FFFF if cp else 0, 1, 0, ic, 1, ii]

        for b, ch in enumerate((al["RCH0"], al["RCH1"])):
            if GATHER:                         # TCB 0 (18 taps of 16), TCB 1 (sentinel), tap list, 0
                put(ch, [(ch + GTCB + 7) & 0x7FFFF, ch + 16, 18, 1, 0, 16, 1, self.sb[b]] +
                        [0, ch + 34, 1, 1, 0, 1, 1, self.flags[b]] + [0] * 18 + [0])
                continue
            t = []
            for n in range(15):
                tt, c = divmod(n, 3)
                t += tcb(ch + nm.TCB * (n + 1) + nm.TCB_II, 16, self.sb[b] + 96 * c + 16 * tt)
            t += tcb(0, 1, self.flags[b])
            put(ch, t)
        if WB == "sb":
            for b in range(2):
                t = []
                for c in range(3):
                    t += tcb(al[f"WCH{b}"] + nm.TCB * (c + 1) + nm.TCB_II, 16, self.sb[b] + 80 + 96 * c)
                t += tcb(0, 1, 0)
                put(al[f"WCH{b}"], t)
        elif GATHER_W:                         # gmax scatter TCBs, the sequence TCB, tap lists, a 0
            w0, g = al["WCH0"], self.gmax
            tl = w0 + (g + 1) * GTCB
            t = []
            for jj in range(g):
                t += [(w0 + GTCB * (jj + 1) + 7) & 0x7FFFF, tl + 3 * jj, 3, 1, 0, 16, 1, al["OUTBUF"] + 48 * jj]
            t += [0, tl + 3 * g, 1, 1, 0, 1, 1, 0] + [0] * (3 * g) + [0]
            put(w0, t)
        else:
            t = []
            for m in range(3 * self.gmax):
                jj, c = divmod(m, 3)
                t += tcb(al["WCH0"] + nm.TCB * (m + 1) + nm.TCB_II, 16, al["OUTBUF"] + 48 * jj + 16 * c)
            t += tcb(0, 1, 0)
            put(al["WCH0"], t)
        for b in range(2):
            ch = al[f"FCH{b}"]
            put(ch, tcb(ch + nm.TCB + nm.TCB_II, T_SIZE3, self.lb[b]) +
                tcb(ch + 2 * nm.TCB + nm.TCB_II, 0, self.lb[b] + T_SIZE3) + tcb(0, 1, self.fflags[b]))
        put(al["LCH"], tcb(al["LCH"] + nm.TCB + nm.TCB_II, 0, self.sb[0]) + tcb(0, 1, v["FLAGL"]))
        jobs = []
        for thr, _, kind, j in self.jobs:
            if kind == "R":
                ch = (al["RCH0"], al["RCH1"])[j % 2]
                jobs += [0, thr, al["FTAB"] + FT_SIZE * j, ch, self.flags[j % 2],
                         (ch + (7 if GATHER else nm.TCB_II)) & 0x7FFFF, 0, 0]
            elif kind == "W":
                grp = self.groups[j]
                ch = al["WCH0"] + (GTCB * (self.gmax - len(grp)) if GATHER_W else nm.TCB * 3 * (self.gmax - len(grp)))
                jobs += [1, thr, al["FTAB"] + FT_SIZE * grp[0], ch, al["WADDR"] + grp[0],
                         (ch + (7 if GATHER_W else nm.TCB_II)) & 0x7FFFF, len(grp), 0]
            else:                                    # F j: layer j's row + weights (j == NL: the head's)
                b = j % 2 if j < NL else 1
                ch = al[f"FCH{b}"]
                off, n = (self.w_off + wo[j], lw(KERNEL[j])) if j < NL else (self.w_off + 3, 49)
                jobs += [2, thr, trows + T_SIZE3 * j, ch, self.fflags[b], (ch + nm.TCB_II) & 0x7FFFF, off, n]
        put(al["JOBS"], jobs)
        put(self.eq_tab, nam_lite.eq_table())
        put(self.stomp_gain, [nam_pack.f2b(10.0 ** (nam_lite.STOMP_DBU / 20))])
        return mem

    def claims(self):
        return n2.Layout.claims(self)

    def report(self):
        r = n2.Layout.report(self)
        r.pop("jobs", None)
        return r


def build(backoff=nm.BACKOFF_N, **kw):
    lay = Layout(backoff=backoff, **kw)
    src = kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(lay.v))
    secs, _ = sasm.assemble(src, "nam_floor5.asm")
    pm = [s for s in secs if s.kind == "pm"]
    assert pm[0].addr == lay.code_pm and len(pm[0].words) == lay.n_code
    mem = lay.words()
    lines = ["", "// ---- tables, written by nam_floor5.py ----"]
    last = None
    for a in sorted(mem):
        if a != (last or 0) + 1:
            lines.append(f".section dm {a:#x}")
        lines.append(f"    .word {mem[a]:#010x}")
        last = a
    return src + "\n".join(lines) + "\n", lay


def _chain_dma1():
    """upstream's ChainDma with channel 1's registers."""
    src = inspect.getsource(nm.ChainDma)
    for a, b in (("DMAC0", "DMAC1"), ("EIEP0", "EIEP1"), ("EMEP0", "EMEP1"), ("ECEP0", "ECEP1"),
                 ("IIEP0", "IIEP1"), ("IMEP0", "IMEP1"), ("ICEP0", "ICEP1"), ("CPEP0", "CPEP1")):
        src = src.replace(a, b)
    src = src.replace("class ChainDma:", "class ChainDma1:")
    g = dict(vars(nm), DMAC1=DMAC1, EIEP1=EIEP1, EMEP1=EMEP1, ECEP1=ECEP1, IIEP1=IIEP1, IMEP1=IMEP1, ICEP1=ICEP1,
             CPEP1=CPEP1)
    exec(src, g)
    return g["ChainDma1"]


ChainDma1 = _chain_dma1()
TIMING = ("start", "tcb", "word")


class GatherDma(nm.ChainDma):
    """ChainDma + tap-list (scatter/gather) chains: DMACx TLEN with CHEN loads 8-word TCBs (CP, TPEP,
    TCEP, EMEP, EIEP, ICEP, IMEP, IIEP; the chain pointer at IIEP, loaded downwards); block i of ICEP
    words starts at EIEP + TL[i] (post-modify, measured on the unit; 27-bit signed offsets); internal sequential.
    `tap` cycles per tap-list entry (a guess) on top of `tcb` per TCB."""

    def __init__(self, sim, tap=4, **kw):
        super().__init__(sim, **kw)
        self.c_tap, self.tl = tap, False

    def _start(self, ctl, cp):
        self.tl = bool(ctl & TLEN) and cp is not None
        super()._start(ctl, cp)

    def _load(self, cp, now):
        if not self.tl:
            return super()._load(cp, now)
        p = self._int(cp)
        r = self.rd0
        t = dict(ii=self._int(r(p)), im=nm.s32(r(p - 1)), ic=r(p - 2) & 0xFFFF or 0x10000, ei=r(p - 3),
                 em=nm.s32(r(p - 4)), tc=r(p - 5) & 0xFFFF, tp=self._int(r(p - 6)), cp=r(p - 7) & 0x7FFFF)
        def s27(v):
            v &= 0x7FFFFFF
            return v - (1 << 27) if v & (1 << 26) else v
        t["blocks"] = []
        for i in range(t["tc"]):
            e0 = t["ei"] + s27(r(t["tp"] + i))          # post-modify (TLPROBE2 on the unit)
            i0 = t["ii"] + i * t["ic"] * t["im"]
            t["blocks"].append((e0, i0))
            self.log.append((self.tran, e0, i0, t["ic"], t["em"], t["im"]))
            if not self.tran:
                for k in range(t["ic"]):
                    self.wr0(i0 + k * t["im"], self.POISON)
        self.cur = t
        self.tcbs += 1
        for reg, k in ((nm.IIEP0, "ii"), (nm.ICEP0, "ic"), (nm.EIEP0, "ei"), (nm.CPEP0, "cp")):
            self.wr0(reg, t[k] & 0xFFFFFFFF)
        self.due = math.inf if self.mode == "stall" else             now + self.c_tcb + (self.c_word * t["ic"] + self.c_tap) * t["tc"]

    def _finish(self):
        t = self.cur
        if not self.tl:
            return super()._finish()
        if self.mode != "nocopy":
            for e0, i0 in t["blocks"]:
                for k in range(t["ic"]):
                    ia, ea = i0 + k * t["im"], e0 + k * t["em"]
                    src, dst = (ia, ea) if self.tran else (ea, ia)
                    self.wr0(dst, self.rd0(src))
        self.words += t["ic"] * t["tc"]
        self.wr0(nm.ICEP0, 0)
        self.wr0(nm.ECEP0, 0)
        now = self.due
        if t["cp"] and self.chained:
            self._load(t["cp"], now)
        else:
            self.active = False
            self.cycles_busy += now - self.t0
            self.wr0(nm.DMAC0, self.rd0(nm.DMAC0) & ~(nm.DMAS | nm.EXTS | nm.CHS))


if GATHER:
    nm.ChainDma = GatherDma


class Rig(nf.Rig):
    def __init__(self, asm, lay, seed=1, **dma):
        nf.REGIONS, r0 = REGIONS3, nf.REGIONS
        try:
            super().__init__(asm, lay, seed, **dma)
        finally:
            nf.REGIONS = r0
        self.allowed = lay.claims()[:5]

    def check_dma(self, inst, label):
        """nam_floor's rule, plus channel 0 may read the layer rows in DDR2 (TROWS)."""
        sd = (inst.sdram, inst.sdram + self.lay.sdram_words())
        ir = (nm.IR_TOP - 0x800 + 1, nm.IR_TOP + 128 * 0x800)
        tr = (self.lay.alloc["TROWS"], self.lay.ddr2_to)
        for out, ei, ii, n, em, im in self.dma.log:
            e0, e1 = sorted((ei, ei + (n - 1) * em))
            i0, i1 = sorted((ii, ii + (n - 1) * im))
            ok_e = sd[0] <= e0 and e1 < sd[1] or not out and (ir[0] <= e0 and e1 < ir[1] or tr[0] <= e0 and e1 < tr[1])
            ok_i = any(a <= i0 and i1 < b for a, b in self.allowed)
            if not (ok_e and ok_i):
                raise nm.CheckFailed(f"{label}: a TCB {'to' if out else 'from'} {ei:#x} ({n} words) / internal "
                                     f"{ii:#x} is outside the instance's memory")
        self.dma.log.clear()


def check(asm, lay, w, **kw):
    nm.Rig, rig0 = Rig, nm.Rig
    nm.REP = lay.rep
    try:
        return nm.check(asm, lay, w, **kw)
    finally:
        nm.Rig = rig0


RIG_BOUNDS = nf.RIG_BOUNDS


def main():
    asm, lay = build()
    for k, v in lay.report().items():
        print(f"{k}: {v}")
    if "--bench" in sys.argv:
        import bench2
        bench2.mod = sys.modules[__name__]
        asm, lay = build(inst_bounds=RIG_BOUNDS)
        print("bench: steady mean %.0f worst %d maxpolls %d dma0 busy %s" % bench2.bench(asm, lay))
    if "--check" in sys.argv:
        asm, lay = build(inst_bounds=RIG_BOUNDS)
        ok, res, _ = check(asm, lay, nam_lite.placeholder())
        print("check:", "PASS" if ok else "FAIL", res)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
