#!/usr/bin/env python3
"""Personal build, 2 NAM blocks per DSP: Helix Floor 3.80.0 with NAM A2 Lite on test2c's layout
(DESIGN_2NAM.md). PC only, never shared.

Stages (as build_floor.py, with):
  1. stage_slots2  Entry 5: each DSP's 3rd big slot -> normal size; Entry 2: heaps a, b shrunk to match
  2. stage_model   NAM_KERNEL=nam_floor4: the instance sizes and SDRAM (0x5800) of the 2-slot kernel
  3. stage_kernel  NAM_KERNEL=nam_floor4: weights streamed on EP DMA channel 1 (KernelCheck first)
  4. stage_main    NAM_MAX_BLOCKS=16: no block cap (all 16 slots stay), max 2 big-slot blocks per DSP

usage: build_floor2.py <stock Helix_Floor_v3.80.0_0x7d01f5efb.hxf> [-o out.hxf]
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from upstream import TOOLS  # noqa: E402
import build_floor as bf  # noqa: E402

ROOT = bf.ROOT


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    stock = os.path.abspath(argv[0])
    assert hashlib.md5(open(stock, "rb").read()).hexdigest() == bf.STOCK_MD5, "not the stock Floor 3.80.0 file"
    out = os.path.abspath(argv[argv.index("-o") + 1]) if "-o" in argv else \
        os.path.join(ROOT, "build", "Helix_Floor_v3.80.0_NAM2_PERSONAL.hxf")
    b = os.path.join(ROOT, "build")
    os.makedirs(b, exist_ok=True)
    s0, s1, s2, s3, s4 = (os.path.join(b, f"floor2_{n}.l6ia") for n in ("stock", "s1", "s2", "s3", "s4"))
    bf.run(os.path.join(TOOLS, "hxf.py"), "unpack", stock, s0)
    diag = "--diag" in argv                  # the beep-code test image (nam_floor5d)
    meter = "--meter" in argv                # the cycles meter test image (nam_floor5m)
    probe = "--probe" in argv                # the tap-list DMA probe image (nam_floor5t)
    ch1 = "--ch1" in argv                    # weights on EP DMA channel 1 (exp_ch1_nomask: nam_floor4, no LRPTL)
    if diag or meter or probe:
        os.environ["NAM_DIAG"] = "1"         # (no KernelCheck: the output is a code / the meter)
        out = out.replace("NAM2_PERSONAL", "NAM2_DIAG" if diag else "NAM2_PROBE" if probe else "NAM2_METER")
        out = out.replace("NAM2_CH1", "NAM2_CH1_METER") if meter and "METER" not in out else out
    os.environ["NAM_KERNEL"], os.environ["NAM_MAX_BLOCKS"] = \
        ("nam_floor5d" if diag else "nam_floor5t" if probe else "exp_ch1_meter" if (meter and ch1) else "nam_floor5m" if meter
         else "exp_ch1_nomask" if ch1 else "nam_floor5"), "16"
    os.environ["NAM_MAX_STEADY"] = "60000"           # (bit-exact still checked; speed judged on the unit)
    bf.run(os.path.join(HERE, "stage_slots2.py"), s0, s1)
    bf.run(os.path.join(HERE, "stage_model.py"), s1, s2)
    bf.run(os.path.join(HERE, "stage_kernel.py"), s2, s3)
    bf.run(os.path.join(HERE, "stage_main.py"), s3, s4)
    del os.environ["NAM_KERNEL"], os.environ["NAM_MAX_BLOCKS"]
    os.environ.pop("NAM_DIAG", None)
    v = bf.run(os.path.join(TOOLS, "l6ia_verify.py"), s4)
    assert "ALL OK" in v
    bf.slots(s4)
    bf.run(os.path.join(HERE, "test_arm_guards.py"))          # (the 13-cap rule set; 16 differs by the constant)
    bf.run(os.path.join(HERE, "test_ir_title.py"))
    rep = bf.report(s0, s4)
    print(rep)
    open(os.path.join(b, "CHANGES_NAM2.txt"), "w").write(rep + "\n")
    bf.run(os.path.join(HERE, "floor_hxf.py"), "pack", s4, out, "--donor", stock)
    for f in (s1, s2, s3):
        os.remove(f)
    print(f"\nDone: {out}\nPersonal build. MD5 {hashlib.md5(open(out, 'rb').read()).hexdigest()}")


if __name__ == "__main__":
    main()
