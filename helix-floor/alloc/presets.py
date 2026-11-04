"""Count blocks per DSP / path in .hlx presets, and list amp-type blocks."""
import json, sys, collections
for p in sys.argv[1:]:
    t = json.load(open(p, encoding='utf-8'))['data']['tone']
    print('==', p.replace(chr(92), '/').split('/')[-1])
    for dsp in ('dsp0', 'dsp1'):
        d = t.get(dsp, {})
        per = collections.Counter(); amps = []
        for k, b in d.items():
            if k.startswith('block') and isinstance(b, dict) and '@model' in b:
                per[b.get('@path', 0)] += 1
                m = b['@model']
                if any(x in m for x in ('Amp', 'Preamp', 'CabMicIr', 'Cab_Dual', 'DualCab')) or '@cab' in b:
                    amps.append(m + (' +cab' if '@cab' in b else ''))
        print(f'  {dsp}: blocks {sum(per.values())} (path a {per[0]}, path b {per[1]})  amp-type: {amps}')
