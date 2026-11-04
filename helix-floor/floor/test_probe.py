"""Run the DFU probe in the guard tests' Thumb interpreter: it must write "BootIntoDfu!" at
0x1001ff00, keep r0 (the update-mode flag), and continue to 0x28110b60 returning to 0x28114d8c."""
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
import build_probe as bp  # noqa: E402
from test_arm_guards import Cpu  # noqa: E402


code, note_va = bp.build()
cpu = Cpu(code, bp.PROBE)
cpu.r[13] = 0x20200000
try:
    cpu.run(bp.PROBE | 1)
except RuntimeError as e:                       # stops at blx r3 (the wait): not modelled
    stop = str(e)
note = bytes(cpu.r8(bp.NOTE_AT + k) for k in range(16))
ok = [("note written", note == bp.NOTE), ("stops at the wait call", "blx r3" in stop),
      ("wait 2 s in r0", cpu.r[0] == bp.WAIT_US), ("wait routine in r3", cpu.r[3] == bp.WAIT | 1),
      ("stack untouched", cpu.r[13] == 0x20200000)]
tail = code[:len(code) - len(bp.NOTE)]
ok.append(("then reset: movs r2,#1; str.w r2,[r3,#0x100]; b .", bytes.fromhex("0122c3f80021fee7") in tail))
for name, good in ok:
    print(("ok  " if good else "BAD ") + name)
print("PASS" if all(g for _, g in ok) else "FAIL")
sys.exit(0 if all(g for _, g in ok) else 1)
