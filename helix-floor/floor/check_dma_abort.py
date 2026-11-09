# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline generated-instruction regression. No USB or firmware container.

Run with a Floor source tree and --expect baseline|candidate. Fault injection
models status remaining busy after DEN is cleared, unlike ChainDma's immediate
stop. It does not emulate stock interrupt handlers or prove a hardware freeze.
Use an external process deadline. --full runs the existing KernelCheck suite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('tree', type=Path)
p.add_argument('--expect', choices=('baseline', 'candidate'), required=True)
p.add_argument('--full', action='store_true')
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
sys.path.insert(0, str(args.tree.resolve() / 'helix-floor/floor'))
import nam_floor5 as k

nm = k.nm
BUSY_STATUS = nm.DMAS | nm.CHS | nm.EXTS
started = time.monotonic()
asm, lay = k.build(inst_bounds=k.RIG_BOUNDS)
nm.REP = lay.rep

def ready():
    rig = k.Rig(asm, lay)
    nm.set_ir(rig.sim, 1, k.nam_lite.ir_samples(k.nam_lite.placeholder(), None))
    inst = rig.inst('A', 0)
    inst.knobs(model=1)
    signal = [k.nf.ssim_f2b(0.15 * ((n * 7) % 11 - 5) / 5) for n in range(16)]
    for n in range(3):
        inst.call(signal, f'warmup {n}')
    assert rig.sim.rd(lay.slot[0] + nm.S['S_INIT']) == 1
    return rig, inst, signal

def probe(release_after):
    rig, inst, signal = ready()
    sim, dma = rig.sim, rig.dma
    dma.mode = 'stall'
    rd0, wr0 = sim.rd, sim.wr
    polls, early, stopped, busy = 0, [], False, False
    before_count = sim.rd(lay.rep + nm.REPW['R_TIMEOUTS'])
    lrptl = k.sasm.UREG_CODE['LRPTL']
    initial = nm.EP0IMSK | k.EP0LAT | 0x20080
    sim.set(lrptl, initial)
    def read(a):
        nonlocal polls, busy
        value = rd0(a)
        if stopped and a == nm.DMAC0:
            if sim.pc == rig.syms['DA_W']:
                polls += 1
                busy = release_after is None or polls <= release_after
            return (value | BUSY_STATUS) if busy else (value & ~BUSY_STATUS)
        return value
    def write(a, value):
        nonlocal stopped, busy
        if a == nm.DMAC0 and not value & nm.DEN and dma.active:
            stopped, busy = True, True
        if busy and a in (nm.ICEP0, nm.CPEP0):
            early.append([hex(a), value])
        return wr0(a, value)
    sim.rd, sim.wr = read, write
    try:
        out = inst.call(signal, 'injected post-disable drain')
    finally:
        sim.rd, sim.wr = rd0, wr0
    assert stopped and not any(out)
    assert polls == (1000 if release_after is None else release_after + 1)
    assert sim.get(lrptl) == initial
    count_delta = sim.rd(lay.rep + nm.REPW['R_TIMEOUTS']) - before_count
    assert count_delta == 1, 'abort accounting must include the exhausted wait'
    if release_after is None and args.expect == 'baseline':
        assert early, 'baseline should expose descriptor writes while still busy'
    else:
        assert not early, early
    recovery = None
    if args.expect == 'candidate' and release_after is None:
        dma.mode = 'ok'
        dma.wr0(nm.DMAC0, BUSY_STATUS)
        sim.dm[lay.rep + nm.REPW['R_BACKOFF']] = 0
        dma.writes.clear()
        assert not any(inst.call(signal, 'still busy next admission'))
        assert not dma.writes
        dma.wr0(nm.DMAC0, 0)
        sim.dm[lay.rep + nm.REPW['R_BACKOFF']] = 0
        dma.writes.clear()
        for n in range(4):
            out = inst.call(signal, f'idle recovery {n}')
        assert any(out)
        assert dma.writes[:2] == [(nm.ICEP0, 0), (nm.CPEP0, 0)]
        recovery = {'noDmaWritesOnBusyReadmission': True, 'audioResumedAfterIdle': True,
                    'backoffFastForwarded': True}
    return {'releaseAfter': release_after, 'abortPolls': polls, 'descriptorWritesWhileBusy': early,
            'timeoutCounterDelta': count_delta, 'linkRegisterUnchanged': True, 'recovery': recovery}

result = {'expectation': args.expect, 'hardwareTested': False, 'firmwareBuilt': False,
          'assemblySha256': hashlib.sha256(asm.encode()).hexdigest(),
          'codeWords': lay.n_code, 'probes': [probe(None), probe(5), probe(999)]}
print('Targeted abort/drain probes passed:', args.expect, flush=True)
if args.full:
    steps = []
    original = nm.KernelCheck.run
    def run(check):
        for name in check.STEPS:
            print('KernelCheck:', name, flush=True)
            getattr(check, name)()
            steps.append(name)
    nm.KernelCheck.run = run
    # Upstream Floor's normal callback exceeds the Stomp checker's 40k limit.
    # Match this workspace's prior Floor regression threshold; not a DSP limit.
    nm.MAX_STEADY = 60000
    try:
        ok, summary, detail = k.check(asm, lay, k.nam_lite.placeholder())
    finally:
        nm.KernelCheck.run = original
    assert ok, summary
    result['regression'] = {'steps': steps, 'summary': summary, 'kernelCalls': len(detail.rig.cycles)}
result['elapsedSeconds'] = round(time.monotonic() - started, 3)
args.output.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
print('PASS', args.output, flush=True)
