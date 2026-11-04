"""Run ir_title's two caves in the guard tests' Thumb interpreter: where each kind of block goes."""
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import ir_title as t  # noqa: E402
from test_arm_guards import Cpu  # noqa: E402

BASE, BLK = 0x1001F160, 0x20300000
PID = 380


def go(cave, cat, pid, sub=2):
    code, ca, cb = t.build(BASE, [PID])
    cpu = Cpu(code, BASE)
    for k, b in enumerate(pid.to_bytes(4, "little")):
        cpu.w8(BLK + 1 + k, b)
    cpu.w8(BLK + 12, cat)
    cpu.w8(BLK + 13, sub)
    cpu.r[6 if cave == "A" else 5] = BLK
    cpu.r[4] = 0x55
    to = cpu.run((ca if cave == "A" else cb) | 1)
    return to & ~1, cpu.r[4]


def main():
    cases = [
        ("A: IR block -> stock IR path", go("A", 15, 5)[0], t.IR_PATH),
        ("A: NAM amp -> IR name branch", go("A", 12, PID), (t.IR_NAME, 0)),
        ("A: other amp -> stock", go("A", 12, 77)[0], t.NON_IR),
        ("A: NAM in Amp+Cab -> stock", go("A", 11, PID)[0], t.NON_IR),
        ("A: an effect -> stock", go("A", 2, PID)[0], t.NON_IR),
        ("B: IR block -> IR redraw", go("B", 15, 5)[0], t.B_IR),
        ("B: NAM amp -> IR redraw", go("B", 12, PID)[0], t.B_IR),
        ("B: other amp -> return", go("B", 12, 77)[0], t.B_RET),
        ("B: NAM in Amp+Cab -> return", go("B", 11, PID)[0], t.B_RET),
    ]
    bad = [c for c in cases if c[1] != c[2]]
    for name, got, want in cases:
        print(f"{'ok ' if got == want else 'BAD'} {name}")
    print("PASS" if not bad else f"FAIL {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
