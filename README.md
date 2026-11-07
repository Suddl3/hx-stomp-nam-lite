# NAM A2 Lite on the Line 6 Helix Floor

**Neural Amp Modeler (NAM) A2 Lite captures, running as an amp block on a stock Helix Floor (firmware 3.80.0).**

This is a fork of [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), which does the same for the HX Stomp. The `helix-floor` branch ports it to the Floor, whose firmware and DSP layout are different enough to need their own kernel, memory plan and fixes. Everything Floor-specific lives in [`helix-floor/`](helix-floor/README.md). The rest of the repository is upstream as of commit `2e80164` (its README is kept as [README_UPSTREAM.md](README_UPSTREAM.md)).

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group. Tested on one Helix Floor. Installing modified firmware is at your own risk and may void your warranty. Rehearse the [recovery](#install-and-recovery) before you rely on it.

## Status (2026-11-07)

| | |
|---|---|
| **Works today** | NAM A2 Lite under **Amp > NAM**, captures loaded from User IR slots, same knobs as upstream (Model, Input, Bass, Mid, Treble, Presence, Ch Vol). |
| | **Up to two NAM blocks per DSP**, so up to four per preset (Path 1 runs on one DSP, Path 2 on the other). Two on one DSP play cleanly (20-minute checks, no dropouts). |
| | The UI-freeze bug of the earlier builds is fixed (cause below). |
| **Limits** | One NAM block uses **about 35% of a DSP** (measured on the unit). Two on one DSP plus the preset's own overhead come to about 90%, so a path with two NAMs has room for little else. The usual layout: both NAMs on one path, the effects on the other path, Path 1 feeding Path 2. |
| | The Floor's DSP budget enforces this: a block that would overload the DSP is refused when you add it. |
| | **HX Edit can drop NAM blocks** when it rewrites a preset (it doesn't know the model). Build and edit NAM presets on the unit. |
| **In progress** | Long, realistic soak tests of real two-NAM presets (footswitch and pedal activity, hours). |

## How it works

- **Captures travel as User IRs.** The converter (upstream's setup page or `tools/nam2ir.py`) packs a `.nam` A2 Lite capture into a `.wav` that HX Edit imports as a User IR. The NAM block's **Model** knob picks the IR slot, and the kernel reads the capture's weights from it.
- **The kernel** is upstream's NAM A2 Lite, written in SHARC assembly, adapted to the Floor's DSP memory map (`helix-floor/floor/nam_floor5.py`). It is checked bit-exact against a reference implementation in a SHARC simulator at every build.
- **Memory:** the Floor's DSP program leaves far less free on-chip memory than the Stomp's. The build trims each DSP's third "big" block slot to a normal one (so a path holds at most two amp-type blocks), and the kernel streams each layer's weights and its long delay lines from SDRAM through external-port DMA channel 0.
- **The DSP budget:** each block declares a cost, and the Floor refuses blocks past its limit. NAM's cost is set from the measured load (3,600 units, about 35% plus overhead), so the Floor's own check keeps presets from overloading.
- **No firmware is distributed.** You build your own file from Line 6's stock 3.80.0 file on your own computer.

## What we found

The useful facts from porting and debugging on real hardware. Details and the full history are in [helix-floor/docs/FINDINGS.md](helix-floor/docs/FINDINGS.md).

- **The freeze:** earlier builds froze the screen and buttons at random (audio kept playing), roughly every 15 minutes with a NAM block loaded. Cause: the Floor's DSP program reroutes its interrupts at boot, and the one the kernel paused during every call was **link port 1, the line between the Floor's two DSPs**, not the DMA channel the kernel uses. Holding or losing that interrupt stalled the DSP-to-DSP messaging, which also made controller edits laggy. The kernel no longer touches interrupts at all. The external-port DMA channels turned out to raise no interrupt on either the Floor or the Stomp.
- **Split paths are fine.** An earlier "52% in a split path" reading was a +3 dB pan-law gain on the measuring signal, not a slower block.
- **Memory reservations are hard limits.** Block slot sizes and heaps below the stock values make the Floor fail to boot. Free memory can only come from turning a big slot into a normal one.
- **Scatter/gather DMA works on this chip**, with post-modify addressing: block *i* starts at the external index plus tap-list entry *i* (the reference manual's table reads like pre-modify). On the unit it gave no measurable speedup over plain chained DMA: the per-transfer overhead is smaller on hardware than the simulator assumed.
- **Using DMA channel 1 as well hung the unit** (dead audio, then no USB). Not understood yet, so channel 1 is not used.
- **Simulator vs hardware:** the arithmetic is exact, but DMA timing in the simulator is a guess. It is now calibrated against meter builds that report the real cycles per call through the audio output.

## Possible today

- One or two NAM A2 Lite blocks per path, four per preset.
- Stereo rigs: a Split Y with one NAM on each side, panned left and right, on one path, and the effects on the other.
- Any NAM A2 Lite capture you can convert. A "full rig" capture (amp + cab) saves the IR blocks.

## In progress

- Hours-long soak tests of real two-NAM presets under realistic use.
- Mapping how much effects headroom a two-NAM path really has, and fine-tuning the declared cost.

## Future

- **Faster kernel:** port upstream's newer work (delay lines in block memory, block-conflict stall fixes) to get NAM well below 35% of a DSP, and with it more room next to two NAMs.
- **Three NAMs per DSP**, as upstream reaches on the Stomp, if enough memory can be freed safely.
- **Keeping NAM blocks in HX Edit**, by giving NAM a stock model's preset ID with matching knob types (upstream's approach).
- Upstream's later features: loudness normalisation, the capture name in the block title, a Polarity knob.

## Build, install and recovery

**Easiest: the setup page, [savedadodo.github.io/helix-floor-nam-lite/floor-web/](https://savedadodo.github.io/helix-floor-nam-lite/floor-web/)** (source in [`floor-web/`](floor-web/index.html)). It builds the firmware from your stock file in the browser (and checks it is byte-for-byte the tested build), batch-converts your `.nam` captures into User IR `.wav` files numbered by slot, gives you a printable slot list, and walks through install and recovery. Nothing is uploaded.

Or by hand: see [helix-floor/README.md](helix-floor/README.md). In short: you need Line 6's stock `Helix_Floor_v3.80.0_0x7d01f5efb.hxf`, Python 3.10+ and `capstone`; the build checks every stage and writes a new `.hxf`; install it with Line 6 Updater (Offline Mode, local file); recovery is holding footswitches **6 + 12** at power-on, then installing the stock file. Presets survive.

**Please don't share a built `.hxf`.** It is Line 6's firmware with changes, not yours or ours to redistribute.

## Credits

Upstream [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite) (the NAM A2 Lite kernel, SHARC toolchain, converter and setup page). [Neural Amp Modeler](https://github.com/sdatkinson/neural-amp-modeler) by Steven Atkinson. Licensed as upstream (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
