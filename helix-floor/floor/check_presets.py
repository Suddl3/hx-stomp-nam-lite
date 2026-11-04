#!/usr/bin/env python3
"""Check Helix .hlx presets against the 13-block layout before loading them on the NAM build
(preset load runs no checks on the unit; setup/index.html does the same in the browser).

Per DSP (Path 1 = dsp0, Path 2 = dsp1): blocks <= 13, and big-space blocks <= 2: amps and
preamps (@type 1), amp + cab (@type 3), and the older dual cab (@type 4 with a legacy
HD2_Cab... model, not HD2_CabMicIr...).

usage: check_presets.py <folder or .hlx> [...]
"""
import json
import os
import sys

MAX_BLOCKS, MAX_BIG = 13, 2


def big(b):
    t, m = b.get('@type'), str(b.get('@model', ''))
    return t in (1, 3) or (t == 4 and m.startswith('HD2_Cab') and not m.startswith('HD2_CabMicIr'))


def check(path):
    tone = json.load(open(path, encoding='utf-8'))['data']['tone']
    out = []
    for n, dsp in enumerate(('dsp0', 'dsp1')):
        blocks = [v for k, v in tone.get(dsp, {}).items() if k.startswith('block') and isinstance(v, dict)]
        nb, ng = len(blocks), sum(big(b) for b in blocks)
        out.append((n + 1, nb, ng, nb > MAX_BLOCKS or ng > MAX_BIG))
    return out


def main():
    files = []
    for a in sys.argv[1:]:
        if os.path.isdir(a):
            files += [os.path.join(dp, f) for dp, _, fn in os.walk(a) for f in fn if f.lower().endswith('.hlx')]
        else:
            files.append(a)
    bad = 0
    for f in sorted(files):
        try:
            res = check(f)
        except Exception as e:                          # not a preset file
            print(f"?    {os.path.basename(f)}: {e}")
            continue
        flag = any(r[3] for r in res)
        bad += flag
        print(f"{'OVER' if flag else 'ok  '} {os.path.basename(f)}: " +
              ", ".join(f"Path {p} {nb} blocks / {ng} big" for p, nb, ng, _ in res))
    print(f"{len(files)} presets, {bad} over the limits (13 blocks, 2 amp-type per path)")


if __name__ == "__main__":
    main()
