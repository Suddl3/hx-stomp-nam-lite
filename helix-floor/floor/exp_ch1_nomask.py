"""Sim experiment (2026-11-06): nam_floor4 (weights on EP DMA channel 1, rings on channel 0) with the
interrupt checks removed. On the Floor, P13I = DAI high priority and P9I = link port 1 (stock PICR),
so floor4's 'P13IMSK unmasked -> skip' check made it silent on the unit (diag v2), and masking either
would hurt Line 6. Neither EP DMA channel has an interrupt, so channel-idle checks are enough.
usage: exp_ch1_nomask.py [--check] [--bench]"""
import sys
import nam_floor4 as n4
import nam_floor5 as n5

_orig = n4.kernel_src
CH1 = """    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP1IMSK;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;
    R0 = DM(DMAC0);"""
CH0 = """    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP0IMSK;
    R1 = R0 AND R1;
    IF EQ JUMP m_idle;
m_busy:"""


def kernel_src():
    s = _orig()
    assert s.count(CH1) == 1 and s.count(CH0) == 1
    s = s.replace(CH1, """    IF NE JUMP m_busy;
    R0 = DM(DMAC0);""")
    s = s.replace(CH0, """    IF EQ JUMP m_idle;
m_busy:""")
    assert "LRPTL" not in s
    for a, b in (n5.PMB_PATCH, n5.GUARD_PATCH):     # nam_floor5's I8 re-check + unsigned bounds guard
        assert s.count(a) == 1, a[:60]
        s = s.replace(a, b)
    return s


_init = n4.Layout.__init__


def _layout_init(self, *a, **kw):
    _init(self, *a, **kw)
    v = self.v
    v["S_PMB"] = n5.S_PMB
    v["INST_DM_SPAN"] = v["INST_DM_HI"] - v["INST_DM_NEED"] - v["INST_DM_LO"]
    v["INST_PM_SPAN"] = v["INST_PM_HI"] - v["INST_PM_NEED"] - v["INST_PM_LO"]
    assert v["INST_DM_SPAN"] >= 0 and v["INST_PM_SPAN"] >= 0


_names = n4.names
n4.names = lambda: _names() + ["S_PMB", "INST_DM_SPAN", "INST_PM_SPAN"]
n4.Layout.__init__ = _layout_init
n4.kernel_src = kernel_src

def __getattr__(name):              # (stage_kernel imports this module like a kernel module)
    return getattr(n4, name)


if __name__ == "__main__":
    n4.main()
