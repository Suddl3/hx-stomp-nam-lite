"""METER v4 image of the channel-1 kernel (exp_ch1_nomask): the same eight 2-sample fields as
nam_floor5m (meter_read.py --v4), written at METER_EXIT (there is no x_nomsk: nothing is masked).
usage: NAM_KERNEL=exp_ch1_meter (build_floor2.py --ch1 --meter); env CH1_METER_SLOTS (default 2)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nam_floor4 as n4  # noqa: E402
import exp_ch1_nomask  # noqa: E402,F401  (patches n4)
import nam_floor5m as m5  # noqa: E402

n4.SLOTS = int(os.environ.get("CH1_METER_SLOTS", "2"))
_src = n4.kernel_src
EXIT = "// METER_EXIT\n    R0 = DM(SAVE + 1);"


def kernel_src():
    s = _src()
    pats = list(m5.PATCHES_M)
    entry, body = pats[0], pats[1][1]
    assert body.startswith("x_nomsk:\n")
    pats[1] = (EXIT, "// METER_EXIT\n" + body[len("x_nomsk:\n"):] + "    R0 = DM(SAVE + 1);")
    for a, b in pats:
        assert s.count(a) == 1, a[:70]
        s = s.replace(a, b)
    return s


n4.kernel_src = kernel_src


def __getattr__(name):
    return getattr(n4, name)


if __name__ == "__main__":
    n4.main()
