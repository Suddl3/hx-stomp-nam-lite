#!/usr/bin/env python3
"""NAM A2 Lite's multi-block kernel (upstream tools/sharc/nam_multi.py) laid out for the
Helix Floor's DSP memory, 13-block layout (floor-port-findings.md, "Floor memory plan").

The upstream kernel keeps everything in one run of Block 3 plus its hot code in Block 2.
The Floor has no such run: after deleting 1 big and 2 normal block slots per DSP the
free on-chip memory is three regions (R3 in Block 0, R1 and R2 in Block 3). So:

- every global table, the two slots' cores and the code are packed into those regions;
- a slot's core is its state, its model stream and its heads (2,130 words);
- the near rings (1,704 words a slot) live in the owning instance's own memory, the
  amp placeholder's DM and PM blocks (I0 + 145 .., I8 + 13 ..), reached through a
  per-slot pointer table (S_RP) that m_init fills when an instance takes the slot.

Kernel changes (asm patched from upstream, see PATCHES): the hot code's address is an
.equ; the near layers read their ring base from S_RP; m_init fills S_RP from RPTAB;
the model load's ring clear reads its bases through S_RP (CLR word 0: rp << 16 | add).

usage: nam_floor.py [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import SHARC as UP  # noqa: E402
sys.path.insert(0, UP)
import nam_multi as nm  # noqa: E402
import nam_lite  # noqa: E402
import nam_pack  # noqa: E402
import sasm  # noqa: E402

C, NL, KERNEL, DILATION = nm.C, nm.NL, nm.KERNEL, nm.DILATION
FAR_D = 17

# The freed static regions of one Floor DSP (normal words, [start, end)).
REGIONS = {
    "R3": (0x9ba5f - 0xeb8, 0x9ba5f),     # Block 0: heap a's tail (1 big + 2 normal slots' DM)
    "R1": (0xe729a, 0xe8000),             # Block 3: the free tail above the stock data
    "R2": (0xe674a - 0x6d8, 0xe674a),     # Block 3: heap b's tail (1 big + 2 normal slots' PM)
}
INST_DM, INST_PM = 145, 13                # what the instance blocks already hold (I0, I8)
GUARD = 16                                # words left free right after each shrunk heap's new end
HEAP_A, HEAP_B = (0x96BA4, 0x9BA5F - 0xEB8), (0xE4466, 0xE674A - 0x6D8)   # after stage_slots: the
#                                           amp placeholder's DM and PM blocks come from these
PLACE_DM, PLACE_PM = 0x596, 0x1FA         # the amp placeholder's budgets (the instance's blocks)
DM_LAYERS = (15, 0, 1, 2, 7, 8, 9)        # near rings in the instance's DM block
PM_LAYERS = (16, 17, 18, 14)              # and in its PM block
FLOOR_IR_FLAG, FLOOR_IR_TOP = 0x2AF982, 0x2B0201
FLOOR_DDR2, FLOOR_DDR2_END = 0x325E00, 0x328000   # after Heap 6's new place (stage_model.HEAP6_NEW), below heap c
# The Floor's addresses for everything upstream keeps as module constants (the check uses them too)
nm.IR_FLAG, nm.IR_TOP, nm.DDR2, nm.DDR2_END = FLOOR_IR_FLAG, FLOOR_IR_TOP, FLOOR_DDR2, FLOOR_DDR2_END

# ------------------------------------------------------------------ the asm patches
PATCHES = [
    # m_init first checks that the instance's DM block (I0) and PM block (I8 at entry) lie
    # where the amp placeholder's memory comes from (heap a / heap b on the unit); if not, it
    # returns at once with S_INIT still 0 and the caller plays silence (nothing written).
    ("""// ---- a slot's first call (and after a failure): its state, sentinels, HIST
m_init:
""", """// ---- a slot's first call (and after a failure): its state, sentinels, HIST
m_init:
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
"""),
    ("""    CALL m_init;

m_ready:""", """    CALL m_init;
    R0 = DM(S_INIT, I6);
    R0 = PASS R0;
    IF EQ JUMP m_silent;

m_ready:"""),
    (".section pm 0x0c4ef8\n", ".section pm CODE_PM\n"),
    # near layer: the ring base from the slot's pointer table, not slot + offset (twice)
    ("""      R10 = DM(T_RB, I4);
      R0 = I6;
      R10 = R10 + R0;
      R9 = DM(T_STRIDE, I4);""",
     """      M4 = DM(T_RB, I4);
      R10 = DM(M4, I6);
      R9 = DM(T_STRIDE, I4);"""),
    ("""      M0 = DM(T_KD, I4);
      R10 = DM(T_RB, I4);
      R0 = I6;
      R10 = R10 + R0;""",
     """      M0 = DM(T_KD, I4);
      M4 = DM(T_RB, I4);
      R10 = DM(M4, I6);"""),
    # the ring clear: word 0 = (the slot's pointer word) << 16 | the offset from it
    ("""    LCNTR = NCLR, DO ld_clr UNTIL LCE;
      R1 = DM(0, I4);
      R1 = R1 + R11;
      I3 = R1;""",
     """    R4 = 0xFFFF;
    LCNTR = NCLR, DO ld_clr UNTIL LCE;
      R1 = DM(0, I4);
      R2 = LSHIFT R1 BY -16;
      R2 = R2 + R11;
      I3 = R2;
      R2 = DM(0, I3);
      R1 = R1 AND R4;
      R1 = R1 + R2;
      I3 = R1;"""),
    # m_init: the slot's ring pointers, for the instance that has it now
    ("""mi_hist: DM(I5, 1) = R2;
    R0 = 1;
    DM(S_INIT, I6) = R0;
    RTS;""",
     """mi_hist: DM(I5, 1) = R2;
    R3 = I0;                            // the instance's DM block, past its own words, even
    R1 = INST_DM + 1;
    R3 = R3 + R1;
    R3 = BCLR R3 BY 0;
    R4 = DM(SAVE + 46);                 // its PM block (I8 at entry), the same
    R1 = INST_PM + 1;
    R4 = R4 + R1;
    R4 = BCLR R4 BY 0;
    R5 = I6;
    I4 = RPTAB;
    LCNTR = NRP, DO mi_rp UNTIL LCE;
      R1 = DM(1, I4);                   // 0: the slot, 1: the DM block, 2: the PM block
      R2 = PASS R5;
      R1 = R1 - 1;
      IF EQ R2 = PASS R3;
      R1 = R1 - 1;
      IF EQ R2 = PASS R4;
      R1 = DM(2, I4);
      R2 = R2 + R1;
      R1 = DM(0, I4);
      R1 = R1 + R5;
      I5 = R1;
      DM(0, I5) = R2;
mi_rp: MODIFY(I4, 3);
    R0 = 1;
    DM(S_INIT, I6) = R0;
    RTS;"""),
]


def kernel_src():
    src = open(os.path.join(UP, "nam_multi_kernel.asm")).read()
    for a, b in PATCHES:
        assert src.count(a) == 1, a[:60]
        src = src.replace(a, b)
    return src


def names():
    return nm.names() + ["CODE_PM", "RPTAB", "NRP", "INST_DM", "INST_PM", "INST_DM_LO", "INST_DM_HI",
                         "INST_DM_NEED", "INST_PM_LO", "INST_PM_HI", "INST_PM_NEED"]


def equs(v):
    return "".join(f".equ {k}, {v[k]:#x}\n" for k in names())


def code_sizes():
    v = {k: 0 for k in names()}
    secs, _ = sasm.assemble(kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(v)),
                            "nam_floor.asm")
    pm = [len(s.words) for s in secs if s.kind == "pm"]
    return pm[0], sum(pm[1:])


def nw(n):
    """Normal words that n instructions take."""
    return -(-(n + (n & 1)) * 3 // 2)


class Regions:
    def __init__(self):
        self.free = {k: list(v) for k, v in REGIONS.items()}

    def take(self, r, n, even=False):
        a = self.free[r][0]
        if even:
            a += a & 1
        if a + n > self.free[r][1]:
            raise SystemExit(f"{r} is full: {n} words at {a:#x}, ends {self.free[r][1]:#x}")
        self.free[r][0] = a + n
        return a

    def take_top(self, r, n):
        b = self.free[r][1] - n
        if b < self.free[r][0]:
            raise SystemExit(f"{r} is full at the top: {n} words")
        self.free[r][1] = b
        return b

    def spare(self):
        return {k: v[1] - v[0] for k, v in self.free.items()}


class Layout(nm.Layout):
    """nm.Layout's fields and tables, at the Floor's addresses (2 slots, far_d 17)."""

    def __init__(self, n_code=None, n_cold=None, backoff=nm.BACKOFF_N, tables_base=None, inst_bounds=None):
        """tables_base: where the read-only tables go (the tone stack's, STOMP_GAIN, RPTAB, CLR,
        DRIVE_TAB, FADE_TAB); default nm.DDR2. inst_bounds: ((DM lo, hi), (PM lo, hi)) an
        instance's blocks must lie in; default heap a and heap b."""
        slots = self.slots = 2
        self.far_d, self.staging = FAR_D, "b3"
        hot, cold = code_sizes()
        self.n_code = hot if n_code is None else n_code
        self.n_cold = cold if n_cold is None else n_cold
        self.far = [i for i, (k, d) in enumerate(zip(KERNEL, DILATION)) if k == 6 and d >= FAR_D]
        F = self.nfar = len(self.far)
        self.groups = []
        for j, i in enumerate(self.far):
            if j and i == self.far[j - 1] + 1:
                self.groups[-1].append(j)
            else:
                self.groups.append([j])
        self.queue = []
        first = {grp[0]: g for g, grp in enumerate(self.groups)}
        for j in range(F):
            self.queue.append(("R", j))
            if j in first and first[j] > 0:
                self.queue.append(("W", first[j] - 1))
        self.queue.append(("W", len(self.groups) - 1))
        self.ring = [(k - 1) * d + 16 for k, d in zip(KERNEL, DILATION)]
        self.nring = [L + (L & 1) for L in self.ring]
        near = [i for i in range(NL) if i not in self.far]
        assert sorted(near) == sorted(DM_LAYERS + PM_LAYERS)
        v = {k: x for k, x in list(nm.S.items()) + list(nm.ST.items()) + list(nm.REPW.items()) + list(nm.T.items())
             + list(nm.J.items()) + list(nm.P.items())}
        rg = self.rg = Regions()
        rg.free["R3"][0] += GUARD
        # the code: hot alone at R2's start past the guard (48-bit, even), cold at the top of R1
        r2 = REGIONS["R2"][0] + GUARD
        pm = nm.NW3 + -(-(r2 - nm.NW3) * 2 // 3)
        pm += pm & 1
        self.code_pm = pm
        code_nw = nm.NW3 + (pm - nm.NW3) * 3 // 2
        rg.free["R2"][0] = code_nw + nw(self.n_code)
        assert rg.free["R2"][0] <= REGIONS["R2"][1], "the hot code does not fit R2"
        cw = nw(self.n_cold)
        assert REGIONS["R1"][1] == nm.B3_END
        cpm = nm.NW3 + (nm.COLD_END - cw - nm.NW3) * 2 // 3
        self.cold_pm = cpm - (cpm & 1)
        self.cold_nw = nm.NW3 + (self.cold_pm - nm.NW3) * 3 // 2
        rg.free["R1"][1] = self.cold_nw
        # the slot cores: state, stream, heads, ring pointers
        h0 = nm.S_STREAM + nm.N_STREAM
        h0 += h0 & 1
        self.hb = [h0 + (nm.HEADL + 2) * j for j in range(C)]
        self.s_rp = self.hb[-1] + nm.HEADL + 2
        self.rp_index = {i: j for j, i in enumerate(sorted(near))}
        self.nrp = len(near) + 1                         # + the slot itself (the heads' clear)
        o = self.s_rp + self.nrp
        o += o & 1
        self.slot_size = o
        self.slot = [rg.take("R3", o, even=True), rg.take("R1", o, even=True)]
        # the near rings, in the instance's blocks: (block, offset from its even base)
        self.near_at, off = {}, {1: 0, 2: 0}
        for sel, layers in ((1, DM_LAYERS), (2, PM_LAYERS)):
            for i in layers:
                self.near_at[i] = (sel, off[sel])
                off[sel] += C * (self.nring[i] + 2)
        assert off[1] <= PLACE_DM - INST_DM - 1 and off[2] <= PLACE_PM - INST_PM - 1, off
        self.inst_dm_need, self.inst_pm_need = INST_DM + 1 + off[1], INST_PM + 1 + off[2]
        # the globals, largest first, first fit (flags + report as one 32-word run)
        alloc = {}
        sizes = dict(FLAGREP=32, SAVE=64, SLOTTAB=slots, IN=16, X=48, HS=48, WBUF=nm.WBUF_N, SB=2 * nm.SB_WORDS,
                     OUTBUF=48 * F, RCH0=16 * nm.TCB, RCH1=16 * nm.TCB, LCH=2 * nm.TCB, JOBS=(F + len(self.groups)) * nm.JOB,
                     TABLE=NL * nm.T_SIZE, FARTAB=F, WADDR=F)
        for g, grp in enumerate(self.groups):
            sizes[f"WCH{g}"] = (3 * len(grp) + 1) * nm.TCB
        self.nclr = C + C * len(near)
        for name, n in sorted(sizes.items(), key=lambda x: -x[1]):
            r = next((r for r in ("R1", "R3") if rg.spare()[r] >= n), None)
            if r is None:
                raise SystemExit(f"no room for {name} ({n} words): {rg.spare()}")
            alloc[name] = rg.take(r, n)
        self.alloc = alloc
        self.b3 = alloc["FLAGREP"]
        self.rep = self.b3 + 16
        b3 = self.b3
        g = dict(G_SDR=b3, G_LEVEL=b3 + 1, J_NEXT=b3 + 2, J_BUSY=b3 + 3, J_DONE=b3 + 4, EVENTS=b3 + 5,
                 DMA_FAIL=b3 + 6, J_CHKADR=b3 + 7, J_CHKVAL=b3 + 8, FLAGL=b3 + 9, G_JOBS=b3 + 12)
        self.flags = [b3 + 10, b3 + 11]
        v.update(g)
        self.sb = [alloc["SB"], alloc["SB"] + nm.SB_WORDS]
        self.xhi_b2 = self.wbuf_b2 = False
        self.wbuf = alloc["WBUF"]
        self.b2_to = self.b2_data = 0
        # SDRAM per instance and DDR2, as upstream
        self.lp = {i: nm.rup16(self.ring[i]) for i in self.far}
        o, self.far_off = 0, {}
        for i in self.far:
            self.far_off[i] = o
            o += C * (self.lp[i] + 16)
        self.hist_off = o
        self.sent_off = o + nm.HIST_N
        self.sdr_need = self.sent_off + 2
        # DDR2: the tone stack's table and STOMP_GAIN (as upstream), then the tables read only
        # at a slot's start or a model's load (RPTAB, CLR) or once a call (DRIVE_TAB, FADE_TAB)
        self.eq_tab = nm.DDR2 if tables_base is None else tables_base
        self.stomp_gain = self.eq_tab + 4 * 101 * 5
        a = self.stomp_gain + 1
        for name, n in (("RPTAB", 3 * self.nrp), ("CLR", 3 * self.nclr), ("DRIVE_TAB", 101), ("FADE_TAB", 18)):
            alloc[name] = a
            a += n
        self.ddr2_to = a
        assert tables_base is not None or self.ddr2_to <= nm.DDR2_END
        (dlo, dhi), (plo, phi) = inst_bounds or (HEAP_A, HEAP_B)
        v.update(SAVE=alloc["SAVE"], REP=self.rep, SLOTTAB=alloc["SLOTTAB"], NSLOTS=slots, IN=alloc["IN"],
                 X=alloc["X"], HS=alloc["HS"], TABLE=alloc["TABLE"], NLAYERS=NL, JOBS=alloc["JOBS"],
                 NJOBS=F + len(self.groups), CLR=alloc["CLR"], NCLR=self.nclr, DRIVE_TAB=alloc["DRIVE_TAB"],
                 FADE_TAB=alloc["FADE_TAB"], EQ_TAB=self.eq_tab, STOMP_GAIN=self.stomp_gain, COLD_PM=self.cold_pm,
                 WBUF=self.wbuf, HEADL=nm.HEADL, LBUF=self.sb[0], LBUF_N=2 * nm.SB_WORDS, LCH=alloc["LCH"],
                 LCH_CP=(alloc["LCH"] + nm.TCB_II) & 0x7FFFF, FARTAB=alloc["FARTAB"], WADDR=alloc["WADDR"],
                 NFAR=F, S_STREAM=nm.S_STREAM, S_HB0=self.hb[0], S_HB1=self.hb[1], S_HB2=self.hb[2],
                 HIST_OFF=self.hist_off, SENT_OFF=self.sent_off, SENT2_OFF=self.sent_off + 1,
                 SDR_NEED=self.sdr_need, MAGIC=nm.MAGIC, POLLMAX=nm.POLLMAX, LPOLLMAX=nm.LPOLLMAX,
                 BACKOFF_N=backoff, T_MAX=nm.T_MAX, N_STREAM=nm.N_STREAM, KM1=5, T_SIZE=nm.T_SIZE,
                 TCB_EI=nm.TCB_EI, TCB_IC=nm.TCB_IC, TCB_II=nm.TCB_II, IR_FLAG=nm.IR_FLAG, IR_TOP=nm.IR_TOP,
                 DMAC0=nm.DMAC0, EIEP0=nm.EIEP0, EMEP0=nm.EMEP0, ICEP0=nm.ICEP0, IIEP0=nm.IIEP0, IMEP0=nm.IMEP0,
                 CPEP0=nm.CPEP0, DFLSH=nm.DFLSH, DEN_CHEN=nm.DEN | nm.CHEN, TRAN=nm.TRAN,
                 BUSYM=nm.DEN | nm.DMAS | nm.CHS | nm.EXTS, EXTSM=nm.EXTS, EP0IMSK=nm.EP0IMSK, HXK_ENTRY_INST=2,
                 HXK_INST_SDRAM=6, HXK_INST_SDRAM_END=7, CODE_PM=self.code_pm, RPTAB=alloc["RPTAB"],
                 NRP=self.nrp, INST_DM=INST_DM, INST_PM=INST_PM, INST_DM_LO=dlo, INST_DM_HI=dhi,
                 INST_PM_LO=plo, INST_PM_HI=phi, INST_DM_NEED=self.inst_dm_need, INST_PM_NEED=self.inst_pm_need)
        self.v = v
        self.b3_to = None

    # ------------------------------------------------------------ the tables
    def words(self):
        v, al, F = self.v, self.alloc, self.nfar
        mem = {}

        def put(a, vals):
            for i, x in enumerate(vals):
                assert a + i not in mem, hex(a + i)
                mem[a + i] = x & 0xFFFFFFFF

        put(self.b3, [0] * 13)
        put(self.sb[0], [0] * (2 * nm.SB_WORDS))
        put(self.rep, [nm.MAGIC] + [0] * 15)
        put(al["SLOTTAB"], self.slot)
        for s in self.slot:
            put(s + nm.S["S_OWNER"], [0])
        wo = nm.stream_offsets()
        tab = []
        rpos = {self.far[j]: q for q, (t, j) in enumerate(self.queue) if t == "R"}
        for i, (k, d) in enumerate(zip(KERNEL, DILATION)):
            row = [0] * nm.T_SIZE
            row[nm.T["T_LW"]] = nm.S["S_LW"] + i
            row[nm.T["T_K"]] = k
            row[nm.T["T_WT"]] = nm.S_STREAM + wo[i]
            row[nm.T["T_KD"]] = -(k - 1) * d
            row[nm.T["T_D"]] = d
            row[nm.T["T_NW"]] = -(2 * C + k * C * C + 4 * C)
            if i in self.far:
                j = self.far.index(i)
                L = self.lp[i]
                row[nm.T["T_RB"]] = self.far_off[i]
                row[nm.T["T_STRIDE"]] = L + 16
                row[nm.T["T_L"]] = L
                row[nm.T["T_S"]] = 16
                row[nm.T["T_KS"]] = -(k - 1) * 16
                row[nm.T["T_FAR"]] = j + 1
                row[nm.T["T_RPOS"]] = rpos[i]
                row[nm.T["T_SB"]] = self.sb[j % 2]
                row[nm.T["T_OB"]] = al["OUTBUF"] + 48 * j
                row[nm.T["T_WA"]] = al["WADDR"] + j
                row[nm.T["T_SIL"]] = nm.S_STREAM + nam_lite.N_WEIGHTS + C + C * i
            else:
                L = self.nring[i]
                row[nm.T["T_RB"]] = self.s_rp + self.rp_index[i]     # the slot's pointer word
                row[nm.T["T_STRIDE"]] = L + 2
                row[nm.T["T_L"]] = L
                row[nm.T["T_S"]] = d
                row[nm.T["T_KS"]] = -(k - 1) * d
                steps = [-(k - 1) * d, 2 - 2 * d, 2 - d]
                assert all(abs(x) < L for x in steps), "a step as long as the ring"
            tab += row
        put(al["TABLE"], tab)
        put(al["FARTAB"], [al["TABLE"] + nm.T_SIZE * i for i in self.far])
        put(al["WADDR"], [0] * F)
        rp_slot = self.s_rp + self.nrp - 1                  # the pointer word holding the slot's base
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
        assert len(clr) == self.nclr
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
        put(al["LCH"], tcb(al["LCH"] + nm.TCB + nm.TCB_II, 0, self.sb[0]) + tcb(0, 1, v["FLAGL"]))
        jobs = []
        for t_, j in self.queue:
            if t_ == "R":
                ch = (al["RCH0"], al["RCH1"])[j % 2]
                jobs += [0, 0 if j < 2 else 2 * j - 2, al["TABLE"] + nm.T_SIZE * self.far[j], ch, self.flags[j % 2],
                         (ch + nm.TCB_II) & 0x7FFFF, 0, 0]
            else:
                grp = self.groups[j]
                jobs += [1, 2 * grp[-1] + 1, al["FARTAB"] + grp[0], al[f"WCH{j}"], al["WADDR"] + grp[0],
                         (al[f"WCH{j}"] + nm.TCB_II) & 0x7FFFF, len(grp), 0]
        put(al["JOBS"], jobs)
        put(self.eq_tab, nam_lite.eq_table())
        put(self.stomp_gain, [nam_pack.f2b(10.0 ** (nam_lite.STOMP_DBU / 20))])
        return mem

    def claims(self):
        """The ranges the kernel writes: staging first, then the regions (the check's DMA rule
        reads every range but the DDR2 and register ones), DDR2, the DMA registers."""
        sb = (self.sb[0], self.sb[0] + 2 * nm.SB_WORDS)
        return [sb] + list(REGIONS.values()) + [(self.eq_tab, self.ddr2_to), (nm.DMAC0, nm.DMAC0 + 1),
                                                (nm.EIEP0, nm.CPEP0 + 1)]

    def report(self):
        return {"code": f"hot {self.n_code} instr at PM {self.code_pm:#x}, cold {self.n_cold} at {self.cold_pm:#x}",
                "slots": [hex(s) for s in self.slot], "slot words": self.slot_size,
                "instance DM words": self.inst_dm_need, "instance PM words": self.inst_pm_need,
                "spare": self.rg.spare(), "sdram words": self.sdr_need}


def build(backoff=nm.BACKOFF_N, **kw):
    lay = Layout(backoff=backoff, **kw)
    src = kernel_src().replace("// EQUS (nam_multi.py puts the layout here)\n", equs(lay.v))
    secs, _ = sasm.assemble(src, "nam_floor.asm")
    pm = [s for s in secs if s.kind == "pm"]
    assert pm[0].addr == lay.code_pm and len(pm[0].words) == lay.n_code
    assert all(s.addr == lay.cold_pm for s in pm[1:]) and sum(len(s.words) for s in pm[1:]) == lay.n_cold
    mem = lay.words()
    lines = ["", "// ---- tables, written by nam_floor.py ----"]
    last = None
    for a in sorted(mem):
        if a != (last or 0) + 1:
            lines.append(f".section dm {a:#x}")
        lines.append(f"    .word {mem[a]:#010x}")
        last = a
    return src + "\n".join(lines) + "\n", lay


# ------------------------------------------------------------------ the check
class Rig(nm.Rig):
    """Upstream's rig with room for the rings in each instance's blocks, every region's
    unwritten words random at start, and DMA allowed into any region."""

    def __init__(self, asm, lay, seed=1, **dma):
        super().__init__(asm, lay, seed, **dma)
        secs, _ = sasm.assemble(asm, "nam_floor.asm")
        static = set()
        for s in secs:
            if s.kind == "dm":
                static.update(range(s.addr, s.addr + len(s.words)))
        for a, b in REGIONS.values():
            for x in range(a, b):
                if x not in static:
                    self.sim.dm[x] = self.rnd.getrandbits(32)
        self.allowed = lay.claims()[:4]

    def inst(self, name, k):
        """Instance k: DM blocks 0x600 apart (the placeholder's 0x596), PM blocks 0x200 apart."""
        return nm.Inst(self, name, 0xB3001 + 0x600 * k, 0x91001 + 0x200 * k, 0xB6000 + 0x40 * k,
                       0x400000 + 0x10000 * k, self.lay.sdram_words())

    def check_dma(self, inst, label):
        a0 = self.allowed
        self.allowed = [(a, b) for a, b in a0]
        try:
            sd = (inst.sdram, inst.sdram + self.lay.sdram_words())
            ir = (nm.IR_TOP - 0x800 + 1, nm.IR_TOP + 128 * 0x800)
            for out, ei, ii, n, em, im in self.dma.log:
                e0, e1 = sorted((ei, ei + (n - 1) * em))
                i0, i1 = sorted((ii, ii + (n - 1) * im))
                ok_e = sd[0] <= e0 and e1 < sd[1] or not out and ir[0] <= e0 and e1 < ir[1]
                ok_i = any(a <= i0 and i1 < b for a, b in self.allowed)
                if not (ok_e and ok_i):
                    raise nm.CheckFailed(f"{label}: a TCB {'to' if out else 'from'} {ei:#x} ({n} words) / internal "
                                         f"{ii:#x} is outside the instance's memory")
            self.dma.log.clear()
        finally:
            self.allowed = a0

    def rep(self):
        return [self.sim.rd(self.lay.rep + k) for k in range(16)]


def check(asm, lay, w, **kw):
    nm.Rig, rig0 = Rig, nm.Rig
    nm.REP = lay.rep                      # (KernelCheck's helpers read the report through nm.REP)
    try:
        return nm.check(asm, lay, w, **kw)
    finally:
        nm.Rig = rig0


RIG_BOUNDS = ((0xB3000, 0xB3000 + 0x600 * 16), (0x91000, 0x91000 + 0x200 * 16))   # Rig.inst's blocks


def check_bounds(asm, lay):
    """An instance whose DM block lies outside the allowed range plays silence and leaves the
    slot uninitialised; one inside plays. (The image built with the rig's bounds.)"""
    w = nam_lite.placeholder()
    sig = [[0.2 * ((i * 7) % 11 - 5) / 5 for i in range(16)] for _ in range(4)]
    sig = [[ssim_f2b(x) for x in blk] for blk in sig]
    outs = {}
    for name, i0 in (("inside", 0xB3001), ("outside", 0xA0001)):
        r = Rig(asm, lay)
        nm.set_ir(r.sim, 1, nam_lite.ir_samples(w, None))
        inst = nm.Inst(r, name, i0, 0x91001, 0xB6000, 0x400000, lay.sdram_words())
        inst.knobs(model=1)
        got = [inst.call(b, f"{name} {k}") for k, b in enumerate(sig)]
        outs[name] = (any(v for blk in got for v in blk), r.sim.rd(lay.slot[0] + nm.S["S_INIT"]))
    assert outs["outside"] == (False, 0), f"an out-of-range instance played or initialised: {outs}"
    assert outs["inside"][1] == 1, f"an in-range instance did not initialise: {outs}"
    return outs


def ssim_f2b(x):
    import ssim
    return ssim.f2b(x)


def main():
    asm, lay = build()
    for k, v in lay.report().items():
        print(f"{k}: {v}")
    if "--check" in sys.argv:
        asm, lay = build(inst_bounds=RIG_BOUNDS)
        nm.REP = lay.rep
        print("bounds guard:", check_bounds(asm, lay))
        ok, res, _ = check(asm, lay, nam_lite.placeholder())
        print("check:", "PASS" if ok else "FAIL", res)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
