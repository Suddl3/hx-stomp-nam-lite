# Design: two NAM blocks per Floor DSP (weights streamed), 2026-11-02

Goal: 2 NAM blocks on one DSP (the owner's parallel-amp stereo preset), on the hardware-proven test2c
memory (`build/test2c_bigslot_heaps.hxf`: 3rd big slot per DSP → normal, heaps a/b shrunk to match).
Base code: `floor/nam_floor.py` (patches upstream `nam_multi_kernel.asm`, lays out, runs KernelCheck).
New work goes in `floor/nam_floor2.py` (+ its own asm patches); upstream files stay untouched.

## Memory budget per DSP (normal words)

| Region | Range | Usable |
|---|---|---|
| R3' Block 0 (heap a tail) | `0x9b6b1+16 .. 0x9ba5f` | 926 |
| R1 Block 3 (free tail) | `0xe729a .. 0xe8000` | 3,430 |
| R2' Block 3 (heap b tail, PM side) | `0xe6624+16 .. 0xe674a` | 278 |
| **Total** | | **4,634** |

Per instance (amp placeholder, I0 / I8): DM 1,430 / PM 506; near rings + stock use leave DM 13 / PM 61.
Per instance SDRAM block: today 0x5000 (19,810 used) → raise to **0x5800** in `stage_model.py` for the
slot's weight copy (1,943 words).

## What changes in the kernel

1. **Weights + per-layer table row streamed per layer** (the core change).
   - Model load (`ld_model`) writes the scaled, forward stream to the slot's SDRAM block
     (`S_SDR + W_OFF`) instead of on chip. Load is rare; core writes to DDR2 are fine there.
   - TABLE moves to DDR2 (shared, read-only after layout): each layer's 17-word row is fetched with
     its weights.
   - Two on-chip layer buffers `LB0`, `LB1`, each `17 + 156` words (row + largest layer's weights,
     WBUF_N). Layer i uses `LB[i % 2]`; while layer i computes, a DMA job fetches row+weights of
     layer i+1 into the other. `I4` (table pointer) and `I9` (weights) point into the buffer.
   - Near layers no longer copy weights into WBUF (`n_wc` loop goes): WBUF's role is taken by the
     layer buffers (they sit away from the rings' block, as WBUF did).
   - New job type in the existing queue (`pump`, `J_TYPE` = 2): one TCB, external → internal,
     address = slot SDRAM weights + layer offset (computed in pump from `G_SDR`/`S_SDR`, like the
     tap jobs). Queue rebuilt in `Layout`: `L0` first, then each layer's fetch placed before the far
     layer jobs it would otherwise wait behind; readiness via `EVENTS` as today. A layer waits for
     its fetch with the existing bounded-poll pattern (`fwait`-style, `dma_abort` on timeout).
   - Head weights: one more fetch after the last layer (same buffers).
2. **Silence states** (72 per slot) stay in SDRAM with the weights; `ld_model`'s ring clear and the
   far-ring patching read them from there (load/restart only).
3. **Cold code overlay** (294 words): cold code is assembled to run at `SB`'s address, stored in
   DDR2 (LDR init), DMA'd into `SB` by a small resident stub before `m_init` / `ld_model` /
   `m_fail` paths, then called. Safe because no far-tap job is in flight at a slot's start or a
   model load (checked: the queue is idle before `m_ready`). Verify in the simulator that SB is
   not live across those calls.

## Expected static total (2 slots)

hot code ~1,600 (minus the WBUF copy loop, plus fetch/wait code) + resident stub ~20 + globals
2,239 − TABLE 391 + LB0/LB1 346 − WBUF 156 + X/IN 64 + flags 32 + per slot (state 72 + heads 102) × 2
≈ **4,100 ± 100** of 4,634: ~500 spare (better than the paper estimate because TABLE rides with
the weight fetch instead of being read from DDR2 by the core).

## Speed

Weight + row fetch: ~2,000 words per call on the EP DMA channel, overlapped with compute; the
far-tap jobs share the channel, so a layer may wait. Measure in the simulator (`ssim.py`, KernelCheck
cycle report): target ≤ upstream's ~25,000 instructions per block + DMA waits. Upstream reference:
steady 24,991 / worst 31,797 (far_d 17, 2 slots).

## Steps

1. `nam_floor2.py`: Layout for test2c regions, 2 slots, TABLE in DDR2, LB0/LB1; queue with fetch jobs.
2. Asm patches: ld_model → SDRAM; layer loop on LB buffers; pump job type 2; drop n_wc copy; head fetch.
3. KernelCheck bit-exact (all 14 steps) + cycle report.
4. Cold code overlay (only if step 3's layout is over budget or close).
5. Rebuild full image on test2c base (`build_floor.py` variant), then the model self-test question
   (see findings: HX Effects port saw unknown models rejected at boot) with a model-only test image
   before the full one.
