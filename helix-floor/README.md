# NAM A2 Lite on the Line 6 Helix Floor: build, install, details

A port of [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite) (NAM A2 Lite on the
HX Stomp) to the **Helix Floor, firmware 3.80.0**. You build a modified firmware file from Line 6's
own stock 3.80.0 file on your PC. No firmware is distributed here, and **a built file must never be
shared**. Overview, status and findings: the [repository README](../README.md).

> **Experimental, one unit tested.** Rehearse the recovery (below) before you rely on it.

## What is different from the HX Stomp build

- **Up to two NAM A2 Lite blocks per DSP** (four per preset: Path 1 runs on one DSP, Path 2 on the
  other), under Amp > NAM. Same User IR captures and knobs as upstream at `2e80164`.
- **Memory:** the Floor's DSP has far less free on-chip memory than the Stomp's. Each DSP's third
  "big" block slot (the room for a Cab Dual next to two amps) is cut to a normal slot, so a path
  holds **at most two amp-type blocks** (amps, preamps, amp+cab; or one amp and a Cab Dual).
  All 16 block positions per path stay. The kernel streams each layer's weights and the long
  delay lines from SDRAM through external-port DMA channel 0's job queue.
- **Interrupts:** the kernel never touches the interrupt mask. On both units the stock DSP program
  routes programmable interrupt P9I to link port 1 (the Floor's DSP-to-DSP link) and gives neither
  external-port DMA channel an interrupt, so channel 0 can be used whenever it is idle. (Earlier
  builds masked P9I for each call, believing it was channel 0's: that froze the UI at random.)
- **Cost:** about 52.8K cycles per 16-sample call on the unit, **~35% of a DSP** per block. The
  declared DSP cost is 3,600 (`NAM_DSP_COST`), so the Floor's own budget refuses a block that would
  overload a DSP.
- **Optional kernel path** (off by default, verified bit-exact in the simulator and on the unit):
  `NAM_GATHER=1` fetches each far layer's taps with one scatter/gather (tap-list) DMA and writes
  them back with scatter DMA. No measurable speed gain on hardware; kept for reference.

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

Test images (not for playing): `--meter` replaces the NAM output with numbers about each call
(cycles, the instance's memory, the guard state; read them from USB 1 at 48 kHz), `--probe` runs
a tap-list DMA probe, `--diag` beeps a code where the block would be silent.

## Captures

Use upstream's converter (`web/`, or its hosted setup page) to turn a `.nam` A2 Lite file into a
User IR `.wav`, and import it into a User IR slot with HX Edit. The Floor stores User IRs the same
way the Stomp does. In the NAM block, **Model** = the IR slot number; a slot without a NAM capture
is silent.

## Install and recovery

Install with Line 6 Updater (Offline Mode, choose the built file). The Updater's last page may show
a web error; the install itself is done once it reports success or the unit restarts. After any
firmware install the Floor starts on a factory setlist.

To go back: hold footswitches **6 + 12** while powering on (update mode), then install the stock
3.80.0 file. Presets survive.

Tip for testing new builds: leave the unit on a preset **without** a NAM block before installing.
The Floor restarts on the last preset, so if a build misbehaves with NAM running, a power cycle
still brings it up without NAM.

Known issue: **HX Edit can drop NAM blocks** when it rewrites a preset (for example when you drag
blocks around), because it does not know the NAM model. Edit NAM presets on the unit.

## Layout

| Folder | What |
|---|---|
| `floor/` | The build: stages (`stage_*.py`), kernels (`nam_floor*.py`, current `nam_floor5.py`), tests |
| `dsp/`, `alloc/`, `scope/`, `scripts/` | Research tools used to map the Floor firmware (read-only analysis) |
| `docs/` | Findings and design notes |

The scripts find upstream's `tools/` one level up (this folder sits at the repository root).
