# NAM A2 Lite on the Line 6 Helix Floor (experimental)

A port of [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite) (NAM A2 Lite on the
HX Stomp) to the **Helix Floor, firmware 3.80.0**. Same idea: you build a modified firmware file from
Line 6's own stock 3.80.0 file on your PC. No firmware is distributed here, and **a built file must
never be shared**.

> **Status: experimental, one unit tested. Not ready for use.**
> - One NAM A2 Lite block per path plays on a Helix Floor.
> - Measured on the unit (meter build, `floor/nam_floor5m.py`): one NAM block costs **~37% of a
>   DSP in a plain path** (declared 30%, so a full preset can overload and crackle), and **~52% in
>   a split path**. Two NAM blocks on one split path overload the DSP.
> - In a split path the Floor hands the block instance memory outside the heaps the kernel was
>   built for (DM in Block 1, PM through a short-word address). The kernel does not handle that
>   yet: **keep NAM out of split paths.** Being investigated.
> Use a unit you can afford to be without, and rehearse the recovery before anything else.

This branch (`helix-floor`) is based on upstream commit `2e80164` (2026-10-31), which the Floor
kernel is built against. Upstream changes after it (the four-knob layout on MM4 Frequency
Shifter's ID, no tone bands, rings in block memory) are not ported yet.

## What is different from the HX Stomp build

- **Two NAM A2 Lite blocks per DSP** (four per preset: two on Path 1, two on Path 2), under
  Amp > NAM. Same User IR captures and knobs as upstream at `2e80164`.
- **Memory:** the Floor's DSP has far less free on-chip memory than the Stomp's. Each DSP's third
  "big" block slot (the room for a Cab Dual next to two amps) is cut to a normal slot, so a path
  holds **at most two amp-type blocks** (amps, preamps, amp+cab; or one amp and a Cab Dual).
  All 16 block positions per path stay. The NAM kernel streams each layer's weights from SDRAM
  through the external-port DMA channel 0 job queue.
- **DMA channel 0 is shared:** the Floor's stock DSP program keeps channel 0's interrupt (P9I)
  unmasked even while the channel is idle (the Stomp's keeps it masked, and upstream's kernel
  stays silent when it is not). The Floor kernel masks P9I for its own call when the channel is
  idle, and restores it on the way out. Channel 1 belongs to Line 6 on the Floor and is not used.
- **Speed:** ~42K simulated instructions per NAM block per 16-sample call, ~55K cycles on the unit
  (the Stomp block is ~22-23% of its DSP). About 15K of the simulated count is waiting for and
  managing the weight stream: the main target for speed work.

Details, measurements and the full history: [docs/FINDINGS.md](docs/FINDINGS.md) and
[docs/DESIGN_2NAM.md](docs/DESIGN_2NAM.md).

## Build

Needs Python 3.10+ and `capstone` (`pip install capstone`), plus Line 6's stock Helix Floor
3.80.0 file `Helix_Floor_v3.80.0_0x7d01f5efb.hxf` (MD5 `805caa03e8a30fd6ff7892f32ed5a9f4`).
From the root of this repository:

```bash
PYTHONUTF8=1 python helix-floor/floor/build_floor2.py path/to/Helix_Floor_v3.80.0_0x7d01f5efb.hxf -o Helix_Floor_v3.80.0_NAM2.hxf
```

The build runs every stage's own checks (the NAM kernel's bit-exact KernelCheck in the
simulator, ~5 minutes; partition sizes; the main-program guard tests) and stops on any failure.
`--diag` builds a test image instead: one NAM per DSP that beeps a code where it would otherwise
be silent (codes in `floor/nam_floor4d.py` and `floor/nam_floor5d.py`).

## Captures

Use upstream's converter (`web/`, or its hosted setup page) to turn a `.nam` file into a User IR
`.wav`, and import it into a User IR slot with HX Edit. The Floor stores User IRs the same way the
Stomp does. In the NAM block, **Model** = the IR slot number; a slot without a NAM capture is silent.

## Install and recovery

Install with Line 6 Updater (Offline Mode, choose the built file). To go back: hold footswitches
**6 + 12** while powering on (update mode), then install the stock 3.80.0 file. Presets survive.

Known issue: **HX Edit can drop NAM blocks** when it rewrites a preset (for example when you drag
blocks around), because it does not know the NAM model. Edit NAM presets on the unit.

## Layout

| Folder | What |
|---|---|
| `floor/` | The build: stages (`stage_*.py`), kernels (`nam_floor*.py`, current `nam_floor5.py`), tests |
| `dsp/`, `alloc/`, `scope/`, `scripts/` | Research tools used to map the Floor firmware (read-only analysis) |
| `docs/` | Findings and design notes |

The scripts find upstream's `tools/` one level up (this folder sits at the repository root).

License: GPL-3.0, as upstream.
