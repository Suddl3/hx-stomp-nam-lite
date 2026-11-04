#!/usr/bin/env python3
"""NAM A2 Lite kernel for two NAM blocks per Floor DSP on the test2c memory (DESIGN_2NAM.md).

Builds on floor/nam_floor.py (its asm patches and rig) and adds:
- weights streamed per layer: a model load writes the whole stream (scaled, forward) to the
  instance's SDRAM block at W_OFF and copies only its header (rechannel, head, scale: 53 words)
  and silence state (72) into the slot; each layer's weights come into one of two on-chip layer
  buffers (LB0, LB1) by a new DMA job type (2) in the existing queue, one layer ahead;
- the near layers' copy into WBUF goes (they read the layer buffer), WBUF becomes LB1 for the head;
- EVENTS counts every layer computed (not only far ones), and the queue is ordered by when each
  job may start (its buffer free) under that count.

Phase 1 (this file now): TABLE stays on chip. Memory beyond the test2c regions spills into RX,
a simulator-only region, so the report shows exactly how much more must be trimmed.

usage: nam_floor2.py [--check]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nam_floor as nf  # noqa: E402
from nam_floor import nm, nam_lite, nam_pack, sasm, C, NL, KERNEL, DILATION, FAR_D  # noqa: E402

REGIONS2 = {
    "R3": (0x9b6b1, 0x9ba5f),       # Block 0: heap a's tail after test2c
    "R1": (0xe729a, 0xe8000),       # Block 3: the free tail
    "R2": (0xe6624, 0xe674a),       # Block 3: heap b's tail after test2c
    "RX": (0x9c600, 0x9e000),       # SIMULATOR ONLY: overflow, must end up empty
}
HEAP_A2, HEAP_B2 = (0x96BA4, 0x9b6b1), (0xE4466, 0xe6624)
HDR = 53                            # stream words kept on chip: rechannel 3, head 49, scale 1
SIL = C * (1 + NL)                  # the silence state, kept on chip after the header
LB_N = 156                          # a layer's weights (k = 15: 153), rounded to 4
NLB = 3                             # layer buffers: a fetch may run NLB - 1 layers ahead
T2 = dict(nm.T, T_FPOS=17, T_LB=18)
T_SIZE2 = 19


def lw(k):
    return 2 * C + k * C * C + 4 * C


PATCHES2 = [
    # the layer loop waits for its weights first (lwait calls pump)
    ("""    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;""", """    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL lwait;"""),
    # every layer computed counts (the fetch jobs wait on near layers too)
    ("""      IF NE R0 = R0 + R1;
      DM(EVENTS) = R0;
n_layer:""", """      R0 = R0 + R1;
      DM(EVENTS) = R0;
n_layer:"""),
    # job type 2: a layer's weights from the instance's SDRAM into its layer buffer
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
    R1 = DM(G_SDR);
    R2 = DM(J_N, I5);                   // W_OFF + the layer's offset in the stream
    R1 = R1 + R2;
    DM(TCB_EI, I0) = R1;
    R1 = DM(J_ROW, I5);                 // its word count
    DM(TCB_IC, I0) = R1;
    R1 = DM(G_SDR);                     // the sentinel TCB: MAGIC from SENT into the flag
    R2 = SENT_OFF;
    R1 = R1 + R2;
    DM(TCB_EI + 6, I0) = R1;
    I0 = DM(J_FLAG, I5);
    R1 = 0;
    DM(0, I0) = R1;
    R1 = I0;
    DM(J_CHKADR) = R1;
    R1 = MAGIC;
    DM(J_CHKVAL) = R1;
    R0 = 0;                             // external -> internal
    JUMP p_go;

// Wait (bounded) for this layer's weights (job J_DONE > T_FPOS).
lwait:
    R9 = POLLMAX;
lw_l: CALL pump;
    R0 = DM(J_DONE);
    R1 = DM(T_FPOS, I4);
    COMP(R0, R1);
    IF GT RTS;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE RTS;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP lw_l;
    JUMP dma_abort;

// Wait (bounded) for this far layer's taps"""),
    # a model load: the stream to the instance's SDRAM ...
    ("""    R0 = I6;
    R1 = S_STREAM;
    R0 = R0 + R1;
    I4 = R0;                            // where they go""", """    R0 = DM(G_SDR);
    R1 = W_OFF;
    R0 = R0 + R1;
    I4 = R0;                            // where they go: the instance's SDRAM"""),
    # ... then its header and silence state into the slot
    ("""    IF LT JUMP ld_chunk;
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
    LCNTR = HDR, DO ld_h UNTIL LCE;
      R1 = DM(I5, 1);
ld_h: DM(I3, 1) = R1;
    R0 = N_WEIGHTS - HDR;
    M2 = R0;
    MODIFY(I5, M2);
    LCNTR = SIL_N, DO ld_s UNTIL LCE;
      R1 = DM(I5, 1);
ld_s: DM(I3, 1) = R1;"""),
]


def patch_layer_weights(src):
    """The layer's weights: from its layer buffer, no copy into WBUF."""
    a = src.index("      R15 = DM(T_WT, I4);               // this layer's weights")
    b = src.index("n_wfar:\n", a)
    return src[:a] + "      I9 = DM(T_LB, I4);                // this layer's weights, fetched\n" \
                     "      M8 = DM(T_NW, I4);\n" + src[b:]


def kernel_src():
    src = nf.kernel_src()
    for a, b in PATCHES2:
        assert src.count(a) == 1, a[:70]
        src = src.replace(a, b)
    return patch_layer_weights(src)


def names():
    return nf.names() + ["T_FPOS", "T_LB", "W_OFF", "HDR", "SIL_N", "N_WEIGHTS"]


def equs(v):
    return "".join(f".equ {k}, {v[k]:#x}\n" for k in names())


def code_sizes():
    v = {k: 0 for k in names()}
    secs, _ = sasm.assemble(kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(v)),
                            "nam_floor2.asm")
    pm = [len(s.words) for s in secs if s.kind == "pm"]
    return pm[0], sum(pm[1:])


class Regions(nf.Regions):
    def __init__(self):
        self.free = {k: list(v) for k, v in REGIONS2.items()}


def queue_and_events(far, groups, nlb=None):
    """The job queue in start order and each job's start threshold under the new EVENTS
    (+1 when a far layer has its newest tap, +1 when any layer is computed)."""
    ev, done, fc = 0, {}, {}
    for i in range(NL):
        if i in far:
            ev += 1
            fc[i] = ev
        ev += 1
        done[i] = ev
    nlb = NLB if nlb is None else nlb
    jobs = []                                   # (threshold, need order, kind, index)
    for i in range(NL):                         # F i: layer i's weights into LB[i % NLB]
        jobs.append((0 if i < nlb else done[i - nlb], (i, 0), "F", i))
    for j, i in enumerate(far):                 # R j: far layer j's taps into SB[j % 2]
        jobs.append((0 if j < 2 else done[far[j - 2]], (i, 1), "R", j))
    for g, grp in enumerate(groups):            # W g: the group's write-back, after its last fcopy
        jobs.append((fc[far[grp[-1]]], (far[grp[-1]], 2), "W", g))
    jobs.sort(key=lambda x: (x[0], x[1]))
    return jobs


class Layout(nf.Layout):
    def __init__(self, backoff=nm.BACKOFF_N, inst_bounds=None, tables_base=None):
        slots = self.slots = 2
        self.far_d, self.staging = FAR_D, "b3"
        self.n_code, self.n_cold = code_sizes()
        self.far = [i for i, (k, d) in enumerate(zip(KERNEL, DILATION)) if k == 6 and d >= FAR_D]
        F = self.nfar = len(self.far)
        self.groups = []
        for j, i in enumerate(self.far):
            if j and i == self.far[j - 1] + 1:
                self.groups[-1].append(j)
            else:
                self.groups.append([j])
        self.jobs = queue_and_events(self.far, self.groups)
        self.queue = [(k, j) for _, _, k, j in self.jobs]
        self.ring = [(k - 1) * d + 16 for k, d in zip(KERNEL, DILATION)]
        self.nring = [L + (L & 1) for L in self.ring]
        near = [i for i in range(NL) if i not in self.far]
        v = {k: x for k, x in list(nm.S.items()) + list(nm.ST.items()) + list(nm.REPW.items()) + list(T2.items())
             + list(nm.J.items()) + list(nm.P.items())}
        v["ST_SIL"] = HDR
        rg = self.rg = Regions()
        rg.free["R3"][0] += nf.GUARD
        rg.free["R2"][0] += nf.GUARD
        # code: hot at R1's start (48-bit, even), cold at the top of R1
        r1 = REGIONS2["R1"][0]
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
        # the slot cores: state, header + silence, heads, ring pointers
        h0 = nm.S_STREAM + HDR + SIL
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
        # everything else, largest first, first fit (R2 last: Block 3, PM side)
        alloc = {}
        nj = len(self.queue)
        sizes = dict(FLAGREP=32, SAVE=64, SLOTTAB=slots, IN=16, X=48, HS=48, LB=NLB * LB_N, SB=2 * nm.SB_WORDS,
                     OUTBUF=48 * F, RCH0=16 * nm.TCB, RCH1=16 * nm.TCB, LCH=2 * nm.TCB, JOBS=nj * nm.JOB,
                     TABLE=NL * T_SIZE2, FARTAB=F, WADDR=F, **{f"FCH{b}": 2 * nm.TCB for b in range(NLB)},
                     SLOT0=self.slot_size, SLOT1=self.slot_size)
        for g, grp in enumerate(self.groups):
            sizes[f"WCH{g}"] = (3 * len(grp) + 1) * nm.TCB
        self.nclr = C + C * len(near)
        for name, n in sorted(sizes.items(), key=lambda x: -x[1]):
            even = name.startswith("SLOT")
            r = next((r for r in ("R1", "R3", "R2", "RX") if rg.spare()[r] >= n + 1), None)
            if r is None:
                raise SystemExit(f"no room for {name} ({n} words): {rg.spare()}")
            alloc[name] = rg.take(r, n, even=even)
        self.alloc = alloc
        self.slot = [alloc["SLOT0"], alloc["SLOT1"]]
        self.lb = [alloc["LB"] + LB_N * b for b in range(NLB)]
        self.b3 = alloc["FLAGREP"]
        self.rep = self.b3 + 16
        b3 = self.b3
        g = dict(G_SDR=b3, G_LEVEL=b3 + 1, J_NEXT=b3 + 2, J_BUSY=b3 + 3, J_DONE=b3 + 4, EVENTS=b3 + 5,
                 DMA_FAIL=b3 + 6, J_CHKADR=b3 + 7, J_CHKVAL=b3 + 8, FLAGL=b3 + 9, G_JOBS=b3 + 12)
        self.flags = [b3 + 10, b3 + 11]
        self.fflags = [b3 + 13 + b for b in range(NLB)]
        assert NLB <= 3
        v.update(g)
        self.sb = [alloc["SB"], alloc["SB"] + nm.SB_WORDS]
        self.xhi_b2 = self.wbuf_b2 = False
        self.wbuf = self.lb[(NL - 1 + 1) % NLB] if NLB > 2 else self.lb[1]
        self.b2_to = self.b2_data = 0
        # SDRAM per instance: far rings, HIST, sentinels, then the stream
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
        for name, n in (("RPTAB", 3 * self.nrp), ("CLR", 3 * self.nclr), ("DRIVE_TAB", 101), ("FADE_TAB", 18)):
            alloc[name] = a
            a += n
        self.ddr2_to = a
        (dlo, dhi), (plo, phi) = inst_bounds or (HEAP_A2, HEAP_B2)
        v.update(SAVE=alloc["SAVE"], REP=self.rep, SLOTTAB=alloc["SLOTTAB"], NSLOTS=slots, IN=alloc["IN"],
                 X=alloc["X"], HS=alloc["HS"], TABLE=alloc["TABLE"], NLAYERS=NL, JOBS=alloc["JOBS"],
                 NJOBS=nj, CLR=alloc["CLR"], NCLR=self.nclr, DRIVE_TAB=alloc["DRIVE_TAB"],
                 FADE_TAB=alloc["FADE_TAB"], EQ_TAB=self.eq_tab, STOMP_GAIN=self.stomp_gain, COLD_PM=self.cold_pm,
                 WBUF=self.wbuf, HEADL=nm.HEADL, LBUF=self.sb[0], LBUF_N=2 * nm.SB_WORDS, LCH=alloc["LCH"],
                 LCH_CP=(alloc["LCH"] + nm.TCB_II) & 0x7FFFF, FARTAB=alloc["FARTAB"], WADDR=alloc["WADDR"],
                 NFAR=F, S_STREAM=nm.S_STREAM, S_HB0=self.hb[0], S_HB1=self.hb[1], S_HB2=self.hb[2],
                 HIST_OFF=self.hist_off, SENT_OFF=self.sent_off, SENT2_OFF=self.sent_off + 1,
                 SDR_NEED=self.sdr_need, MAGIC=nm.MAGIC, POLLMAX=nm.POLLMAX, LPOLLMAX=nm.LPOLLMAX,
                 BACKOFF_N=backoff, T_MAX=nm.T_MAX, N_STREAM=nm.N_STREAM, KM1=5, T_SIZE=T_SIZE2,
                 TCB_EI=nm.TCB_EI, TCB_IC=nm.TCB_IC, TCB_II=nm.TCB_II, IR_FLAG=nm.IR_FLAG, IR_TOP=nm.IR_TOP,
                 DMAC0=nm.DMAC0, EIEP0=nm.EIEP0, EMEP0=nm.EMEP0, ICEP0=nm.ICEP0, IIEP0=nm.IIEP0, IMEP0=nm.IMEP0,
                 CPEP0=nm.CPEP0, DFLSH=nm.DFLSH, DEN_CHEN=nm.DEN | nm.CHEN, TRAN=nm.TRAN,
                 BUSYM=nm.DEN | nm.DMAS | nm.CHS | nm.EXTS, EXTSM=nm.EXTS, EP0IMSK=nm.EP0IMSK, HXK_ENTRY_INST=2,
                 HXK_INST_SDRAM=6, HXK_INST_SDRAM_END=7, CODE_PM=self.code_pm, RPTAB=alloc["RPTAB"],
                 NRP=self.nrp, INST_DM=nf.INST_DM, INST_PM=nf.INST_PM, INST_DM_LO=dlo, INST_DM_HI=dhi,
                 INST_PM_LO=plo, INST_PM_HI=phi, INST_DM_NEED=self.inst_dm_need, INST_PM_NEED=self.inst_pm_need,
                 W_OFF=self.w_off, HDR=HDR, SIL_N=SIL, N_WEIGHTS=nam_lite.N_WEIGHTS)
        self.v = v
        self.b3_to = None

    def words(self):
        """nam_floor's tables with: 19-word TABLE rows (T_FPOS, T_LB; T_SIL on the slot's
        silence after the header), the new queue, the fetch chains."""
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
        pos = {(k, j): q for q, (k, j) in enumerate(self.queue)}
        tab = []
        for i, (k, d) in enumerate(zip(KERNEL, DILATION)):
            row = [0] * T_SIZE2
            row[T2["T_LW"]] = nm.S["S_LW"] + i
            row[T2["T_K"]] = k
            row[T2["T_KD"]] = -(k - 1) * d
            row[T2["T_D"]] = d
            row[T2["T_NW"]] = -lw(k)
            row[T2["T_FPOS"]] = pos[("F", i)]
            row[T2["T_LB"]] = self.lb[i % NLB]
            if i in self.far:
                j = self.far.index(i)
                L = self.lp[i]
                row[T2["T_RB"]] = self.far_off[i]
                row[T2["T_STRIDE"]] = L + 16
                row[T2["T_L"]] = L
                row[T2["T_S"]] = 16
                row[T2["T_KS"]] = -(k - 1) * 16
                row[T2["T_FAR"]] = j + 1
                row[T2["T_RPOS"]] = pos[("R", j)]
                row[T2["T_SB"]] = self.sb[j % 2]
                row[T2["T_OB"]] = al["OUTBUF"] + 48 * j
                row[T2["T_WA"]] = al["WADDR"] + j
                row[T2["T_SIL"]] = nm.S_STREAM + HDR + C + C * i
            else:
                L = self.nring[i]
                row[T2["T_RB"]] = self.s_rp + self.rp_index[i]
                row[T2["T_STRIDE"]] = L + 2
                row[T2["T_L"]] = L
                row[T2["T_S"]] = d
                row[T2["T_KS"]] = -(k - 1) * d
            tab += row
        put(al["TABLE"], tab)
        put(al["FARTAB"], [al["TABLE"] + T_SIZE2 * i for i in self.far])
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
        for g, grp in enumerate(self.groups):
            t = []
            for m in range(3 * len(grp)):
                jj, c = divmod(m, 3)
                t += tcb(al[f"WCH{g}"] + nm.TCB * (m + 1) + nm.TCB_II, 16, al["OUTBUF"] + 48 * grp[jj] + 16 * c)
            t += tcb(0, 1, 0)
            put(al[f"WCH{g}"], t)
        for b, ch in enumerate(al[f"FCH{b}"] for b in range(NLB)):
            put(ch, tcb(ch + nm.TCB + nm.TCB_II, 0, self.lb[b]) + tcb(0, 1, self.fflags[b]))
        put(al["LCH"], tcb(al["LCH"] + nm.TCB + nm.TCB_II, 0, self.sb[0]) + tcb(0, 1, v["FLAGL"]))
        jobs = []
        for thr, _, kind, j in self.jobs:
            if kind == "R":
                ch = (al["RCH0"], al["RCH1"])[j % 2]
                jobs += [0, thr, al["TABLE"] + T_SIZE2 * self.far[j], ch, self.flags[j % 2],
                         (ch + nm.TCB_II) & 0x7FFFF, 0, 0]
            elif kind == "W":
                grp = self.groups[j]
                jobs += [1, thr, al["FARTAB"] + grp[0], al[f"WCH{j}"], al["WADDR"] + grp[0],
                         (al[f"WCH{j}"] + nm.TCB_II) & 0x7FFFF, len(grp), 0]
            else:
                ch = al[f"FCH{j % NLB}"]
                jobs += [2, thr, lw(KERNEL[j]), ch, self.fflags[j % NLB], (ch + nm.TCB_II) & 0x7FFFF,
                         self.w_off + wo[j], 0]
        put(al["JOBS"], jobs)
        put(self.eq_tab, nam_lite.eq_table())
        put(self.stomp_gain, [nam_pack.f2b(10.0 ** (nam_lite.STOMP_DBU / 20))])
        return mem

    def claims(self):
        sb = (self.sb[0], self.sb[0] + 2 * nm.SB_WORDS)
        return [sb] + list(REGIONS2.values()) + [(self.eq_tab, self.ddr2_to), (nm.DMAC0, nm.DMAC0 + 1),
                                                 (nm.EIEP0, nm.CPEP0 + 1)]

    def report(self):
        sp = self.rg.spare()
        used_rx = REGIONS2["RX"][1] - REGIONS2["RX"][0] - sp["RX"]
        return {"code": f"hot {self.n_code} instr at PM {self.code_pm:#x}, cold {self.n_cold} at {self.cold_pm:#x}",
                "slots": [hex(s) for s in self.slot], "slot words": self.slot_size, "jobs": len(self.queue),
                "instance DM words": self.inst_dm_need, "instance PM words": self.inst_pm_need,
                "spare": {k: sp[k] for k in ("R3", "R1", "R2")}, "OVER (in RX)": used_rx,
                "sdram words": self.sdr_need}


def build(backoff=nm.BACKOFF_N, **kw):
    lay = Layout(backoff=backoff, **kw)
    src = kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(lay.v))
    secs, _ = sasm.assemble(src, "nam_floor2.asm")
    pm = [s for s in secs if s.kind == "pm"]
    assert pm[0].addr == lay.code_pm and len(pm[0].words) == lay.n_code
    mem = lay.words()
    lines = ["", "// ---- tables, written by nam_floor2.py ----"]
    last = None
    for a in sorted(mem):
        if a != (last or 0) + 1:
            lines.append(f".section dm {a:#x}")
        lines.append(f"    .word {mem[a]:#010x}")
        last = a
    return src + "\n".join(lines) + "\n", lay


class Rig(nf.Rig):
    def __init__(self, asm, lay, seed=1, **dma):
        nf.REGIONS, r0 = REGIONS2, nf.REGIONS
        try:
            super().__init__(asm, lay, seed, **dma)
        finally:
            nf.REGIONS = r0
        self.allowed = lay.claims()[:5]                 # staging + R3, R1, R2, RX


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
    print("queue:", " ".join(f"{k}{j}@{t}" for t, _, k, j in lay.jobs))
    if "--check" in sys.argv:
        asm, lay = build(inst_bounds=RIG_BOUNDS)
        ok, res, _ = check(asm, lay, nam_lite.placeholder())
        print("check:", "PASS" if ok else "FAIL", res)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
