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

usage: nam_floor4.py [--check] [--bench]
"""
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nam_floor as nf  # noqa: E402
import nam_floor2 as n2  # noqa: E402
import nam_floor3 as n3  # noqa: E402
from nam_floor import nm, nam_lite, nam_pack, sasm, C, NL, KERNEL, DILATION, FAR_D  # noqa: E402

REGIONS3 = n2.REGIONS2
HDR, SIL, LB_N = n2.HDR, n2.SIL, n2.LB_N
EP1IMSK = 0x20000                   # LIRPTL P13IMSK (P6IMSK..P15IMSK = bits 10..19; P9IMSK = 0x2000 as upstream)
DMAC1, EIEP1, EMEP1, ECEP1, IIEP1, IMEP1, ICEP1, CPEP1 = 0x180C, 0x1830, 0x1831, 0x1832, 0x1833, 0x1834, 0x1835, 0x1836   # ADSP-214xx HRM rev 1.1, register table
# A layer's row now comes fetched with its weights: layer buffer b = [flag][row T_SIZE3][weights].
# Its last four words say what to fetch next (offset in SDRAM, count, buffer, the row in DDR2).
T3 = dict(nm.T, T_NXO=18, T_NXN=19, T_NXB=20, T_NXR=21)
T_SIZE3 = 22
FT_SIZE = 12                        # the far layers' rows on chip for pump (fields 0..11)
SLOTS = 2                           # NAM blocks per DSP (exp_ch1_meter may use 1)
HEAD_FETCH = True                   # the head's 49 weights fetched on channel 1 (slot keeps rechannel + scale)
SIL_SDRAM = True                    # the silence state in SDRAM after the weights, not in the slot
WB = "group"                        # write-back: "group" (one shared 4-layer buffer) or "sb" (from SB)
lw = n2.lw

PATCHES3 = [
    # fetch layer 0's weights before the loop; each layer waits for its own, then starts the next
    ("""    I4 = TABLE;
    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;""", """    I4 = ROWM1 - T_NXO;
    CALL lw_go;
    I4 = LBROW0;
    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;
      CALL lwait;
      R0 = DM(DMA_FAIL);                // a transfer failed: this layer's row and weights may
      R0 = PASS R0;                     // never have come, so the rest of the layers are skipped
      IF NE JUMP n_lskip;               // (their loop counts and pointers come from the row)"""),
    # the next layer's row is in the other buffer
    ("""n_layer: MODIFY(I4, T_SIZE);""", """n_lskip:
      R0 = LBSUM;
      R1 = I4;
      R0 = R0 - R1;
n_layer: I4 = R0;"""),
    ("""    DM(CPEP0) = R1;
    RTS;

// Wait (bounded) for this far layer's taps""", """    DM(CPEP0) = R1;
    RTS;

// This layer's weights (channel 1, its buffer's flag), then the next layer's fetch into the
// other buffer. Uses R0-R2, R9, I0, I1 (and pump's).
lwait:
    R0 = DM(DMA_FAIL);                  // after a failure: no waits, no new fetches
    R0 = PASS R0;
    IF NE RTS;
    R9 = POLLMAX;
lw_l: R1 = MAGIC;
    R0 = DM(-1, I4);                    // the buffer's flag, just before it
    COMP(R0, R1);
    IF EQ JUMP lw_go;
    CALL pump;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP lw_l;
    R0 = 0;                             // never came: channel 1 off, the block fails
    DM(DMAC1) = R0;
    R0 = 1;
    DM(DMA_FAIL) = R0;
    R0 = DM(REP + R_TIMEOUTS);
    R0 = R0 + 1;
    DM(REP + R_TIMEOUTS) = R0;
    RTS;
lw_go:
    R0 = DM(T_NXN, I4);                 // the next layer's words (0: none)
    R0 = PASS R0;
    IF EQ RTS;
    R2 = DM(T_NXB, I4);                 // its buffer's [chain, flag, CP]
    R1 = BUFT;
    R2 = R2 + R1;
    I1 = R2;
    I0 = DM(0, I1);
    R1 = DM(T_NXR, I4);                 // TCB 0: its row, from DDR2
    DM(TCB_EI, I0) = R1;
    R1 = DM(G_SDR);                     // TCB 1: its weights, from the instance's SDRAM
    R2 = DM(T_NXO, I4);
    R1 = R1 + R2;
    DM(TCB_EI + 6, I0) = R1;
    DM(TCB_IC + 6, I0) = R0;
    R1 = DM(G_SDR);                     // TCB 2, the sentinel: MAGIC from SENT into the flag
    R2 = SENT_OFF;
    R1 = R1 + R2;
    DM(TCB_EI + 12, I0) = R1;
    I0 = DM(1, I1);
    R1 = 0;
    DM(0, I0) = R1;
    R1 = DFLSH;
    DM(DMAC1) = R1;
    R1 = 0;
    DM(CPEP1) = R1;
    R1 = DEN_CHEN;
    DM(DMAC1) = R1;
    R1 = DM(2, I1);
    DM(CPEP1) = R1;
    RTS;

// Wait (bounded) for this far layer's taps"""),
    # the end of a call: channel 1 off too (its reset value)
    ("""n_ewd:
    R0 = 0;
    DM(DMAC0) = R0;""", """n_ewd:
    R0 = 0;
    DM(DMAC0) = R0;
    DM(DMAC1) = R0;"""),
    # a call starts only with channel 1 idle and its interrupt (P13I, EPDMA1) masked too, as
    # upstream asks of channel 0 (P9I): else the stock program may be using it, and the block is skipped
    ("""m_nobo:
    R0 = DM(DMAC0);""", """m_nobo:
    R0 = DM(DMAC1);
    R1 = BUSYM;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP1IMSK;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;
    R0 = DM(DMAC0);"""),
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
    return patch_head(src) if HEAD_FETCH else src


def names():
    return nf.names() + ["HFLAG", "HDR_RECH", "T_NXN", "T_NXO", "T_NXB", "T_NXR", "W_OFF", "HDR", "SIL_N",
                         "N_WEIGHTS", "BUFT", "DMAC1", "CPEP1", "ROWM1", "LBROW0", "LBSUM", "EP1IMSK", "DIAG", "DCNT", "DCAUSE"]


def equs(v):
    return "".join(f".equ {k}, {v[k]:#x}\n" for k in names())


def code_sizes():
    v = {k: 0 for k in names()}
    secs, _ = sasm.assemble(kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(v)),
                            "nam_floor4.asm")
    pm = [len(s.words) for s in secs if s.kind == "pm"]
    return pm[0], sum(pm[1:])


class Regions(nf.Regions):
    def __init__(self):
        self.free = {k: list(v) for k, v in REGIONS3.items()}


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
            first = {grp[0]: g for g, grp in enumerate(self.groups)}
            self.queue = []
            for j in range(F):
                if j in first and first[j] > 0:
                    self.queue.append(("W", first[j] - 1))
                self.queue.append(("R", j))
            self.queue.append(("W", len(self.groups) - 1))
            self.gmax = max(len(g) for g in self.groups)
        self.ring = [(k - 1) * d + 16 for k, d in zip(KERNEL, DILATION)]
        self.nring = [L + (L & 1) for L in self.ring]
        near = [i for i in range(NL) if i not in self.far]
        v = {k: x for k, x in list(nm.S.items()) + list(nm.ST.items()) + list(nm.REPW.items()) + list(T3.items())
             + list(nm.J.items()) + list(nm.P.items())}
        v["ST_SIL"] = (4 if HEAD_FETCH else HDR)
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
                     **({} if WB == "sb" else {"OUTBUF": 48 * max(len(g) for g in self.groups)}), RCH0=16 * nm.TCB, RCH1=16 * nm.TCB, LCH=2 * nm.TCB, JOBS=nj * nm.JOB,
                     FTAB=F * FT_SIZE, ROWM1=4, FARTAB=F, WADDR=F, FCH0=3 * nm.TCB, FCH1=3 * nm.TCB, BUFT=6,
                     SLOT0=self.slot_size, SLOT1=self.slot_size)
        if WB == "sb":
            for b in range(2):
                sizes[f"WCH{b}"] = (3 + 1) * nm.TCB
        else:
            sizes["WCH0"] = (3 * self.gmax + 1) * nm.TCB
        self.nclr = C + C * len(near)
        for name, n in sorted(sizes.items(), key=lambda x: -x[1]):
            even = name.startswith("SLOT")
            r = next((r for r in ("R1", "R3", "R2", "RX") if rg.spare()[r] >= n + 1), None)
            if r is None:
                raise SystemExit(f"no room for {name} ({n} words): {rg.spare()}")
            alloc[name] = rg.take(r, n, even=even)
        self.alloc = alloc
        self.slot = [alloc["SLOT0"], alloc["SLOT1"]]
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
        v.update(SAVE=alloc["SAVE"], REP=self.rep, SLOTTAB=alloc["SLOTTAB"], NSLOTS=slots, IN=alloc["IN"],
                 X=alloc["X"], HS=alloc["HS"], TABLE=0, NLAYERS=NL, JOBS=alloc["JOBS"],
                 ROWM1=alloc["ROWM1"], LBROW0=self.lb[0], LBSUM=self.lb[0] + self.lb[1],
                 NJOBS=nj, CLR=alloc["CLR"], NCLR=self.nclr, DRIVE_TAB=alloc["DRIVE_TAB"],
                 FADE_TAB=alloc["FADE_TAB"], EQ_TAB=self.eq_tab, STOMP_GAIN=self.stomp_gain, COLD_PM=self.cold_pm,
                 WBUF=self.wbuf, HEADL=nm.HEADL, LBUF=self.sb[0], LBUF_N=2 * nm.SB_WORDS, LCH=alloc["LCH"],
                 LCH_CP=(alloc["LCH"] + nm.TCB_II) & 0x7FFFF, FARTAB=alloc["FARTAB"], WADDR=alloc["WADDR"],
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
                 HFLAG=self.fflags[1], SIL_N=SIL, N_WEIGHTS=nam_lite.N_WEIGHTS, BUFT=alloc["BUFT"],
                 DMAC1=DMAC1, CPEP1=CPEP1, EP1IMSK=EP1IMSK, DIAG=b3 + 13, DCNT=b3 + 14, DCAUSE=b3 + 15)
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
        put(al["ROWM1"], r_1[T3["T_NXO"]:T3["T_NXO"] + 4])
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
        put(al["FARTAB"], [al["FTAB"] + FT_SIZE * j for j in range(F)])
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
        else:
            t = []
            for m in range(3 * self.gmax):
                jj, c = divmod(m, 3)
                t += tcb(al["WCH0"] + nm.TCB * (m + 1) + nm.TCB_II, 16, al["OUTBUF"] + 48 * jj + 16 * c)
            t += tcb(0, 1, 0)
            put(al["WCH0"], t)
        buft = []
        for b in range(2):
            ch = al[f"FCH{b}"]
            put(ch, tcb(ch + nm.TCB + nm.TCB_II, T_SIZE3, self.lb[b]) +
                tcb(ch + 2 * nm.TCB + nm.TCB_II, 0, self.lb[b] + T_SIZE3) + tcb(0, 1, self.fflags[b]))
            buft += [ch, self.fflags[b], (ch + nm.TCB_II) & 0x7FFFF]
        put(al["BUFT"], buft)
        put(al["LCH"], tcb(al["LCH"] + nm.TCB + nm.TCB_II, 0, self.sb[0]) + tcb(0, 1, v["FLAGL"]))
        jobs = []
        for t_, j in self.queue:
            if t_ == "R":
                ch = (al["RCH0"], al["RCH1"])[j % 2]
                jobs += [0, 0 if j < 2 else 2 * j - 2, al["FTAB"] + FT_SIZE * j, ch, self.flags[j % 2],
                         (ch + nm.TCB_II) & 0x7FFFF, 0, 0]
            else:
                if WB == "sb":
                    ch = al[f"WCH{j % 2}"]
                    jobs += [1, 2 * j + 1, al["FARTAB"] + j, ch, al["WADDR"] + j, (ch + nm.TCB_II) & 0x7FFFF, 1, 0]
                else:
                    grp = self.groups[j]
                    ch = al["WCH0"]          # (a shorter group: its chain starts that many TCBs in)
                    ch += nm.TCB * 3 * (self.gmax - len(grp))
                    jobs += [1, 2 * grp[-1] + 1, al["FARTAB"] + grp[0], ch, al["WADDR"] + grp[0],
                             (ch + nm.TCB_II) & 0x7FFFF, len(grp), 0]
        put(al["JOBS"], jobs)
        put(self.eq_tab, nam_lite.eq_table())
        put(self.stomp_gain, [nam_pack.f2b(10.0 ** (nam_lite.STOMP_DBU / 20))])
        return mem

    def claims(self):
        return n2.Layout.claims(self) + [(DMAC1, DMAC1 + 1), (EIEP1, CPEP1 + 1)]

    def report(self):
        r = n2.Layout.report(self)
        r.pop("jobs", None)
        return r


def build(backoff=nm.BACKOFF_N, **kw):
    lay = Layout(backoff=backoff, **kw)
    src = kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(lay.v))
    secs, _ = sasm.assemble(src, "nam_floor4.asm")
    pm = [s for s in secs if s.kind == "pm"]
    assert pm[0].addr == lay.code_pm and len(pm[0].words) == lay.n_code
    mem = lay.words()
    lines = ["", "// ---- tables, written by nam_floor4.py ----"]
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


class Rig(nf.Rig):
    def __init__(self, asm, lay, seed=1, **dma):
        nf.REGIONS, r0 = REGIONS3, nf.REGIONS
        try:
            super().__init__(asm, lay, seed, **dma)
        finally:
            nf.REGIONS = r0
        self.allowed = lay.claims()[:5]
        self.dma1 = ChainDma1(self.sim, **{k: v for k, v in dma.items() if k in TIMING})

    def call(self, inst, block, label):
        out = super().call(inst, block, label)
        self.dma1.advance()
        if self.dma1.active:
            raise nm.CheckFailed(f"{label}: returns with channel 1 running")
        sd = (inst.sdram, inst.sdram + self.lay.sdram_words())
        tr = (self.lay.alloc["TROWS"], self.lay.ddr2_to)
        for out_, ei, ii, n, em, im in self.dma1.log:
            ext_ok = sd[0] <= ei and ei + n <= sd[1] or tr[0] <= ei and ei + n <= tr[1]
            if out_ or not ext_ok or not any(a <= ii and ii + n <= b
                                                                         for a, b in self.allowed):
                raise nm.CheckFailed(f"{label}: a channel 1 TCB from {ei:#x} ({n}) to {ii:#x} is out of bounds")
        self.dma1.log.clear()
        return out


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
