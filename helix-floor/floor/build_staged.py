#!/usr/bin/env python3
"""Staged test images (review/REVIEW_2026-11-01.md: test one risk at a time). PC only, never share.

  test1_seg0_only.hxf   stock, except Entry 0's seg0 grown by the same number of bytes as the full
                        build, filled with zeros (no code points there): does the bootloader take
                        the bigger seg0 and does the unit run normally?
  test2_slots_only.hxf  stock + stage_slots (3 slots per DSP off, heaps a/b shrunk): do 13-block
                        presets, 2 amps and preset changes still play on both DSPs?
Then the full build (build_floor.py).

usage: build_staged.py <stock Floor .hxf>
"""
import hashlib
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream import TOOLS  # noqa: E402
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import l6ia  # noqa: E402
import patch_amp as pa  # noqa: E402
import floor_hxf  # noqa: E402
import stage_main  # noqa: E402
from build_floor import SLOT_BYTES  # noqa: E402


def grow_seg0(e0, n):
    segs = stage_main.segments(e0)
    h0, p0, l0, d0, n0 = segs[0]
    out = bytearray(e0[:n0]) + bytes(n) + e0[n0:]
    struct.pack_into('<3I', out, h0, l0 + n, d0, n0 + n)
    for h, p, l, d, nx in segs[1:]:
        struct.pack_into('<3I', out, h + n, l, d, nx + n)
    struct.pack_into('<I', out, 4, len(out))
    return l6ia.fix_internal_crcs(bytes(out))


def check_and_pack(img, name, stock_raw):
    ents = l6ia.parse(img)
    for i, cap in SLOT_BYTES.items():
        assert ents[i]['payload_len'] <= cap, f"{name}: Entry {i} over its partition"
    path = os.path.join(ROOT, "build", "l6ia.tmp")
    open(path, "wb").write(img)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "l6ia_verify.py"), path],
                       capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"})
    os.remove(path)
    assert "ALL OK" in r.stdout, f"{name}: checksums"
    out = os.path.join(ROOT, "build", name)
    open(out, "wb").write(floor_hxf.pack(img, stock_raw))
    print(f"{name}: checksums ALL OK, partitions fit, MD5 {hashlib.md5(open(out, 'rb').read()).hexdigest()}")


def main():
    stock = sys.argv[1]
    raw = open(stock, "rb").read()
    assert hashlib.md5(raw).hexdigest() == floor_hxf.FLOOR_MD5
    data, _ = pa.load_l6ia_from_any(stock)
    # test 1: seg0 grown by the full build's amount, zeros
    full, _ = pa.load_l6ia_from_any(os.path.join(ROOT, "build", "floor_s4.l6ia"))
    e0, f0 = pa.get_entry_swapped(data, 0), pa.get_entry_swapped(full, 0)
    n = stage_main.segments(f0)[0][2] - stage_main.segments(e0)[0][2]
    g0 = grow_seg0(e0, n)
    assert stage_main.segments(g0)[0][2] == stage_main.segments(f0)[0][2]
    img, _, _ = l6ia.rebuild_archive(data, {0: g0})
    assert pa.get_entry_swapped(img, 1) == e0
    print(f"test 1: seg0 +{n} bytes of zeros (as the full build), Entry 1 stock")
    check_and_pack(img, "test1_seg0_only.hxf", raw)
    # test 2: stage_slots alone
    s0 = os.path.join(ROOT, "build", "floor_stock.l6ia")
    s1 = os.path.join(ROOT, "build", "test2.l6ia")
    r = subprocess.run([sys.executable, os.path.join(HERE, "stage_slots.py"), s0, s1], capture_output=True, text=True,
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, r.stderr
    print("test 2: stage_slots only\n" + r.stdout.strip())
    check_and_pack(open(s1, "rb").read(), "test2_slots_only.hxf", raw)
    os.remove(s1)


if __name__ == "__main__":
    main()
