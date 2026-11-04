#!/usr/bin/env python3
"""Personal build: Helix Floor 3.80.0 with NAM A2 Lite (13-block layout). PC only, never shared.

Stages (each checks its own result; floor-port-findings.md "Floor build plan"):
  1. stage_slots   Entry 5: 3 block slots per DSP switched off; Entry 2: heaps a and b shrunk
  2. stage_model   Entries 4, 5: the NAM amp; Entry 2: Blob 0 buffer, Heap 6 moved
  3. stage_kernel  Entry 2: the kernel (KernelCheck first) and primitive 0x128's record
  4. stage_main    Entries 0, 1: guards, tables, the Amp > NAM folder
  5. l6ia_verify, the guard tests, a report of every changed byte range, the .hxf

usage: build_floor.py <stock Helix_Floor_v3.80.0_0x7d01f5efb.hxf> [-o out.hxf]
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from upstream import TOOLS  # noqa: E402
ROOT = os.path.dirname(HERE)
PY = sys.executable
STOCK_MD5 = "805caa03e8a30fd6ff7892f32ed5a9f4"


def run(*args):
    print("$ " + " ".join(os.path.basename(a) if a.endswith(".py") else a for a in args), flush=True)
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"})
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(f"build_floor: {os.path.basename(args[0])} failed")
    return r.stdout


# Partition sizes in sectors, from the app's own partition table (0x28116124.., indexed by entry
# through 0x2811619c); the app checks every partition's header length against them at boot
# (0x281135f0: cmp.w r3, r2, lsl #9 at 0x28113644) and a longer one is a boot failure.
PART_SECTORS = {0: 0x4001, 1: 0x4001, 2: 0x400, 3: 0x80, 4: 0x800, 5: 0x7BF8}
SLOT_BYTES = {i: n * 512 for i, n in PART_SECTORS.items()}


def slots(l6ia_path):
    sys.path.insert(0, TOOLS)
    import l6ia
    ents = l6ia.parse(open(l6ia_path, "rb").read())
    for i, cap in SLOT_BYTES.items():
        n = ents[i]['payload_len']
        assert n <= cap, f"Entry {i}: {n:#x} bytes > its partition's {cap:#x}"
        print(f"Entry {i}: {n:#x} bytes of its partition's {cap:#x} ({cap - n} spare)")


def report(stock_l6ia, new_l6ia):
    sys.path.insert(0, TOOLS)
    import l6ia
    a, b = open(stock_l6ia, "rb").read(), open(new_l6ia, "rb").read()
    ea, eb = l6ia.parse(a), l6ia.parse(b)
    lines = []
    for x, y in zip(ea, eb):
        pa_ = a[x['payload_off']: x['payload_off'] + x['payload_len']]
        pb_ = b[y['payload_off']: y['payload_off'] + y['payload_len']]
        if pa_ == pb_:
            continue
        n = min(len(pa_), len(pb_))
        runs, k = [], 0
        while k < n:
            if pa_[k] != pb_[k]:
                s = k
                while k < n and pa_[k] != pb_[k]:
                    k += 1
                if runs and s - runs[-1][1] <= 16:
                    runs[-1][1] = k
                else:
                    runs.append([s, k])
            k += 1
        lines.append(f"Entry {x['index']}: {len(pa_):#x} -> {len(pb_):#x} bytes, {len(runs)} changed runs in the common part"
                     + (f", +{len(pb_) - len(pa_)} bytes" if len(pb_) != len(pa_) else ""))
        for s, e in runs[:12]:
            lines.append(f"    {s:#08x}..{e:#08x} ({e - s} B)")
        if len(runs) > 12:
            lines.append(f"    ... {len(runs) - 12} more")
    return "\n".join(lines)


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    stock = os.path.abspath(argv[0])
    assert hashlib.md5(open(stock, "rb").read()).hexdigest() == STOCK_MD5, "not the stock Floor 3.80.0 file"
    out = os.path.abspath(argv[argv.index("-o") + 1]) if "-o" in argv else \
        os.path.join(ROOT, "build", "Helix_Floor_v3.80.0_NAM_PERSONAL.hxf")
    b = os.path.join(ROOT, "build")
    os.makedirs(b, exist_ok=True)
    os.makedirs(b, exist_ok=True)
    s0, s1, s2, s3, s4 = (os.path.join(b, f"floor_{n}.l6ia") for n in ("stock", "s1", "s2", "s3", "s4"))
    run(os.path.join(TOOLS, "hxf.py"), "unpack", stock, s0)
    run(os.path.join(HERE, "stage_slots.py"), s0, s1)
    run(os.path.join(HERE, "stage_model.py"), s1, s2)
    run(os.path.join(HERE, "stage_kernel.py"), s2, s3)
    run(os.path.join(HERE, "stage_main.py"), s3, s4)
    v = run(os.path.join(TOOLS, "l6ia_verify.py"), s4)
    assert "ALL OK" in v
    slots(s4)
    run(os.path.join(HERE, "test_arm_guards.py"))
    run(os.path.join(HERE, "test_ir_title.py"))
    rep = report(s0, s4)
    print(rep)
    open(os.path.join(b, "CHANGES.txt"), "w").write(rep + "\n")
    run(os.path.join(HERE, "floor_hxf.py"), "pack", s4, out, "--donor", stock)
    for f in (s1, s2, s3):
        os.remove(f)
    print(f"\nDone: {out}\nPersonal build. Not tested on hardware. Do not install on a unit you rely on; "
          f"a spare unit and a tested recovery come first.")


if __name__ == "__main__":
    main()
