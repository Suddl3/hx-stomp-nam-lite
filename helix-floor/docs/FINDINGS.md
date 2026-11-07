# NAM A2 Lite → Helix Floor: firmware map (read-only)

Source: `Helix_Floor_v3.80.0_0x7d01f5efb.hxf`, MD5 `805caa03e8a30fd6ff7892f32ed5a9f4`.
Compared against what `nocaseguy/hx-stomp-nam-lite` (proven on a real HX Stomp 3.80.0) patches.
Nothing has been written to any device. All reads were done with our own scripts (`scripts/`, `review/`); the upstream repo's scripts were not run.
Independently reviewed on 2026-10-31. Corrections from that review are folded in below and marked *(review)*.

**Status: not ready to build.** The main program side is close. The DSP side needs a Floor-specific memory layout for the NAM kernel.

## Archive layout

| Floor entry | Stomp entry | What it is | Notes |
|---|---|---|---|
| 0 (type 2) and 1 (type 3) | 0 | Main program, LPC43xx M4 + M0, magic `0x230b0c5e` | Byte-identical copies. Which one the bootloader runs, and whether it compares them, is **unknown**: patch both. |
| 2 | 2 | SHARC ADSP-21469 LDR boot stream | 0x7bdc0 B (495 KiB). Headroom under the repo's 512 KiB assert: 16,960 B. The real slot looks like ~1 MiB (Entry 2 at eMMC sector 0x8007, Entry 3 at 0x880a), unverified. |
| 3 | — | Small program for another MCU (`mcu/ui/src/app/app.c`) | Not touched. |
| 4 | 3 | Model DB (`0x4023245e`) | **863** models (the Stomp has 864; the repo hard-codes 864), 4,244 strings |
| 5 | 4 | DSP graph library (`0x28267e5e`) | 863 blobs, Blob 0 = `0x7a612` words, 457 composites |
| 6 / 7 | — | I/O model DB + graph lib (`sqAudio0/1`, LinkPort) | |
| 15 | — | `cabpkg` (stock cabs) | |

- The `.hxf` has **one** `dinf` and no trailer (the Stomp has two). The repo's `hxf.pack` only updates the `dinf` when there are two, so it must be changed for the Floor *(review)*.
- **Both SHARCs boot this same Entry 2** (confirmed): `0x281157ac` opens two eMMC streams at sector 0x8007, and `0x100059e0` boots DSP 0 and DSP 1 from them. One kernel injection serves both paths *(review)*.

## Main program (Entry 0)

4 segments:
- seg0: `0x10000000` + `0x11870` (local SRAM bank 0)
- seg1: `0x10088a30` + `0x3008`
- seg2: `0x28000000` + `0x156d20` (SDRAM)
- seg3: `0x20000000` + `0x66c4` (M0 image)

| Item | Floor | Notes |
|---|---|---|
| Table 1 (12-byte rows) | 823 rows at `0x2813520c` | Same as the Stomp |
| `TAB1_BASE_PTRS` | `0x28134d70`, `0x28134dbc`, `0x28134dd4`, `0x28134ec8`, `0x28134f80` | 5, all used |
| `TAB1_END_PTR` | `0x28134db8` **only** | `0x28134de4` holds the same value but is the base of a separate 7-entry table that starts right after Table 1 (`0x28134ddc`). **Don't patch it** *(review)*. |
| `TAB1_CNT_INSN` | `movw r0,#823` at `0x28134dc0` | |
| `TAB1_CNT_M1_INSNS` | `0x28134da8`, `0x28134e32`, `0x28134eda` | 3 is complete: a whole-program search found no others *(review)* |
| Table 2 (44-byte rows) | 823 rows at `0x280e0280` | One pointer (`0x280e027c`), count `movw ip,#823` at `0x280e01dc`. No `+5` pointer; nothing else touches it *(review)*. |
| `BLIST_PTR_TAB` | **`0x28134220`** | Corrected *(review)*: earlier note said `0x28134240` |
| `BLIST_CNT_TAB` | **`0x28134350`** | |
| `SUBCAT_CNT` | **`0x28134480`** | |
| `SUBCAT_NAMES` | **`0x281344cc`** | getter `0x28126c3a`. Same spacing between the four tables as the Stomp. |

- **Category numbers are the same as the Stomp's** *(review)*: 2 = Distortion, 11 = Amp+Cab, 12 = Amp (folders Guitar, Bass; 2 free), 15 = IR, 16 = Volume. Clarity sits in lists (11,0), (11,2) and (12,0), as on the Stomp. So `folder=(12, "NAM")`, `FX_CATEGORY_IDS` and the IR == 15 test port as they are.
- Preset ids must be ≤ 832 (reverse map of 833 entries at `0x284c8758`). Free: 380–383, 516–518, 572, 605, 768. **147 and 148 (the Stomp build's ids) are taken** (`HD2_AppDSPFlow1Input` / `HD2_AppDSPFlow2Input`).
- **IR-name title sites found** *(review)*:
  - probable site B: `0x280ad37c` (`2b7b0f2b05d0`; the Stomp's is `2b7b0f2b51d0`)
  - probable site A: `0x280ac164` (`ldrb r3,[r6,#12]; cmp r3,#15; beq.w 0x280ac374`)
  - a third test at `0x280ac546`
  - The registers and branch forms differ from the Stomp's, so the cave must be rewritten.

### Where the relocated tables go

- SDRAM after the program is in use: startup zeroes `.bss` from `0x28156d20` to `0x285a3210`, and `0x285a3210` is an eMMC read buffer (`0x2807c104`). So the Stomp's "append to the last segment" trick doesn't work.
- No slack after any table, and no dead rows to reuse.
- **Candidate home: local SRAM `0x10011870..0x1001ffff` (59,280 B)**, by growing seg0. No code reference into it, no MPU setup, no heap or stack bound there (checked by us and by the reviewer).
- **Size budget** *(review)*:
  - add-model also relocates the two Amp+Cab lists that contain Clarity (95 × 48 B each). Total 55,312 B: **fits, with ~4 KB spare**.
  - add-fx-model appends another full Table 1 + Table 2 (~46 KB), and the ir-title cave comes after that. **Doesn't fit**: either drop the FX version, or relocate the tables only once with both new rows.
- **Untested alternative:** seg2 starts with a byte-identical copy of Entry 2 (`0x28000000..0x2807bdc0`, ~495 KB) that no code literal points into. If it's really dead, it could hold the tables in SDRAM with no segment growth. Rule out any update or repair path that reads it before using it.
- **Can't prove from the file:** whether the bootloader uses bank 0 above `0x10011870` while loading, or caps segment sizes. Needs the hardware recovery test.

## Model DB / graph library

- Donor: `HD2_AmpLine6Clarity`, id 804, blob 804, string 3805. Top composite **`0x6001aa`**: in → `0x6001ba` (1 in / 1 out, dm 0x3f9 / pm 0x164) → out. Shared with Voltage, Kinetic and others. The repo hard-codes `0x6001a9`; on the Floor that is Ventoux.
- **Amp harness ids are shifted by 1** *(review)*: Floor `0x60000d`, `0x60000e`, `0x600010` with placeholder `0x6000c9` (Stomp: `0x60000c/d/f`, `0x6000c8`). `0x600007` also holds `0x6000c9`. The `0x63000` per-slot SDRAM limit is unverified on the Floor.
- The NAM parameter sources exist (`HD2_ImpulseResponse2048Mono` Index, `VintagePre` Polarity), as do all `FX_CLONES` and `HD2_VolPanVolMono`.
- The repo's `add_model_entry3/4` hard-code 864 models/blobs. On the Floor that would copy table junk in as a fake model 863. **Must use 863.**

## DSP program (Entry 2)

- Blob 0 (graph) buffer, Heap 6. Three patch points, as on the Stomp:
  1. size `R0 = 0x0007a612` at words 38846/38847 (Stomp 37192/37193)
  2. start `R23 = 0x297318` at w43531, end `R19 = 0x2af64b` at w43536 (Stomp 41966/41971)
  3. **clear start `R4 = 0x297318` at w43540/43541** (Stomp 41975/41976). This one was missing *(review)*. Leaving it out would clear the enlarged tail.
- The Floor's buffer base is `0x21cd06` (w38850), not `0x21c400`. Heap 7 starts at `0x2af64c`, so in place the buffer can grow to at most `0x92946`.
- Primitive registry: INIT_L32 block at w112674, `0x200000`, 290 records × 8 words `[id, init, f2, f3, ctrl, process, dm, pm]`. Same layout as the Stomp. `0x9c75` is not registered.
- Unused primitives *(review)*: of 20 graph-unreferenced registered ids, **16** are also on the Stomp's unused list, including `0xe` @ `0x2001e8` and `0x87` @ `0x200500`. Avoid `0x4e`, `0x4a`, `0x50` (a low-id system/I-O block). Suggested hook: `0x128` @ `0x200088`.

## Floor SHARC memory map (2026-10-31, `dsp/occupancy.py` + heap-init constants)

The code is mostly VISA (compressed) instructions in short-word space: `0x13b4f2..`, `0x16e770..0x17bfff`, `0x182508..0x1848c2` (tag-3 blocks). There are only 0x2b1 plain 48-bit instructions, at `0x8c100..0x8ef85`.

Heap table (start/end immediates set at boot, Entry 2 words 43424–43582):

| Heap | Range (normal words) | Size | Where |
|---|---|---|---|
| a | `0x96ba4..0x9ba5f` | 0x4ebb | Block 0 |
| b | **`0xe4466..0xe674a`** | 0x22e4 | Block 3 |
| c (big) | **`0x328000..0xed7000`** | 0xbaf000 | DDR2 |
| d | `0x9bb60..0x9c530` | 0x9d0 | Block 0 |
| e | `0xb2000..0xb73b8` | 0x53b8 | Block 1 |
| 6 (Blob 0 tail) | `0x297318..0x2af64b` | 0x18334 | DDR2 |
| 7 | `0x2af64c..0x2af982` | 0x336 | DDR2 |
| f, g | `0x9c530..0x9cfa7`, `0x9cfa8..0x9da1f` | | Block 0 |

What the NAM kernel needs (the Stomp layout, `nam_multi.py`) vs what the Floor has free:

| Kernel need | Stomp location | Floor free | Fits? |
|---|---|---|---|
| Hot code + staging, Block 2 | `0xc4ef8..` (48-bit) → normal `0xc7674..0xc8000`, ~2.4K words | **Block 2 completely used** (`0xc0000..0xc8000`) | **No** |
| Slots, rings, tables, cold code, Block 3 | `0xe4850..0xe8000`, ~13.7K words | `0xe729a..0xe8000` only, **0xd66 words (3.4K)**. The Floor's Block 3 heap (b) and zero data cover `0xe41de..0xe729a`. | **No** |
| DDR2: moved Heap 6 + tone table | `0x30d100..0x328000` | `0x30dac0..0x328000` (`0x1a540` words) before heap c. Heap 6 moved to `0x30dac0..0x325df4` leaves `0x220c` words; the kernel's DDR2 needs ~`0x7e5`. | **Yes** |
| Blob 0 growth in place | +0x17354 words | to `0x2af64b`, max `0x92945` (needs `0x91966`) | **Yes, ~4K spare** |
| User IR store `IR_FLAG`/`IR_TOP` | `0x2ab56e`/`0x2abded` (right after the Stomp's Heap 6) | **not found yet**: the Floor's heap 7 is only 0x336 words, so the IR store is somewhere else | ? |

### Stomp comparison (2026-10-31, stock `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 verified, unpacked in `work/stomp`)

- **Same DSP program design, shifted.** The Stomp has the same heap table in the same order (`dsp/heaps.py`). The Block 3 heap is the same size on both (Stomp `0xe1a00..0xe3cf1` = 0x22f1; Floor 0x22e4), and so are the big DDR2 heap `0x328000..0xed7000` and the Blob 0 / Heap 6 / Heap 7 pattern.
- **User IR store found** (same structure as the Stomp): `IR_FLAG` = end of Heap 7 = **`0x2af982`** (Stomp `0x2ab56e`). IR data starts at the flag table + 0x80 = `0x2afa02` (Stomp `0x2ab5ee`). Both values are used at the matching places in the DSP code (Floor w43878/43918/43899, Stomp w42448/42487/42469). So **`IR_TOP` = `0x2b0201`** (Stomp `0x2abded`, same +0x87f).
- **Hook handlers found:** the Stomp hook copies primitive **`0x822`**'s handlers (Stomp `[0x611e90, 0, 0x611ef4, 0x611ddd]`, dm 0x91, pm 0xd). Floor `0x822` = **`[0x61343a, 0, 0x61349e, 0x613387]`**, same dm/pm.
- **On-chip memory per block** (physical blocks inferred from the boot data: B0 `0x92000..0x9e000`, B1 `0xb2000..0xbe000`, B2 `0xc0000..0xc8000`, B3 `0xe0000..0xe8000`):

| Block | Stomp free | Floor free |
|---|---|---|
| 0 | 0x182 | 0x180 |
| 1 | 0x2d | 0x2c |
| 2 | **0x994** (the kernel's code goes here) | **0x7** |
| 3 | **0x37bf** (the kernel's data goes here) | **0xd67** |

  The Floor's static code and data use 0x98d more words in Block 2 and 0x2a58 more in Block 3. That's about **13.3K words short in total**, with nowhere else free on chip. Shrinking the Block 3 heap can't cover it: the heap is only 0x22e4 words, and the Stomp's is the same size.

**Conclusion:** the NAM kernel as designed **does not fit the Floor's fast on-chip DSP memory**. It needs ~16K words of Block 2/3 RAM, and the Floor has ~3.4K free there. The Floor uses that space for a bigger Block 3 heap (b), most likely because each Floor DSP runs a larger signal path than the Stomp's single DSP. Options, none proven:
1. Shrink the Floor's Block 3 heap (b) to make room. That takes fast memory from stock effects; which ones need it, and how much, is unknown.
2. Re-design the kernel for less on-chip RAM: one slot per DSP, more state in DDR2. Slower: more DSP load per block than the Stomp's ~29%.
3. Compare against the Stomp's own Entry 2 to see why the Stomp had this space free. **Needs the stock `HX_Stomp_v3.80.0_0x103966115.hxf`** (MD5 `a2cd8f4ae56f49415380270ebc484bf1`). That comparison would also find the Floor's User IR store and the hook functions (`0x611e90`/`0x611ef4`/`0x611ddd`) by matching code.

### Repacking the kernel: first read (2026-11-01, from `nam_multi.py` / `nam_multi_kernel.asm`, not yet run)

- The kernel already keeps its long rings (dilation ≥ FAR_D) in SDRAM and streams their taps in by chained external-port DMA, double-buffered. On-chip it keeps per slot: state, the tone stack, **the model's 1,943 weight words**, and the short rings. Globally on-chip: about 2.4K words of hot code (Block 2), cold code (top of Block 3), TCB chains, and the job, layer, Drive and fade tables.
- On the Floor, everything would have to go into Block 3's 0xd67 (3,431) words. Hot code (~2.4K normal words) plus one slot's weights (1,943) already exceed that. So **repacking alone can't fit the current design**. It needs one of:
  - (a) stream each slot's weights from SDRAM by DMA every call, like the far rings, keeping only code, staging buffers and the near rings on chip;
  - (b) one slot per DSP (the Floor has 2 DSPs, so still up to 2 NAM blocks per preset, one per path) with (a);
  - (c) run the cold or rarely-used code from SDRAM, if the 21469 can fetch code externally (unverified).
- Sizing each option exactly needs `nam_multi.layout()` run with different slot counts and staging settings, then the simulator's bit-exact check plus a DMA timing estimate for the cost.

### Scoping result (2026-11-01, upstream code run: baseline 48 tests pass, including the byte-exact Stomp build)

Measured with `nam_multi.Layout` (`scope/layout_report.py`). Code: hot 1,090 instructions = 1,635 normal words; cold 196 instructions = 311 words; **code total 1,946 words**.

| Layout | On-chip words needed (data + code) |
|---|---|
| 2 slots, stock far rings (d ≥ 41) | 13,760 |
| 2 slots, every ring in SDRAM | 10,662 |
| 1 slot, stock far rings | 9,000 |
| 1 slot, every ring in SDRAM | 7,846 |
| **Floor Block 3 free** | **3,431** |

One slot is 2,814–4,758 words (the model's 1,943-word stream, state, tone stack, short rings). The shared tables and TCB chains are ~3,086 words.

**Pushing more into SDRAM can't close the gap:** even the smallest layout is more than twice the free space.

**The route that does fit: take NAM's memory the way stock blocks do.** Every stock block declares per-instance DSP memory in its graph member (`dm_words`; Clarity's amp declares 1,017). The DSP's allocator hands it out from its heaps when the block is added, and "DSP full" accounting covers it. Per Floor DSP those heaps hold roughly 58K words (Block 0: 0x4ebb + 0x9d0 + 2 × 0xa77; Block 1: 0x53b8; Block 3: 0x22e4). The Stomp kernel instead takes **static** memory (fixed slots in Block 3's free tail) and declares only 145 words. Refactored:

- **Static on chip:** only the code, 1,946 of the 3,431 free words in Block 3 (fits, with ~1,485 to spare for a few globals).
- **Per instance, from the stock allocator:** each NAM block's slot (state, weights, near rings, tone stack, staging and TCBs): about 5–8K words, comparable to a heavy stock block. Long rings stay in each instance's SDRAM block, as now.
- **Result:** NAM blocks behave like any other amp. The Floor adds them while DSP memory lasts and says "DSP full" when not. No fixed slot limit, and both Floor DSPs can host them. Speed should stay close to the Stomp's ~29% per block (same algorithm, same far-ring split), though heap blocks may share memory banks with the code, which can cost a few percent.

**What that needs (the next work):**
1. Find how the Floor's DSP allocator picks a heap for `dm_words` and the largest single allocation it allows (dispatcher disassembly; the Stomp's is the same design, so it can be checked on both).
2. Refactor the kernel from global slots (`SLOTTAB`, `NSLOTS`, owner/LAST words) to "my slot is my instance memory" (I0-relative). The ownership logic goes away, which simplifies the kernel. It keeps the same arithmetic, so it stays bit-exact against `nam_a2.asm` in the upstream simulator.
3. Move the hot code from Block 2 to Block 3 (the 48-bit address changes; the instruction fetch then shares Block 3 with the cold code).
4. Run the upstream check (`KernelCheck`) on the refactored kernel, with Floor addresses (`IR_FLAG 0x2af982`, `IR_TOP 0x2b0201`, hook handlers from `0x822`).

**Verdict:** feasible, as a medium-size refactor of the kernel's memory handling, not a rewrite of the DSP math. Odds are better than the 50/50 estimated before scoping, and the result matches the goal ("like any other amp"). The main unknown is item 1.

### Allocator analysis (2026-11-01, `alloc/harness.py`, `alloc/paths.py`, `alloc/heapsum.py`): the scoping route above is WRONG

There is no free pool. DSP memory is **pre-carved into fixed per-slot budgets** that use the heaps up exactly:

- Each DSP's path graph (Floor `0x600000`, `0x600001`; members are block slots) declares a fixed DM/PM/SDRAM budget per member (record words 13/14/15). The sums match the heap sizes to the word:

| | DM (r13) | PM (r14) | SDRAM (r15) |
|---|---|---|---|
| `0x600000` sum | 0x4ebb | 0x22b3 | 0xbaf000 |
| `0x600001` sum | 0x4e94 | **0x22e4** | 0xbae400 |
| Heap | **a = 0x4ebb** (Block 0) | **b = 0x22e4** (Block 3) | **c = 0xbaf000** (DDR2) |

- So heap a holds every slot's DM, heap b every slot's PM, heap c every slot's SDRAM, sized for the worst-case graph. Heaps d, e, f, g: purpose not yet known (e is Block 1, 0x53b8).
- Per DSP: **16 block slots** (composite `0x600006`): 13 with DM 0x3ae / PM 0x1e6 and 3 with DM 0x75c / PM 0x30c (each SDRAM 0x63000). The big ones are probably the amp-capable slots.
- The Amp harness (`0x60000d/e`, `0x600010`) gives the model placeholder **DM 0x596 (1,430) + PM 0x1fa (506) + SDRAM 0x800**: identical on Stomp and Floor. Upstream raises only the SDRAM part (`raise_amp_harness_sdram`); a request above the budget fails to bind (silent block).
- So a NAM block can get at most ~1,936 on-chip words per instance from the stock system, against the 2,814–4,758 words one kernel slot needs plus ~3,086 words of shared tables. **"Take 5–8K per instance from the allocator" is impossible without changing the budgets.**
- The Stomp kernel fits only because the Stomp's Block 3 has 0x37bf words outside any heap.

**Routes left:**
1. **Budget slack audit (measurement only):** compute what each stock model actually needs against its slot budget. If the 0x3ae/0x75c budgets have real slack across 16 slots, shrink them, shrink heaps a/b to match, and give the freed on-chip words to the kernel statically. Risk: a stock model whose need is undercounted then fails to bind.
2. **Slim kernel inside the amp budget:** code static in Block 3 (1,946 of 3,431 free), per instance ≤ 1,430 DM + 506 PM, weights streamed from SDRAM each call, all rings in SDRAM. Slower than the Stomp's ~29% per block, by an unknown amount (needs a DMA timing estimate in the simulator).
3. Find what heap e (Block 1, 21K words) holds; if it's over-sized it could be shrunk the same way.

### Budget slack audit (2026-11-01, `alloc/needs.py`): no slack

Each model's need = the summed member budgets of its top composite (861 of 862 model blobs are composites).

- DM: the heaviest effects need 0x3a2–0x3ae, the full normal slot (0x3ae). The heaviest amps need 0x546 against the 0x596 placeholder, and the amp+cab harness blob (844) needs exactly 0x75c, the big slot. Histogram (models 3..842): 468 under 0x100, 136 under 0x200, 46 under 0x300, 73 under 0x38c, 24 at 0x38c..0x3ae, 92 amp-sized (0x3af..0x596).
- PM: the top effects need 0x1e0/0x1e6 (slot 0x1e6) and the top amps 0x1fa (placeholder 0x1fa).
- **Line 6 sized every slot for its heaviest model.** Shrinking budgets would make those models fail to load in that position. Route 1 is dead as a free win.

**What could still work (a trade):** give up one big slot per DSP. That frees 0x75c DM (Block 0) + 0x30c PM (Block 3) = 2,664 words, plus the 3,431 already free in Block 3 = 6,095 static words per DSP. That would hold the code (1,946) + shared tables (~3,086), with the per-instance data in the amp placeholder (1,936 on-chip + SDRAM) and the weights streamed (route 2). Before offering it: find what the 3 big slots are for (which blocks need them, so what the user loses).

### What the big slots are for (2026-11-01, `alloc/bigmodels.py`)

Models whose need is over a normal slot (DM 0x3ae or PM 0x1e6): **only amps and preamps** (46 amp + 46 preamp models, the heaviest e.g. PV Vitriol Lead 0x546/0x1fa), plus the harnesses: Amp 0x59e/0x1ff, Amp+Cab 0x75c/0x30c, Amp+Cab+IR 0x5ba/0x20f, **Cab Dual 0x384/0x21e** (its PM is over the normal 0x1e6). Every amp goes through the amp harness (placeholder 0x596), so any amp block, light or heavy, needs a big slot.

So the 3 big slots per DSP = **up to 3 amp-type blocks per DSP chip** (amp, amp+cab, heavy preamp, dual cab), probably. Not yet checked: how the main program assigns slots (and whether it enforces this as a limit the user sees).

**The trade, concretely:** turn one big slot per DSP into NAM's permanent memory, so each DSP takes at most 2 amp-type blocks (4 on the whole Floor), NAM blocks included. This applies to every preset, NAM or not.

### Trade options sized (2026-11-01, `alloc/slots.py`, `scope/breakdown.py`)

The 16 block slots of each path graph are a pool (members m166..m181 of `0x600000`, all on buffers [0,1]; 13 normal, then the 3 big ones last, m179..m181, DM offsets 0x376e/0x3eca/0x4626). Routing is set at run time, so a slot is not a fixed UI position. Deleting one costs a block, not a position.

Kernel need for one NAM block per DSP (code 1,946 + globals + slot):

| Far rings in SDRAM from d ≥ | globals | slot (with weights) | total |
|---|---|---|---|
| 41 (Stomp 2-slot) | 2,233 | 4,758 | 8,937 |
| 1 (every ring) | 2,875 | 2,814 | **7,635** |

Weights are 1,943 of each slot. On-chip available per DSP, one NAM block:

| Option | Static | + amp placeholder | Total | Fits |
|---|---|---|---|---|
| A: big slot → normal (keeps 16 blocks per DSP) | 3,431 + 942 DM + 294 PM = 4,667 | 1,936 | 6,603 | only with weights streamed from SDRAM (5,692 needed) |
| B: delete one big slot (15 blocks per DSP) | 3,431 + 1,884 + 780 = 6,095 | 1,936 | 8,031 | weights on chip, every ring in SDRAM (7,635, 396 spare) |

Both need the main program to know a big slot is gone (else a third amp gets a slot it can't bind in, probably a silent block): not yet researched. Option A's speed depends on weight streaming, which needs a simulator measurement. Option B is closest to the Stomp design.

**Decision (2026-11-01): option B.** the owner's presets (`alloc/presets.py` on a set of real presets) peak at 10 blocks and 1 amp (+ 1 single cab) per DSP, well inside 15 blocks and 2 amp-type blocks.

## Blocking issues before a build (ranked)

1. **The NAM kernel's memory layout collides with the Floor SHARC** *(review)*:
   - The kernel's PM `0xc4ef8..0xc5554` lands on Floor LDR data (w50763..w50868).
   - Its Block 3 data `0xe4842..0xe8000` overlaps a Floor zero block (`0xe41de..0xe729a`).
   - The Stomp's new Heap 6 home `0x30d100..0x324497` overlaps Floor data `0x30cb73..0x30dac0`, and runs into the kernel's DDR2 `0x324500..`.
   - The kernel's User IR store addresses (`IR_FLAG`/`IR_TOP` `0x2AB56E`/`0x2ABDED`), idle word `DM(0xC2FD5)` and `STOMP_DBU` are all Stomp-specific.
   - **Needs: a full Floor SHARC memory map (free PM, DM and DDR2; where User IRs live), then a re-layout of the kernel.** This is the biggest remaining job.
2. **Hook id:** `nam_host_member` hard-codes member type `0x9c75`, but the hook writes the slot's own id. On the Floor (no `0x9c75`), the host member must use the chosen slot's id (e.g. `0x128`).
3. **Hook record function addresses** (`0x611e90`, `0x611ef4`, `0x611ddd` on the Stomp): Floor equivalents not found yet. Needs SHARC disassembly.
4. **Code changes needed** (patcher parameters): the 863 count, the harness ids, the `0x6001aa` donor, the corrected table bases, `TAB1_END_PTR` (one only), the third Heap 6 word, the single-`dinf` packer, patching Entry 0 and Entry 1 both, and preset ids from the free list.
5. **Entry 0 space:** add-model fits; add-fx-model and the ir-title cave need a re-budget (relocate once, or use the seg2 copy if proven dead).
6. **Partition limits** (`E0_MAX`, `E3_MAX`, `E4_MAX`, the bootloader's app and segment caps) are Stomp numbers. Unverified on the Floor.

## Open risks (need hardware)

- No run-from-RAM path for the Floor: every test is a real install.
- Floor recovery (update-mode buttons, reflash of stock) not yet tested.
- Bootloader behavior with a grown seg0, and with Entry 0 vs Entry 1.
- DSP budget per block (~29% on the Stomp) unmeasured on the Floor.

## Stereo / two NAM per DSP measured (2026-11-01)

**Correction to option B sizing:** far_d 1 (every ring in SDRAM) is not a valid layout. `scope/cost.py 1` fails KernelCheck ("15 of 16 samples differ"): a far ring's taps are prefetched by DMA before the 16-sample block, so a layer with dilation < 16 would read samples computed in the same block. Smallest valid cut-off is far_d 17 (dilations 1/3/7/13 stay on chip). Sizes (code 1,946 + globals + slots, staging b3):

| far_d | 1 slot | 2 slots | SDRAM/inst |
|---|---|---|---|
| 41 | 9,000 | 13,760 | 18,658 |
| 17 | 8,266 (globals 2,498, slot 3,822) | 12,088 | 19,810 |

So plain option B (8,031) is **235 words short**. Fix: also delete one normal slot (+942 DM + 486 PM = 1,428).

**Stereo block (one capture, two channels):** weights (1,871 words) shared; second channel = slot 3,822 − 1,871 = 1,951 (state, heads, near rings, silence state; an upper bound). Total ≈ 10,217. Far rings: 2 × 19,810 SDRAM words, well inside a big slot's 0x63000.

**Pools per DSP:** 3,431 free Block 3 + 2,664 per deleted big slot + 1,428 per deleted normal slot (static); + 1,936 per NAM block in a remaining big slot (its amp placeholder, per instance; only the slot's spill beyond it must be static).

| Config | Slots deleted per DSP | Blocks/DSP | Amp-type spots | Need | Have | Spare |
|---|---|---|---|---|---|---|
| 1 mono NAM | 1 big + 1 normal | 14 | 2 | 8,266 | 9,459 | 1,193 |
| stereo NAM (+1 stock amp) | 1 big + 2 normal | 13 | 2 | 10,217 | 10,887 | 670 |
| 2 mono NAM | 1 big + 2 normal | 13 | 2 (both NAM) | 12,088 (static 8,216) | 12,823 (static 8,951) | 735 |

The 13-block layout runs either: two mono NAM blocks, or one stereo NAM + one stock amp, or two stock amps. Caveat: the static pool is split across Block 0 DM, Block 3 and PM, so the kernel's data must be laid out across non-contiguous regions (not yet tried; fragmentation could eat some spare).

**Processing (KernelCheck, slots 2, `scope/cost.py`):** far_d 41 (Stomp layout) steady mean 24,197 / worst 30,226 instructions per block; far_d 17 mean 25,010 / worst 31,819 (+3–5%). Stomp unit measured ~24% DSP per block (README), so Floor ≈ 25% per mono block, ≈ 50% for two blocks or one stereo block (stereo kernel not written; assumed 2× minus shared model checks).

**Three block types requested (2026-11-01):** mono (1 capture), stereo same-capture, stereo dual-capture (2 captures, one block). Memory is the same as weight sets + channel states (dual = 12,088, like 2 mono), but a single block gets only one amp placeholder (1,936), so dual-in-one-block needs static 10,152 vs 8,951 in the 13-block layout: short ~1,200. It fits only with a third normal slot deleted (12 blocks/DSP, static 10,379, spare 227: too tight given fragmentation). Two mono NAM blocks on a split give the same sound in the 13-block layout.

**Decision (2026-11-01):** dual-capture stereo block dropped. Target block types: mono NAM and stereo same-capture NAM, in the 13-block layout (delete 1 big + 2 normal slots per DSP); two mono NAM blocks per DSP also allowed. the owner will blend captures himself before import (must be retrained as A2 Lite captures; .nam files can't be merged).

## How the main program limits blocks per DSP (2026-11-01, Entry 0 disassembly)

Scripts: `scripts/callers.py` (bl call sites), `scripts/grepasm.py` (regex over Thumb disassembly), `alloc/costs.py` (DSP cost of big-slot models), `alloc/bigtag.py` (model-DB meta vs big-slot need: no tag; big = 46 of 111 amps + 46 of 113 preamps).

- **DSP Full:** `0x280b09f0` shows "DSP Full!" (2 s) when the chosen model's availability byte (model record +0x28, read by `0x28147b34`) is 0.
- **Availability** is computed per DSP in `0x2814b680..` for every category/model: available iff `[dsp+0xa88]` (current DSP cost total) − current block's cost (`0x28134fb4`) + model cost (record +0x2c) ≤ **9000** (`0x28135070`, `0x2328`). Model costs come from the Table 1 rows at `0x2813520c` (getter `0x28134e30`).
- **Cost alone does not cap big-slot models:** the cheapest big-slot preamps cost 1,025–1,400, so 7 fit in 9000.
- **Per-DSP counters** (`0x2811c804`, jump table on the block type byte at block +0x28, block records stride 0x9f4), stored at `[dsp+0xa90..0xaa0]`:
  - `0xa98` amp count: type 0x11 +1 (amp and preamp; .hlx `@type` 1 for both), 0x12 +1, 0x21 +1.
  - `0xa90` cab units: 0x13/0x1f +1, 0x14/0x15/0x20 +2 (dual), 0x21 +1 (amp+cab).
  - `0xa94`: 0xf +1, 0x10 +2, 0x12 +1 (IR family, unconfirmed).
  - `0xa9c`: type 0x16 count; `0xaa0`: count of models with ids 0x60a/0x61f/0x64c..0x660 (special models).
- **Limits applied in the availability pass (`0x2814b880..`):** when `[0xa98] == 2`, categories 0xb..0xd (amp family) are unavailable unless the block being replaced is itself type 0x11/0x12/0x21: **the stock Floor already allows at most 2 amp/preamp blocks per DSP.** Cab units and `0xa94` units are capped at 2 (cab dual counts 2).
- **So the 3 big slots are for 2 amps + 1 Cab Dual** (Cab Dual PM 0x21e > 0x1e6; at most one per DSP by the cab-unit cap).
- **No block-count limit in code:** 16 slots = 16 grid positions per DSP (A + B, 8 each), so the grid is the only limit.

Consequences for the 13-block layout (1 big + 2 normal slots deleted):
1. The "max 2 amp-type blocks per DSP" trade costs nothing new: stock already has it. The real loss is **2 amps + a Cab Dual on the same DSP** (the 3rd big slot).
2. Two ARM patches are needed so nothing binds silently: (a) a block-count cap (13 per DSP) in the availability pass and wherever a block is added or moved; (b) Cab Dual (and amp+dual cab) unavailable when `[0xa98] == 2`, and the 3rd amp case when a Cab Dual is present.
3. Not yet known: what the DSP does when a block finds no slot (assumed silent); whether preset load and HX Edit bypass these checks (HX Edit may keep its own copy of the rules).

Alternative without the Cab Dual loss: delete 4 normal slots and keep all 3 big (12 blocks per DSP; static 3,431 + 4 × 1,428 = 9,143 vs needs 6,330 mono / 8,281 stereo / 8,216 two mono). Still needs the block-count cap.

**Decision (2026-11-01): 13-block layout** (delete 1 big + 2 normal slots per DSP). Loss accepted: no Cab Dual on a DSP that has 2 amp/preamp blocks.

### Where a block-count cap would go (2026-11-01, partial)

- **Recount:** `0x2811d7dc` refreshes a DSP's state (`0x2811ce6c`, counters `0x2811c808` [entry is `0x2811c804` + 4-byte literal-pool word], `0x2811cd58`, ...). 5 callers: `0x28118d42`, `0x28118e60`, `0x28120070`, `0x281204ce`, `0x28125d3a`. The counter pass walks every block record of the DSP, so a block count can be added there (a spare word next to `0xa90..0xaa0`, e.g. `0xaa8`/`0xab4` are in use; free word still to find).
- **Browser (add/replace):** availability pass `0x2814b680..` (sets model +0x28). Cap: when the target position is empty and count ≥ 13, mark every model unavailable ("DSP Full!" then shows).
- **Move/paste into a DSP:** DSP-cost check `0x2811de44` (cost delta ≤ 9000 via `0x28135070`), called from `0x28125ada`, `0x28125cf4`. Cap there too. `0x2811dc08` (single-instance flag check, called from the availability pass) and `0x2811deac` (from `0x28148f16`) not yet labelled.
- **Cab Dual rule:** in the availability pass, categories with cab-unit +2 types (0x14/0x15/0x20) unavailable when `[0xa98] == 2`; and amp family unavailable when `[0xa98] == 1` and a dual cab (cab units from a 0x14/0x15/0x20 block) is present. Same in the move/paste check.
- Still open: preset load path (no checks expected, presets over the cap would get silent blocks), HX Edit (may run its own rules), DSP-side behaviour when no slot fits.

### Open checks closed (2026-11-01)

- **HX Edit** (`C:\Program Files (x86)\Line6\HX Edit`): `HX_ModelCatalog.json` / `.models` carry names, images and params, no DSP costs; the exe has no "DSP Full" text and reads `dspLoad0`/`dspLoad1` from the unit. So HX Edit leaves availability to the unit: the unit's rules (and our caps) apply. Not verified live.
- **Preset load:** the 9000 compare (`0x28135070`) has exactly two callers: the browser availability pass (`0x2814b7fa`) and the move/paste check (`0x2811de70`, via `0x2811de44` from `0x28125ada`/`0x28125cf4`). Preset load runs no budget or count check; stock relies on presets having been valid when saved. A preset over the 13-block cap (or 2 amps + Cab Dual on one DSP) would load unchecked.
- **DSP side, block with no fitting slot:** not resolved. The main program holds no slot sizes or slot ids (no refs to `0x600000`/`0x600006`), so slot choice happens on the SHARC side (Entry 2), and there is no SHARC disassembler in this project (upstream has an assembler and a simulator only). Outcomes range from one silent block to the whole DSP graph failing to load (all audio on that path lost). This must be tested on a spare unit before the owner's Floor; a preset-load guard should be considered if the outcome is the whole path.

## Floor memory plan, 13-block layout (2026-11-01, `scope/pieces.py`, `scope/floor_plan.py`)

Freed static on-chip regions per DSP, assuming the shortened heaps keep their starts (budgets carved in member order; unverified on the SHARC side):
- **R3, Block 0:** heap a tail, 0xeb8 = 3,768 words (1 big DM 0x75c + 2 normal DM 0x3ae).
- **R1, Block 3:** existing free tail `0xe729a..0xe8000`, 3,430 words.
- **R2, Block 3:** heap b tail, 0x6d8 = 1,752 words (1 big PM 0x30c + 2 normal PM 0x1e6).

Kernel pieces at far_d 17, 2 slots: hot code 1,635, cold code 294, two weight streams of 2,015 (72 state + 1,871 weights + 72 silence state), heads 102 per slot, globals 2,498 + X/IN/WBUF 220 (in Block 2 on the Stomp; no room there on the Floor) + 32 flags/report.

Packing (first-fit decreasing, hot code pinned alone in R2, stream A in Block 0, stream B in Block 3):

| Region | Size | Holds | Spare |
|---|---|---|---|
| R3 Block 0 | 3,768 | stream A, SB, OUTBUF, TABLE, WBUF, X, SLOTTAB | 4 |
| R1 Block 3 | 3,430 | stream B, cold code, JOBS, CLR, heads A/B, DRIVE_TAB, RCH0/1, WCH0..2, SAVE, HS, FADE_TAB, IN, LCH | 4 |
| R2 Block 3 | 1,752 | hot code, FARTAB, WADDR | 93 |

Static total 8,849 + 32 flags ≈ 8,881 of 8,950: **about 70 words spare.** Tight but it fits.

Near rings (1,704 per slot) go in each NAM block's own amp-placeholder memory, beside the 145 DM / 13 PM it uses now: **DM 1,285 free** ← layer 15 (600) + ring groups 0–2 and 7–9 (336 each) = 1,272; **PM 493 free** ← group 16–18 (336) + layer 14 (96) = 432. The kernel already finds each ring through its layer table, so the rings can be placed per layer; the slot base must be split into a static part (stream, heads) and per-instance parts (I0 / I8 based).

Modes:
- **Mono block:** stream A or B plus its instance's rings.
- **Two mono blocks:** both streams, each block's rings in its own instance.
- **Stereo block:** one instance. Shared weights in stream A, channel A's rings in the instance, channel B's state, heads and rings (1,950) inside stream B's area (2,015), which holds no weights in stereo mode. So a stereo block and a second NAM block can't run on the same DSP; the amp cap (2) and slot count allow it, so the kernel must play the second block silent or the ARM must block it.

Kernel changes this implies (upstream `nam_multi.py` / `nam_multi_kernel.asm`): Layout from fixed `B3`/`REP`/`CODE` bases to a list of regions; hot code moves from Block 2 to Block 3 (R2); per-slot ring bases from I0/I8; instance declaration raised to the placeholder's DM 0x596 / PM 0x1fa; a stereo mode.

**Speed risk:** on the Stomp, hot code sits in Block 2 apart from its data. Here hot code and stream B share Block 3, so instruction fetches can collide with data reads (the SHARC's conflict cache softens this in loops). The simulator counts instructions, not stalls, so the cost per block on the Floor is unmeasured; expect somewhat above the ~25% estimate, worst for a block using stream B.

## Floor kernel, steps 1–2 done (2026-11-01, `floor/nam_floor.py`)

Upstream `nam_multi.py` + `nam_multi_kernel.asm` untouched; `floor/nam_floor.py` imports them, patches the asm (4 text patches, `PATCHES`) and lays the kernel out for the Floor's 13-block regions (2 slots, far_d 17).

- **Asm changes:** hot code address is an `.equ` (CODE_PM); near layers take their ring base from the slot's pointer table (`M4 = DM(T_RB, I4); R10 = DM(M4, I6)`, one instruction fewer than upstream's slot + offset); `m_init` fills the pointers from RPTAB for the instance taking the slot (I0 + 146 / saved I8 + 14, rounded even); the model load's ring clear reads its bases through the pointers (CLR word 0 = pointer word << 16 | offset).
- **Placement:** hot code 1,088 instr at PM `0xe404c` (R2, Block 3, fills it); cold 226 instr at PM `0xe5468` (top of R1); slot cores 2,130 words at `0x9aba8` (R3, Block 0) and `0xe729a` (R1, Block 3); globals packed first-fit; RPTAB, CLR, DRIVE_TAB, FADE_TAB moved to DDR2 after the tone table (read at slot start / model load / once a call). Spare: R3 208, R1 2, R2 0.
- **Per instance:** DM block 1,418 of the placeholder's 1,430 (rings of layers 15, 0–2, 7–9); PM block 446 of 506 (layers 16–18, 14). SDRAM 19,810 words (far rings, HIST, sentinels).
- **Check:** upstream KernelCheck, bit for bit against the reference, all 14 steps (two models, crossfades, polarity, takeover, recreated, DMA timeout, busy channel, capture replaced) with a rig whose instance DM/PM blocks start on odd addresses, 0x600/0x200 apart, and every region's unwritten words random: **PASS**. Steady mean 24,991 / worst 31,797 instructions per block (upstream far_d 17: 25,010 / 31,819). Memory-bank stalls not modelled.

Next: stereo mode. Needs the stock calling convention for a stereo block (how a 2-channel primitive gets its input/output buffers) and whether an Amp-category block can be stereo at all in the ARM's block rules (stock amps are mono; Table 2 kind byte).

## Stereo NAM block: research (2026-11-01)

- **Amp-type blocks have no stereo variant.** Across the owner's .hlx presets, `@type` 1 (amp/preamp, 48 blocks), 2, 3 and 4 (amp+cab / cab family, 29 blocks) never carry `@stereo`; effects (`@type` 0, 7) and some IRs do. The amp harness is 1 in / 1 out. A stereo Amp-category NAM block would need a new stereo amp harness and ARM block-width rules: no stock pattern to copy.
- **A stereo effect-category NAM** (like upstream's Distortion > NAM, but stereo) would use the stereo FX harness: placeholder DM 0x3a2 / PM 0x1e0 (upstream FX_BUDGET), so about 784 DM + 466 PM free past the kernel's own words, against channel A's near rings of 1,704 (channel B's would go in stream B's static area). **Short ~450 words**, and the static spare (R3, 208) can't cover it.
- **The stereo primitive calling convention is unknown** (how a [0,1>0,1] primitive gets its two buffers): stock handlers are VISA code, which neither ssim nor any tool here decodes. Upstream's own stereo host (`0x600096`, primitive 0x9c51) has not been used with the NAM kernel.
- **Same sound without a stereo block:** two mono NAM blocks on a split, each loading the same capture, exactly as the owner's a two-amp stereo preset uses two Matchsticks. The kernel already runs two NAM blocks per DSP (2 slots, checked). Costs: two blocks to edit instead of one; ~50% of a DSP either way.

Recommendation: drop the stereo block. That also removes the "stereo + second NAM can't share a DSP" limit and the kernel's stereo mode.

**Decision (2026-11-01): stereo NAM block dropped.** Stereo sound = two mono NAM blocks on a split with the same capture. The 13-block layout stays (needed for 2 NAM per DSP).

## Main-program guards written (2026-11-01, `floor/arm_guards.py`, `floor/test_arm_guards.py`)

Block types (browser lists at `0x28134220`, counts at +0x130, `alloc/btypes.py`): 0x01 effects, 0x08 delay/reverb, 0x02–0x07 returns, 0x09–0x0e FX loops, 0x19–0x1e sends, 0x0f legacy cab, 0x10 legacy dual cab, 0x11 amp/preamp, 0x12 amp + legacy cab, 0x13–0x15 IR, 0x16 looper, 0x17/0x18 special synth/delay, 0x1f cab, 0x20 dual cab, 0x21 amp + cab. **Big-slot blocks:** a big slot is exactly the amp harness (placeholder DM 0x596 + cab placeholder 0x1c6 = 0x75c; PM 0x1fa + 0x112 = 0x30c), so every amp-family block (0x11, 0x12, 0x21) takes one whatever the model; the legacy dual cab (0x10, two legacy cabs, PM ~0x21a) too (inferred). New cabs (DM ≤ 0x27), IRs, sends/returns/loops, loopers: normal.

**The patch:** the stock budget check `0x28135070` (16 bytes, two callers) becomes `ldr.w pc, [pc, #0]; .word 0x10011871` (8 bytes). HOOK (224 bytes at `0x10011870`, the local-SRAM cave: **reserve 0x10011870..0x10011950**) keeps the ≤ 9000 test and, by return address:
- browser (`0x2814b7ff`; fp = DSP struct, caller [sp+0x38] = model entry, [sp+0x60] = target's type): unavailable if the target is empty and the DSP has ≥ 13 blocks; unavailable if the new block is big-slot and big-slot blocks + 1 − (replaced one big) > 2.
- move/paste (`0x2811de75`; r6 = DSP struct, r5 = 0 for an empty target): refused if the target is empty and the DSP has ≥ 13 blocks.
- Counting mirrors the stock counter `0x2811c804` (n records + 3, in-use bit, type 1..0x21).

**Test:** HOOK run in a small Thumb interpreter (capstone decode) against made-up DSP structs: 19 cases (budget edge, 12/13 blocks, replace at 13, extra records, unused and >0x21 records, amp caps, legacy vs new dual cab, IR, move cases): **PASS**, stack and r4–r11 preserved.

**Gaps (documented, not fixed):** moves don't apply the big-slot rule (the moved block's type isn't at hand); a move within the same DSP into an empty position may be refused at exactly 13 blocks (if that path uses the same check); preset load runs no check; the 3 extra records' meaning is unknown (counted if in use); applying the patch needs seg0 grown into the cave (bootloader behaviour unproven, hardware test).

## Floor build plan (2026-11-01)

Output stays in `build/` on this PC (personal build: never shared). Every stage checks its own result before the next.

| Stage | What | Status |
|---|---|---|
| A. Container | unpack (upstream `hxf.py`), checksums (upstream `l6ia_verify.py`: ALL OK on the stock Floor image), pack with the one-dinf fix (`floor/floor_hxf.py`, selftest: stock round trip byte-identical; grown payload updates dinf length, HEAD size, MD5) | **done** |
| B1. SHARC heaps | Heap a end −0xeb8, heap b end −0x6d8 (boot immediates, Entry 2 heap table words 43424–43582) | todo |
| B2. SHARC kernel | Inject `floor/nam_floor.py`'s sections into the LDR stream at the Floor regions; Floor constants: IR_FLAG `0x2af982` / IR_TOP `0x2b0201`, DDR2 base (free `0x30dac0..`, after a Heap 6 move), the idle word and STOMP_DBU (Stomp-specific in upstream) | todo |
| B3. SHARC hook | Register the kernel on an unused primitive id (`0x128` @ `0x200088`) with `0x822`'s handlers `[0x61343a, 0, 0x61349e, 0x613387]` | todo |
| B4. Blob 0 / Heap 6 | Grow Blob 0 for the new composite; the three patch points (size w38846/7, heap 6 start/end w43531/w43536, clear start w43540/1) | todo |
| C. Graph lib (Entry 5) | NAM composite from Clarity's `0x6001aa` (863 blobs); placeholder budgets DM 0x596 / PM 0x1fa used in full, SDRAM ≥ 19,810 words; **delete 1 big + 2 normal slot members** in the two path graphs `0x600000` and `0x600001` (the only ones with the 13+3 pool: the `0x6001e7..` hits of an earlier scan were past the 457-composite table, `0x6001c8` is the last) | todo |
| D. Model DB (Entry 4) | "NAM" amp model in Amp > NAM (863 models), preset id from the free list (380) | todo |
| E. Main program (Entries 0 **and** 1) | Grow seg0 into `0x10011870..`; guards (`floor/arm_guards.py`, cave `0x10011870..0x10011950`) + trampoline at `0x28135070`; Table 1/2 rows and browser lists relocated into the cave after the guards; `TAB1_END_PTR` `0x28134db8` only; counts 823 → 824 | todo |
| F. Final checks | `l6ia_verify` ALL OK; re-run KernelCheck and the guard tests on the bytes actually placed; diff report of every changed byte range | todo |

Skipped for the first build: the FX-category NAM, the IR-name title.

## First full build (2026-11-01, `floor/build_floor.py`): PC only, not installed, never share

`build/Helix_Floor_v3.80.0_NAM_PERSONAL.hxf` (47,799,168 B, MD5 `0eb95753e3abdbd5a1ef0ec2906f14bb`; payload MD5 `c9cd5c5d77e98ce17263d54be5ca930e`), from the stock file in one run. Every stage checks itself; `build/CHANGES.txt` lists the changed byte runs.

| Stage | Script | Result |
|---|---|---|
| 1 slots + heaps | `stage_slots.py` | 0x600000 members 177, 178, 181 and 0x600001 members 14, 15, 18 (last two normal + last big of each pool) get DM/PM/SDRAM 0, records kept. Heap a end `0x9ba5f→0x9aba7`, size `0x4ebb→0x4003`; heap b end `0xe674a→0xe6072`, size `0x22e4→0x1c0c` (w43455/43461/43467/43472): each = the larger graph's new sum. Heap c untouched. |
| 2 model | `stage_model.py` | Model 863 "NAM A2 Lite" (`HD2_AmpNAMLite`) on blob 863, browser groups 48, 49, 51; host composite `0x6001c9` (copy of `0x6001aa`), member 1 = primitive `0x128`, DM 0x58a / PM 0x1be / SDRAM 0x5000 (fits the placeholder's 0x596 / 0x1fa; harness SDRAM raised to 0x5000). Blob 0 `0x7a612→0x7b2d8` words, buffer cap `0x92946` (w38846), relocation check OK. Heap 6 `0x297318..0x2af64b → 0x30dac0..0x325df3` (w43530/43535/43540). |
| 3 kernel | `stage_kernel.py` | KernelCheck PASS at Floor addresses (IR_FLAG `0x2af982`, IR_TOP `0x2b0201`, DDR2 tables from `0x325e00`). 1,314 instructions + 3,866 data words as LDR INIT blocks before FINAL_INIT, each inside a freed region. Record `0x200088` = `[0x128, 0x61343a, 0, 0x61349e, 0x613387, 0xe404c, 0x58a, 0x1be]` (0x822's handlers, kernel entry, instance sizes = the member's). Entry 2 `0x7bdc0→0x819b0` B. |
| 4 main program | `stage_main.py` | Entries 0 and 1 (identical): seg0 `0x11870→0x1f160` (cave `0x10011870..0x1001f160`, 3,744 B left); HOOK at the cave start, trampoline at `0x28135070`; Table 1 823→824 at `0x10011950` (NAM preset id **380**, DSP cost **2700**), Table 2 823→824 at `0x10013ff0`, lists (11,0), (11,2) 94→95, new folder Amp > NAM (12,2). Read back and verified. |
| 5 checks | `build_floor.py` | `l6ia_verify` ALL OK; guard tests 19/19; slot sizes (below). |

**eMMC slots (inferred from the main program's sector constants, unverified):** Entry 2 at 0x8007, Entry 3 at 0x880a, Entry 4 at 0x890d, Entry 5 at 0x9110, I/O pair at 0x1cfbd/0x1cffe (tables `0x2811641c`/`0x28116438`). Entry 2 uses 0x819b0 of 0x100400; **Entry 4 0xf2688 of 0x100400 (56,696 B spare: tight)**; Entry 5 0xe141e4 of 0x27d5800. The SHARC boot loader (`0x100059e0`) reads LDR blocks until FINAL_INIT: no fixed 512 KiB cap found.

**Decisions taken without a hardware test (technical, reversible):** slots switched off by zero budgets, not removed (indices kept); registry instance sizes = the member's (not 0x822's 0x91/0xd); DSP cost 2700 (upstream 2345 + margin; tune after measuring); STOMP_DBU 11.5 kept (input-trim calibration for captures with level data; Floor value unknown).

**Risks, ranked (all need the spare unit):**
1. **Slot choice on the DSP side unknown.** If the main program or SHARC assigns pool slots by position, a block can land in a zero-budget slot → silent block. Zeroing (not deleting) keeps indices but doesn't remove this.
2. **Bootloader with a grown seg0** (59 KB more local SRAM image) and with Entry 0 vs 1; and whether anything uses local SRAM above `0x10011870` at run time.
3. **Instance sizes in the registry record** (`0x58a/0x1be` vs the handlers' `0x91/0xd` on 0x822): if 0x822's init handler assumes its own layout, the block could misbehave.
4. Heap 6's new place and the kernel's DDR2 tables (`0x30dac0..0x328000`) assumed unused by the Floor's SHARC code (occupancy scan only).
5. Real-chip speed (Block 3 code beside its data); DSP cost 2700 may be wrong either way.
6. Entry 4 slot tight (56 KB); slots inferred.
7. Gaps: moves don't apply the big-slot rule; preset load unchecked; IR title not shown (block title shows the model, not the IR name).

## Run from RAM on the Floor: first look (2026-11-01)

Upstream (`RAM_RUN.md`, `tools/hxf_ram.py`, `src/ramboot/`): the Stomp restarts into the LPC43xx boot ROM's USB DFU (`1fc9:000c`) via its app's "BootIntoDfu!" path (or Page Right at power-up); a 4 KB loader (`ramboot`) starts PLL1/SDRAM/eMMC (read only), takes the build into SDRAM, hooks the app's two eMMC functions (`read_blocks`/`write_blocks`, first 8 bytes → `ramboot_hook`) so changed sectors come from an SDRAM overlay and writes stay in SDRAM, and jumps. Nothing is written to the eMMC; a power cycle returns to the installed firmware.

What carries over to the Floor, found on the PC:
- **eMMC functions:** read `0x1000504c`, write `0x10005194` (seg0, local SRAM; card struct `0x10080000`; `[+0x248]` block shift, `[+0x250]` sector count, error lines 0x64f / 0x6d6). Every stream (incl. both SHARC boot streams) goes through them. Same shape as the Stomp's (args buf, sector, count), different prologue: `hxf_ram.py`'s byte check needs a Floor entry.
- **Startup:** zeroes bank 1 `0x10080280..0x10086a30` and SDRAM `.bss` `0x28156d20..0x285a3210`, then jumps to seg1 `0x10088a30`.
- **SDRAM use (literal references):** `.bss` + buffers to ~`0x285d0000`; fixed UI/stream structures `0x2971b950..0x298f03be` (stream contexts at `0x29822xxx`). Nothing referenced in `0x285d0000..0x2971b950` (~17.5 MB): free or a dynamic pool, not provable from the file. **Upstream's overlay area `0x29000000..0x29f00000` collides with the Floor's `0x2971b000..0x29900000` structures**, so the Floor needs its own layout (candidate inside `0x28600000..0x29700000`).
- **Not in the file:** the Floor's bootloader (SDRAM timing for `ramboot`'s `sdram.h`, framebuffers, its own DFU path).

**Main blocker:** the Floor's app has no "BootIntoDfu!". Its update mode is run by the app itself ("Entered Update Mode!" / "Boot Failure, Entered Update Mode!", `0x28115dca`, `0x28115f8e`), i.e. probably an app-level updater, not the boot ROM's DFU. Whether the Floor can reach `1fc9:000c` at all without opening the unit is unknown. **Cheap safe check (the owner):** put the Floor in update mode the documented Line 6 way, plug in USB, and note the USB device's VID/PID in Windows Device Manager (no Updater, nothing written; power cycle leaves it). `1fc9:000c` → the RAM path is open; Line 6's own ID → it isn't, without hardware boot pins.

## Pre-test work (2026-11-01)

- **Entry 1 left stock** (`stage_main.py` writes Entry 0 only and asserts Entry 1 is byte-identical to stock). Reason: the Floor's update mode is run by the app ("Entered Update Mode!"), so an untouched copy may be the way back; it also shows which copy the bootloader runs (no NAM folder = Entry 1 runs). Unknown: whether the bootloader requires the two to match.
- **IR name in the block title** (`floor/ir_title.py`, `floor/test_ir_title.py` 9/9): site A `0x280ac164` (8 B → `ldr.w pc,[pc]` + caveA) and site B `0x280ad37c` (`b.w` relay `0x28135078`, the dead tail of the old budget check → caveB); caves (84 B) in the seg0 cave after the tables. Amp-category (12) blocks with preset id 380 take the IR Single name branch `0x280ac8ee` (r4 = 0) and redraw on knob 0 (`0x280ad38e`); Amp+Cab (11) keeps the stock title; the IR path's `[+0x9c]` test is skipped for NAM. The third IR test `0x280ac546` is left stock (its effect unknown).
- **NAM as an effect: not feasible in the 13-block layout.** Floor FX harnesses: `0x600007` member 5 placeholder DM 0x38b / PM 0x14e (mono), `0x600006` member 5 DM 0x3a2 / PM 0x1e0 (stereo); NAM's instance needs DM 0x58a. Its rings could only be static, ~1,600 words more than the spare: two more normal slots per DSP (11 blocks). It would add no capacity (still 2 kernel slots per DSP), only a Distortion-category entry for pedal captures; NAM in Amp already plays pedal captures.
- **Personal setup page** `setup/index.html` (local file; `setup/nam2ir-core.js` is upstream's converter, unchanged, GPL-3.0): converter (checked: a test A2 Lite capture converts byte-identical to `tools/nam2ir.py`; a non-A2-Lite file is refused with the reason), IR slot list, first-test checklist with notes, troubleshooting, recovery. Saved in the browser's local storage only. Open it by double-clicking the file.
- **`FIRST_TEST.md`**: the same checklist as a document.
- Build now: `build/Helix_Floor_v3.80.0_NAM_PERSONAL.hxf` MD5 `9dc10bc83c03bdba74ea9746a13b7739`; Entry 0 +55,620 B (seg0 cave 3,660 B left); all checks pass (l6ia ALL OK, KernelCheck, guard tests 19/19, title tests 9/9, slot sizes).

## Review 2026-11-01 (`review/REVIEW_2026-11-01.md`) and fixes

Independent review verdict: **fix first**. Verified and fixed:
1. **Entry 2 over its partition (confirmed by me).** The app's partition table (`0x28116124`.., indexed through `0x2811619c`): E0/E1 0x4001 sectors, **E2 0x400 (512 KiB)**, E3 0x80, E4 0x800, E5 0x7bf8; `0x281135f0` checks each header length against it at boot (`cmp.w r3, r2, lsl #9` at `0x28113644`), over = boot failure. My "next partition's start" estimate was wrong. Fix: the read-only tables (tone stack, STOMP_GAIN, RPTAB, CLR, DRIVE_TAB, FADE_TAB: 2,284 words) now follow Blob 0 in its buffer (Entry 5; at `0x297fde..0x2988ca`, Blob 0 0x7b2d8 → 0x7bbc4 words, relocation check OK), and zero runs ≥ 8 words are ZERO_LDATA (tag 1) blocks (stock uses 90). **Entry 2 now 0x7ecf0 of 0x80000 (4,880 B spare).** `build_floor.slots()` and `stage_kernel.E2_MAX` use the real table.
2. **Kernel trusts I8 (instance PM) unchecked.** Fix: `m_init` first checks I0..I0+0x58a within heap a's new range and I8..I8+0x1be within heap b's; if not, it returns with S_INIT 0 and the caller plays silence (`check_bounds`: out-of-range instance silent and uninitialised, in-range plays; KernelCheck still PASS).
3. **No gap between the shrunk heaps and our data/code.** Fix: 16 free words after each new heap end (`GUARD`); hot code now at PM `0xe4058`; globals no longer packed into R2.
4. **Zero-budget slots still hold the FX harness `0x600006`** (needs DM 0x3ae / PM 0x1e6): the DSP may refuse them (harmless), fail the path graph, or lay the harness out unchecked into our regions. The reviewer's stand-in `0x60005e` is not a pass-through (it sums and mixes), so not applied. Instead: **staged test images** (`floor/build_staged.py`): `build/test1_seg0_only.hxf` (seg0 +55,620 B of zeros, nothing else; MD5 `2a7f3445c7fd93fa0d015a1bc50a648a`) and `build/test2_slots_only.hxf` (stage_slots only; MD5 `914b5dd6a4f535ce39dad9e1883fe924`), both checksums ALL OK and within partitions. Order in `FIRST_TEST.md`: stock rehearsal → test1 → test2 → full.
5. Still open from the review: bootloader with the bigger seg0 (test1 answers it); moves/preset load can put a third amp-type block on a DSP (silent block); Heap 6's margin above the DSP's last boot block.

Full build now: `build/Helix_Floor_v3.80.0_NAM_PERSONAL.hxf` MD5 `a1df32be9110b6e240e19bc3f384f2bc`; all checks pass.

## Gaps closed (2026-11-01)

- **Moves / pastes / editor inserts:** HOOK's move path (lr `0x2811de75`) now reads the incoming block's descriptor from `0x2811de44`'s saved registers by its caller: `0x28125a2c` (saved r8, frame +24; called from the message handler `0x2813ed06`, so HX Edit inserts too) and `0x28125c80` (saved r6, frame +16; from `0x281214b6`). Rules onto an empty position: refuse at 13 blocks, refuse a big-slot type when the DSP already has 2. A descriptor inside the target DSP struct (`dsp..dsp+0xb424`) counts as a move within it (no count change); both callers actually pass copies, which is consistent with the stock budget check (it would double-count a block moved within a DSP unless the source is removed first). Onto an occupied position counts are taken as unchanged (the replaced block's type isn't at hand). Guard tests 29/29.
- **Preset load:** no check on the unit (unchanged). Instead `floor/check_presets.py` and the setup page's "Check presets" section flag any .hlx over 13 blocks or 2 amp-type blocks (@type 1, 3, and @type 4 with a legacy `HD2_Cab…` model) per path. **All 40 presets on the PC fit** (Music\Line 6 Helix Presets, Downloads incl. commercial).
- Build: `build/Helix_Floor_v3.80.0_NAM_PERSONAL.hxf` MD5 `204844c4b5700474e4d10d164f9e607a`; `test1_seg0_only.hxf` MD5 `70bd453d7b532b07fa8fcb2517207f6d` (seg0 grown by the new +55,704 B); `test2_slots_only.hxf` unchanged. All checks pass.

## Hardware log

- **2026-11-01: recovery rehearsal PASSED.** Floor (stock 3.80) reinstalled with stock `Helix_Floor_v3.80.0_0x7d01f5efb.hxf` via Line 6 Updater (Offline Mode, local file); presets kept, version 3.80. During/around the update Windows saw the Floor as Line 6 `USB\VID_0E41&PID_4248` (Helix Floor, audio+MIDI), not LPC DFU `1FC9:000C`.
- **2026-11-01: update-mode USB check.** In update mode (FS 6+12 at power-on) the Floor enumerates as Line 6 `USB\VID_0E41&PID_4248` (serial `_________1`, vs `<serial>` in normal use) with its audio/MIDI interfaces; **no LPC boot-ROM DFU (`1FC9:000C`)**. Consistent with the app-run update mode ("Entered Update Mode!" lives in Entry 0/1). So upstream's run-from-RAM path is not reachable on the Floor without hardware boot pins; testing goes by the staged installs.

## Can the Floor reach the boot-ROM DFU? (2026-11-01)

- **Stomp:** `0x28d99260` copies "BootIntoDfu!" (13 B) to **`0x1001ff00`** (top of local SRAM bank 0) and resets (`0x100000f0`: RGU `0x40053100` = 1). Its bootloader sees the magic and starts the LPC boot ROM's USB DFU (`1fc9:000c`).
- **Floor:** no reference to `0x1001ff00`. Reset `0x28114d88(r0)`: if r0 ≠ 0, `0x28110b60(r0)` first writes r0 as a 4-byte **persistent flag on the eMMC** (a record via `0x281125ec`/`0x28112498`), then RGU reset. The command handler `0x280f3480` (message +0x10 = the value; the Updater's "reboot into mode" request) calls it. At boot the app reads the flag, shows "Entered Update Mode!" and clears it (`0x28115ab4` writes 0). So the Floor's update mode is entirely app-level; nothing in the app asks the bootloader for DFU.
- **Untested possibility:** the Floor's bootloader (not in the .hxf) may share the Stomp's check of `0x1001ff00`. A one-time tiny app patch could write "BootIntoDfu!" there in `0x28114d88` before the reset (keeping the flag write), so an Updater-requested reboot would show `1fc9:000c` if the bootloader honours it, or plain update mode if not. Our seg0 cave ends at `0x1001f208`, below `0x1001ff00`.
- A Floor RAM run would then still need: the ramboot loader with the Floor's SDRAM timing (in its bootloader, unknown; a wrong guess only hangs until power-off), the overlay layout (Floor uses `0x2971b000..0x29900000`), hooks at read `0x1000504c` / write `0x10005194`, and a WinUSB-type driver for `1fc9:000c` on Windows.

## DFU probe build (2026-11-01, `floor/build_probe.py`, `floor/test_probe.py`)

`build/test0_dfu_probe.hxf` (MD5 `5a9a60447092f2b1d3a80dcd0be4036b`): stock 3.80.0 except Entry 0 (Entry 1 stock). seg0 `0x11870 → 0x118ac` (+60 B: probe code + note at `0x10011870`). Site `0x28114d9c` (update-mode branch of the reset routine; stock `bl 0x28110b60; b 0x28114d8c; nop`) → `ldr.w pc,[pc]; .word 0x10011871`. The probe copies "BootIntoDfu!\0" (16 B) to `0x1001ff00`, sets lr = `0x28114d8d` and jumps to `0x28110b60` with r0 (the flag) unchanged, so the flag is saved and the unit waits and resets exactly as stock. Plain restarts untouched. Emulator test PASS (note written, flag kept, continues to 0x28110b60 returning to 0x28114d8c, stack untouched); checksums ALL OK; partitions fit.

Test: install it like stock; check normal use; then in Line 6 Updater (Floor running normally) start an install of the stock file, which asks the Floor to restart into update mode. `1fc9:000c` in Device Manager = the bootloader honours the note (RAM path open); normal update mode = it doesn't (the Updater then reinstalls stock and the probe is gone). If the Updater doesn't send the restart request, the result is inconclusive.
- **2026-11-01: test0_dfu_probe.hxf INSTALLED.** Updater reported success; the Floor starts and plays normally, version 3.80. First modified firmware on the unit: the bootloader accepted Entry 0 differing from Entry 1 and seg0 +60 B (which copy runs is not yet known).
- **2026-11-01: probe v1 inconclusive.** Line 6 Updater (Offline, local stock file) installed while the Floor ran normally (USB serial stayed `<serial>`) and restarted once at the end; it never sent the update-mode restart request, so the v1 probe (update-mode branch only) never ran. Floor back to stock, presets intact.
- **Probe v2** (`build/test0_dfu_probe.hxf`, MD5 `ba8dd56c8a7f8c965e5e95c3979959e6`): site moved to the reset tail `0x28114d8c` (stock `054841f0affe054b`; only internal branches reach it), so every software restart writes the note, then waits 2 s and resets as stock. seg0 +72 B. Emulator test PASS. Trigger: install it, then install stock over it; the Updater's final restart carries the note.
- **2026-11-01: probe v2 result = NO.** Probe v2 installed (Floor ran normally, 3.80, USB serial `<serial>`). Then Line 6 Updater (Offline, local stock 3.80 file) installed while the Floor ran normally; final restart came back to normal use (screen, 3.80, presets play) and USB showed only `VID_0E41&PID_4248` serial `<serial>`, no `1FC9:000C`. So the Floor's bootloader ignores "BootIntoDfu!" at `0x1001ff00` (assuming that restart went through the patched reset tail, the only software reset path). Run-from-RAM is closed on the Floor without hardware boot pins. Floor is stock 3.80 again, probe gone. Next: staged installs (`test1_seg0_only.hxf` → `test2_slots_only.hxf` → full), never right before the unit is needed.
- **2026-11-01: test1_seg0_only.hxf PASSED.** Installed via update mode + Updater (Offline, local file); Floor starts, 3.80, presets play normally. Start-up accepts seg0 +55,704 B. Caveat: test1 is padding only, so it can't show whether Entry 0 or the stock Entry 1 is the copy that runs; the full build's NAM folder will.
- **2026-11-01: test2_slots_only.hxf INSTALLED, result pending.** Updater said "Firmware Update Completed Successfully" (~17:57); the Floor dropped off USB at the restart and was still absent at 18:53 (earlier installs came back within about a minute). Possibly a long preset rebuild, possibly a start-up hang from the slot/heap change. the owner checking the screen in person; recovery = FS 6+12 + stock file (Entry 0/1 stock in test2).
- **2026-11-01: test2_slots_only.hxf FAILED.** Floor screen: "Boot Failure - Entered Update Mode!" (`0x28115f8e`); no USB until power-cycled into FS 6+12 update mode (then `_________1` as usual). Recovered with the stock file. The boot sequence around `0x28115d80..0x28115f2e` is a chain of init steps, each failing to `0x28109ce8` (log, line no.) + `0x281141ac`; which step failed is not visible from the PC. Leading suspect = review item 4: the 3 zero-budget 0x600006 slots per path graph (Entry 5) still need harness memory, so path-graph setup fails; second suspect = heap a/b shrink in Entry 2 vs what the DSP needs at boot. Next split: **test2a = Entry 5 change only** (zero budgets, heaps stock: stock heaps are big enough, so only the zero-budget slots are new). Boots → heap shrink is the fault; fails → zero-budget slots are rejected (then try removing the 3 members from the graphs instead).
- **test2a built** (`floor/build_test2a.py` → `build/test2a_slots_e5_only.hxf`, MD5 `8bd9f2e921a5784b46fee01cfa8896fd`): Entry 5 zero-budget slots only (graph 0x600000 members 177/178/181, 0x600001 members 14/15/18), every other entry byte-identical to stock, checksums ALL OK. Install path: Updater can install while the Floor runs normally (proven by the probe v2 stock reinstall); FS 6+12 only needed when it won't start.
- **2026-11-01: test2a FAILED** ("Boot Failure - Entered Update Mode!"). So the zero-budget slots in Entry 5 alone are rejected at boot (heap shrink not needed to fail). Likely the boot-time graph check wants every 0x600006 slot member to have at least the harness's budget (DM 0x3ae / PM 0x1e6 = the stock NORMAL size), so slots can't be "switched off" by zeroing. Next routes: (a) delete the 3 slot members from each path graph's member list (fix the counts/indices that refer to them), or (b) find the boot check in Entry 0/DSP and what it compares. Recovering with FS 6+12 + stock.
- **test2b built** (`floor/build_test2b.py` → `build/test2b_bigslot_normal.hxf`, MD5 `12a1644059ae15a0696799ef8a3256c8`): Entry 5 only; last big slot per path graph (0x600000 m181, 0x600001 m18) gets the normal slot's size words 13..19 (`75c 30c 63000 8 d4 8 0` → `3ae 1e6 63000 8 71 8 0`). Note: slot records carry a 4th size, word 17 (normal 0x71, big 0xd4), that stage_slots never touched (test2/2a zeroed 13..15 only, leaving 17 non-zero: an inconsistent record may itself be what failed). Question test2b answers: is any legal-size edit of the slot list accepted?
- **2026-11-01: test2b PASSED boot.** Installed while running normally; preset rebuild, then normal screen, presets look and sound normal. So the Floor accepts edited slot sizes in Entry 5 when the record is a legal (normal) one; test2/2a failed on the zero/half-zeroed records. Pending: proof the edit is live (2 amps + Cab Dual on one DSP should now be refused, stock allows it).
- **2026-11-01: test2b live check.** Path 1 with 2 amps + Cab Dual: the UI allows it (expected: Entry 0 untouched) and the Cab Dual PLAYS. Entry 5 is definitely read (test2a failed on it alone), so either per-slot sizes aren't enforced at bind time (blocks take what they need from the heap) or the Cab Dual overran its slot unnoticed. Unresolved; needs the SHARC bind code.
- **test2c built** (`floor/build_test2c.py` → `build/test2c_bigslot_heaps.hxf`, MD5 `8979a7cf2035ed5118c69592e1faa2b3`): test2b's Entry 5 + Entry 2 heaps a 0x4ebb→0x4b0d (end 0x9ba5f→0x9b6b1), b 0x22e4→0x21be (end 0xe674a→0xe6624) = the larger graph sums, as stock sizes them. Frees DM 0x9b6b1..0x9ba5f (942 w) + PM 0xe6624..0xe674a (294 w) per DSP, unused in this test. Other entries stock; checksums ALL OK.
- **2026-11-01: test2c PASSED.** Boots (after preset rebuild), presets play normally. The DSP accepts heaps a/b shrunk to the new budget sums. **First memory freed on hardware:** DM 0x9b6b1..0x9ba5f (942 w, Block 0) + PM 0xe6624..0xe674a (294 w, Block 3) per DSP, plus the 3,431 w already free in Block 3 = option A's static pool (4,667 w). Option A needs NAM's weights streamed from SDRAM (static need 5,692 with weights on chip vs 4,667): next = re-lay nam_floor.py for these regions with streamed weights, measure speed in the simulator. Floor currently runs test2c (2 amps + Cab Dual on one DSP not safe on it).

## Option A sizing on the test2c memory (2026-11-01, `scope/pieces_1slot.py`)

Freed per DSP by test2c (hardware-proven): R3' Block 0 DM `0x9b6b1..0x9ba5f` 942 w, R2' Block 3 PM `0xe6624..0xe674a` 294 w, plus R1 Block 3 `0xe729a..0xe8000` 3,430 w = 4,666 (4,634 after 16-word guards). Per instance (amp placeholder) DM 1,285 / PM 493 free, near rings take 1,272 / 432 (as in nam_floor.py).

Kernel, **one slot per DSP** (2 slots can't fit; 2 streams alone = 4,030): hot code 1,635 (needs one PM run: only R1 holds it), cold 294, globals 2,498 (−228 for RPTAB/CLR/DRIVE_TAB/FADE_TAB already moved to DDR2 = 2,270), X/IN/WBUF 220, flags 32, stream 2,015 (72 state + 1,871 weights + 72 silence state), heads 102 = **6,568 static vs 4,634: 1,934 short.** Streaming the 1,871 weight words from SDRAM leaves 63 short **plus the weight staging buffers** (double-buffered per layer; size not yet measured, likely a few hundred). So option A as tested (one big slot → normal) is still a few hundred words short.

Ways to close it: (1) also turn a 2nd big slot per DSP to normal (+1,236 w; one more legal edit like test2c) → 5,870, fits with weights streamed and room to spare, but **max 1 amp-type block per DSP** (the NAM block or one stock amp); (2) trim globals (SB 576 / OUTBUF 576 / TABLE 391 sized for the 2-slot design; unread); (3) delete slot members outright (untested on hardware). Either way: **1 NAM per DSP** (2 per Floor, one per path), so a stereo pair of NAMs on one DSP is out.

## Why the Stomp has room and the Floor doesn't (2026-11-01, `dsp/spans.py`, `dsp/diff_spans.py`)

Boot-stream spans paired Floor ↔ Stomp. Heaps a/b/c are the same size on both (so block spaces are NOT the difference). The ~13K extra fast words the Floor uses are its **bigger DSP program**:
- Block 2 code (INIT_L16, VISA) `0xc1284`: Floor 4,254 vs Stomp 1,241 words (+3,013).
- Block 2 .bss section `0xc487a`: Floor 7,274 vs Stomp `0xc3c8f` 1,065 (+6,209); 87 refs at 30 offsets (variables, not one buffer).
- Block 3 .bss `0xe0a00`: Floor 6,227 vs Stomp 3,223 (+3,004); 296 refs / 109 offsets.
- Block 3 .bss `0xe2454`: Floor 5,328 vs Stomp's matching section in Block 2 `0xc5bd4` 4,549 (+779); the Floor spilled this group from Block 2 to Block 3.
Sum ≈ 13.0K. These are many live variables of a larger program (Floor I/O, two-DSP link, etc.), not a spare buffer; moving them means rewriting hundreds of references. Not a practical source.

Implication for 2 NAM per DSP: each NAM block needs an amp (big) slot, so 2 NAM per DSP needs 2 big slots, i.e. at most test2c's change (4,634 static). 2 slots with weights streamed ≈ 5,350 + staging: ~700+ short. Remaining lever: **are the heaps a shared pool** (blocks take their real need, budgets only size the heaps)? test2b hints yes (Cab Dual PM 0x21e played with no slot ≥ 0x21e PM). If so, heaps a/b can shrink below the summed budgets with every block space kept, at the cost of only worst-case presets.
- **test2d built** (`floor/build_test2d.py` → `build/test2d_heaps_only.hxf`, MD5 `f07c5541f722c2646f7b618d7eca799a`): Entry 5 stock, heaps a 0x4ebb→0x475f, b 0x22e4→0x1fd8 (one big slot's DM/PM below the budget sums). Frees DM 0x9b303..0x9ba5f (1,884) + PM 0xe643e..0xe674a (780). Boots + plays → pool; boot failure → the DSP requires heap ≥ budgets.
- **2026-11-01: test2d FAILED** ("Boot Failure - Entered Update Mode!"). Heaps a/b below the summed slot budgets are rejected at boot: the DSP requires heap ≥ budgets. So budgets are hard reservations; NAM's static memory can only come from shrinking slot budgets (legal sizes) + heaps to match (test2c pattern). With 2 big slots needed for 2 NAM blocks per DSP, the pool is test2c's 4,634 vs ~5,350 + staging for 2 slots with streamed weights: 2 NAM per DSP not reachable without further cuts (e.g. a normal slot shrunk to a smaller legal size: minimum unknown, would bar the heaviest effects from that slot). **Realistic target: 1 NAM per DSP (2 per Floor).** Recovering to stock.

## Two NAM per DSP: sizing with shared buffers (2026-11-01)

- **test2e built** (`floor/build_test2e.py` → `build/test2e_normal_half.hxf`, MD5 `ab1dfc6fac7c1e771ed0fed218125fe7`): test2c + the last normal slot per path graph (0x600000 m178, 0x600001 m15) at half DM/PM (0x1d7/0xf3, other size words kept), heaps a 0x4936 / b 0x20cb = new sums. Frees DM 0x9b4da..0x9ba5f (1,413) + PM 0xe6531..0xe674a (537) per DSP; with R1 = 5,380 (5,348 after guards). Asks whether a sub-normal slot is legal. Cost: effects over DM 0x1d7 / PM 0xf3 can't bind in that one slot (ARM slot choice for such a block unknown: possible silent block).
- **Kernel globals are per call, not per slot** (`nam_multi.Layout`): SB 2×SB_WORDS (C·96 each), OUTBUF 48·F, RCH0/1, WCH, LCH, JOBS, TABLE 17·NL, FARTAB, WADDR, CLR all serve whichever slot runs; F = 12 far layers at far_d 17. A second slot adds only its state (144) + heads (102). WBUF (156) already receives a near layer's weights each call (copy), a natural landing spot for streamed weights.
- **2 slots, weights streamed from one SDRAM copy:** 6,568 (1 slot, weights on chip) − 1,871 + 246 = **4,943 + weight staging** vs **5,348** (test2e): fits if far-layer weight staging ≤ ~400 words (largest far layer's weights, double-buffered; to measure). Tight but plausible. On test2c alone (4,634) it doesn't fit.

## Lessons from scottlynn73/hx-effects-nam-lite (HX Effects 3.80.0 port, read 2026-11-02)

- Hosts NAM as the **IR > Single 1024 block** (takes over its name, preset id and browser entry; the IR graph's convolution member becomes the NAM primitive, other members parked). Reason given: **the HX Effects app's boot self-test rejects unknown models**, so it reuses an existing model identity instead of adding one. → **Risk for our full build:** `stage_model.py` adds a new model (count 863, like upstream on the Stomp). If the Floor app has the same self-test, the full build would "Boot Failure" with nothing wrong in the kernel. Check Entry 0 for a model-table self-test before the full build, or plan a repurposed-identity fallback.
- Per-block working memory: fixed DDR2 region `0x294400 + 0x5000·slot`, made room for by moving Heap 6 (same idea as ours). Captures in the User IR store (128 slots shared with cab IRs), ~8 KB .wav, 1,871 weights.
- Cost: simulated 34,000 / 150,000 cycles per audio block (~23%); declared DSP_COST 2700, suggested floor 2300. README: "two NAM blocks and a few effects fit in one preset". No stereo, no per-DSP limit stated. HX Edit can't edit the block (error −8200), as expected for ours.
- Idea to check for the Floor: hosting NAM in the IR category (normal slot) instead of the Amp category (big slot) would free NAM from the big-slot/2-amp rules, so both remaining big slots could shrink (more static memory). Blocker to check: a normal slot's per-instance budget (DM 0x3ae / PM 0x1e6) is below what the near rings take today (DM 1,272 / PM 432), so rings would move to static memory.
- **2026-11-02: test2e FAILED** ("Boot Failure"). A slot below the normal size (DM 0x1d7 / PM 0xf3) is rejected at boot, like the zero-size ones. Evidence so far: legal = exactly the stock normal or big record; anything smaller fails. Probable rule: every 0x600006 slot must cover the slot harness's own need (DM 0x3ae / PM 0x1e6 = the normal size). So test2c (one big → normal per DSP, 4,634 static) is the most memory the slot route gives while keeping 2 big slots. 2 NAM per DSP (≈4,943 + weight staging) is ~300+ short there; remaining levers: kernel trimming (hot code / globals), IR-category hosting (frees the big-slot need but rings must go static), or cross-DSP stereo (fits today).

## Engine trim pass: 2 NAM per DSP on test2c memory (2026-11-02, paper only)

Budget per DSP (test2c, after 16-word guards): R3' Block 0 926 + R1 Block 3 3,430 + R2' Block 3 PM 278 = **4,634**. Per-instance placeholder spare after near rings: DM 13 / PM 61.

Need, 2 slots, weights streamed from one SDRAM copy: hot 1,635 (one run, must sit in R1) + cold 294 + globals 2,239 (SAVE 64, SLOTTAB 2, HS 48, SB 576, OUTBUF 576, RCH0/1 192, WCH0-2 234, LCH 12, JOBS 120, TABLE 391, FARTAB 12, WADDR 12; CLR/DRIVE/FADE already in DDR2) + X/IN/WBUF 220 + flags 32 + per slot (state 72 + silence 72 + heads 102) × 2 = **4,912 + weight staging**.

Trim candidates:
- Silence states to SDRAM with the weights (read only when a slot (re)starts): −144.
- Weight staging reuses WBUF (near layers already get their weights copied there each call); far layers need a second buffer of the largest layer's weights: est. +156.
- Cold code (294, runs only at init / model load) as an overlay DMA'd into SB, idle at those times: −294. Moderate work; needs a check that no far-ring DMA is in flight during a load.
- TABLE (391) to DDR2: read 23×17 words a call through the external port, est. ~10% more DSP per block. Last resort.
→ 4,912 + 156 − 144 − 294 = **4,630 vs 4,634: zero margin**, before fragmentation (R2' only takes PM-side data; hot code pins R1). With TABLE in DDR2: ~390 spare at a DSP cost. Not robust; an implementation might land a few dozen words either side.
- **2026-11-02: design written, `DESIGN_2NAM.md`.** Weights stream per layer by a new DMA job type in the existing queue, with each layer's TABLE row riding in the same fetch (TABLE moves to DDR2 at no core-read cost); two on-chip layer buffers (17 + 156 each) replace WBUF; silence states stay in SDRAM; weights live in each instance's SDRAM block (raise 0x5000 → 0x5800). Estimated static ≈ 4,100 of 4,634 (~500 spare) before the optional cold-code overlay. Implementation next (`floor/nam_floor2.py`).
- **2026-11-02: `floor/nam_floor2.py` phase 1 (weights streamed per layer) — KernelCheck PASS, all 14 steps bit-exact** (run with MAX_STEADY relaxed; scratch script). Stream in instance SDRAM at W_OFF (SDRAM need 21,767 words → harness 0x5800), header 53 + silence 72 kept per slot, 23 fetch jobs (type 2) in the queue ordered by start threshold (EVENTS now +1 per layer computed), LB0/LB1 (156 each), WBUF = LB1 for the head. Two open problems:
  - **Speed:** steady mean 33,197 / worst 40,727 instructions per block (floor 1-stream kernel: 24,991 / 31,797; check limit 33,000). Cause: one EP DMA channel now carries ~4,100 cycles more per call (sim model: 40 cycles a TCB + 2.1 a word) on top of the far taps (~14K), and a fetch can only start once its buffer is free and the queue in front of it is done, so layers poll. ≈27% of a 150K-cycle block per NAM (vs ~17–21%).
  - **Memory:** 976 words over test2c (spill in sim-only RX). Planned trims: per-layer write-back with 2 OUTBUFs (−~594, but more DMA jobs: slower), TABLE to DDR2 with rows riding the weight fetch (−~399), silence to SDRAM (−144).
- **2026-11-02: `floor/nam_floor3.py` — weights on EP DMA channel 1: KernelCheck PASS (all 14 steps bit-exact, normal limit): steady mean 25,111 / worst 32,106** (1-stream Floor kernel 24,991 / 31,797). Channel 0 keeps upstream's tap/write-back queue; each layer waits for its own weights then starts the next fetch on channel 1. Channel 1 regs assumed DMAC1 0x180C, EIEP1..CPEP1 0x1828..0x182E (pattern of ch0; confirm in HRM; stock Entry 2 has no 32-bit refs to either channel's registers). Memory: 906 over test2c before trims.
- **2026-11-02: nam_floor3 trims, KernelCheck PASS (bit-exact, mean 25,176 / worst 32,109):** write-back buffer shared by group (OUTBUF 576 → 192, one WCH chain, W before the next group's first taps), silence states in SDRAM (fcopy / load clear read them via G_SDR), TABLE row 21 words (T_WT slot reused), head's 49 weights fetched on channel 1 into WBUF=LB1 during layer 22 (slot keeps rechannel + scale). **Over test2c: 92 words.** Next: TABLE rides with each fetch (row + weights into the LB; on-chip far-only table for pump), est. −300 → ~200 spare.
- **test3 built** (`build/test3_model_only.hxf`, MD5 `ab06eb9fe59d7d1442bd0466e0716c2e`): stock + `stage_model.py` only (NAM A2 Lite = model 863 on blob 863 in browser groups 48/49/51; host composite 0x6001c9 with member primitive 0x128; Blob 0 buffer 0x7a612→0x92946 and Heap 6 moved to 0x30dac0). No kernel. Answers the HX-Effects worry: does the Floor app boot with an unknown model (and the bigger Blob 0 / moved Heap 6)? Do NOT add the NAM block on this image (primitive 0x128's stock handlers, not NAM).
- **2026-11-02: `floor/nam_floor4.py` — 2 NAM per DSP FITS test2c memory: 0 over, 205 words spare (R2 202, R3 1, R1 2); KernelCheck PASS, all 14 steps bit-exact, steady mean 25,390 / worst 32,366** (limit 33,000; 1-stream Floor kernel 24,991 / 31,797). Last trim: layer rows live in DDR2 (`TROWS`, + a blank row for the head fetch) and ride channel 1 with the weights (each layer buffer = flag, 22-word row, 156 weights; the row's last 4 words name the next fetch); pump reads a 12-field on-chip far table (FTAB, 144 words); `ROWM1` (4 words) starts layer 0's fetch. Still to do for hardware: confirm channel 1 register addresses; build the full image on test2c (Entry 2 kernel in R1/R3'/R2', instance SDRAM 0x5800, ARM rules for the 16-slot / 2-big layout); test3 (new model) install result.
- **2026-11-02: EP DMA channel 1 registers confirmed from the HRM** (`docs/ADSP-214xx_hwr_rev1.1.pdf`, register table): DMAC1 0x180C, **EIEP1 0x1830, EMEP1 0x1831, ECEP1 0x1832, IIEP1 0x1833, IMEP1 0x1834, ICEP1 0x1835, CPEP1 0x1836** (ch0 has EBEP0 0x1827, TPEP0 0x1828, ELEP0 0x1829 after CPEP0: the 0x1828.. guess would have hit channel 0). Channel 1's interrupt is P13I (EPDMA1); nam_floor4 now also requires DMAC1 idle and LIRPTL P13IMSK (0x20000, by the P6..P15 mask layout that gives upstream's P9IMSK 0x2000) clear before a call, else the block is skipped like a busy channel 0. Re-check PASS (mean 25,398 / worst 32,374). The two channels arbitrate (rotating by default); no other setup needed.
- **2026-11-02: FULL 2-NAM BUILD** `floor/build_floor2.py` → `build/Helix_Floor_v3.80.0_NAM2_PERSONAL.hxf` (MD5 `56276ca750069260c779df92d032de69`; CHANGES_NAM2.txt). Stages: stage_slots2 (test2c layout), stage_model / stage_kernel with `NAM_KERNEL=nam_floor4` (instance DM 0x58a / PM 0x1be / SDRAM 0x5800; KernelCheck PASS mean 25,398; kernel 1,391 instr + 1,227 data words; 2,812 table words after Blob 0 incl. TROWS), stage_main with `NAM_MAX_BLOCKS=16` (no block cap, max 2 big-slot blocks per DSP: 2 amps, or 1 amp + Cab Dual). l6ia_verify ALL OK; every partition fits (Entry 2: 5,960 B spare); guard tests 29/29, IR-title tests pass. NOT installed. Depends on test3 (new model at boot).
- **2026-11-02: test3 (new model only) BOOTED**: install ~21:01, restart 21:20, preset rebuild on screen, back in normal mode (USB `<serial>`) 21:26. So the Floor app accepts an added model (863, "NAM A2 Lite") plus the enlarged Blob 0 buffer and moved Heap 6 at boot (no HX-Effects-style unknown-model rejection). Pending the owner's screen check: NAM A2 Lite listed under Amp, presets play.
- test3 follow-up: NAM A2 Lite not in the browser menu (expected: test3 has no stage_main / Entry 0 lists). A fuzz heard on one humbucker guitar only (not P90s, not other guitars): guitar-side, not firmware.
- **2026-11-02: NAM2 full build INSTALLED and BOOTED** (`Helix_Floor_v3.80.0_NAM2_PERSONAL.hxf`): update mode 21:44 (serial `_________1`), install to 22:03, back in normal mode 22:03:46 (22 s, no long rebuild this time). First boot of the NAM kernel image on hardware. Pending: Amp > NAM folder, NAM sound, 2 NAM per path, DSP load.
- **2026-11-02: first NAM test on hardware: boots, presets fine, Amp > NAM > NAM A2 Lite listed, but NAM is SILENT** (1 and 2 blocks; IR slot with an imported Tone3000 A2 Lite capture). Silence = one of the kernel's silent paths (busy channel / unmasked P9I or P13I, backoff, no model, DMA fail, bounds guard) or the kernel not called. **Diagnostic image built:** `floor/nam_floor4d.py` (beep codes instead of silence, list in its docstring), `build_floor2.py --diag` → `build/Helix_Floor_v3.80.0_NAM2_DIAG.hxf` (MD5 `1507981942d5700eb70676d2353ea4bf`). Code 5 (empty slot) verified in the simulator.
- **2026-11-02: diag result = 4 beeps (backoff).** Every retry fails, so the block sits in BACKOFF (1,500 calls ≈ 0.5 s) almost all the time and the failing call itself (one call) is inaudible. Next: diag v2 that beeps the CAUSE during backoff (sticky DCAUSE stored at m_fail) and separates channel 0 vs channel 1 timeouts.
- **2026-11-02: hang fix + diag v2.** Simulating a channel 1 stall HUNG the kernel (pc in the tap loop): with the row riding the fetch, a failed fetch leaves the layer's loop counts / pointers unloaded (stale or garbage). Fix in nam_floor4: after CALL lwait the loop skips the rest of the layers when DMA_FAIL is set (`n_lskip`), and lwait returns at once once DMA_FAIL is set; a stall now returns in ~10K cycles, silent (m_fail). Diag v2 (`nam_floor4d`): codes renumbered (4 = model load DMA fail, 6 = channel 0 timeout, 7 = channel 1 timeout, 10 = no code) and the backoff beeps the failure that started it (DCAUSE, b3+15, zeroed at boot). Image `build/Helix_Floor_v3.80.0_NAM2_DIAG.hxf` MD5 `b0232e6dadf9b3e3a72e8852769175ab`. Production nam_floor4 re-check running.
- nam_floor4 with the skip-on-failure fix: KernelCheck PASS (mean 25,477 / worst 32,512; the DMA-timeout call now 13,454 instead of 34,497 since the layers are skipped). Production image not rebuilt yet (wait for the diag result).
- **2026-11-02: diag v2 = 3 beeps: channel 1's interrupt (LIRPTL P13IMSK, bit 17 by the P6..P15 layout that gives upstream's P9IMSK 0x2000) is UNMASKED on the Floor** (ch1 itself idle at our calls, ch0 check passes). The stock DSP program enables the EPDMA1 interrupt: it may use channel 1.
- Stock DSP code has no 32-bit references to either EP DMA channel's registers (both units; 16-bit halfword hits are noise-level and identical Floor/Stomp), so how/whether Line 6 drives channel 1 is not visible from immediates. IVT index 0x17 = EPDM1I (P13I), 0xF = EPDM0I (P9I). Options for the weight stream: (A) mask P13I (and clear its latch, LIRPTL bit 7) while the kernel uses channel 1, restore on exit (safe only if the stock code never starts a channel 1 transfer while the NAM block runs); (B) weights back on channel 0's queue (nam_floor2-style: proven-free channel, ~+30% DSP in sim); (C) find the P13I handler / LIRPTL write in the stock code to learn what channel 1 is for. Decision pending (the owner away).
- **2026-11-03: what channel 1 is for (research C).** Interrupt vector table = the boot stream's FINAL_INIT payload (256 instructions, 4 per vector). Unused vectors hold the stub `000000000000 073e073e0000 …`. **Floor vector 0x17 (EPDM1I / P13I) holds a real handler entry** (the same template as DAI 0x15 and DPI 0x19: `…eb42 1720063e0408 000e4158796e 11020f020017`, a dispatch to handler 0x…796e), **while the Stomp's vector 0x17 is the empty stub.** So the Floor's stock DSP program really drives EP DMA channel 1 with interrupts (a Floor-only feature: plausibly its DSP-to-DSP or SDRAM traffic); the Stomp doesn't, which is why upstream never needed ch1. Borrowing ch1 (option A) would race Line 6's own transfers and could fire their handler on our completions: rejected. Channel 0's vector 0x0F has an entry on both units, but P9I is masked on both (upstream's check passes on the Floor too). **Decision basis: weights must share channel 0 (option B).**
- **2026-11-03: `floor/nam_floor5.py` — weights back on channel 0** (nam_floor4's layout: rows + weights per layer, but fetched by job type 2 in channel 0's queue; `queue5` orders F/R/W by start threshold, group write-back forced before the next group's first taps; buffer flags cleared at call start and after use; head fetch waited with pump after the loop; LB_N 153; FARTAB dropped, p_w steps FTAB rows). Fits test2c (12 spare). **KernelCheck bit-exact PASS (with MAX_STEADY raised): steady mean 34,894** (ch1 design 25,477; 2-instance bench 41.7K vs 28.9K): the queue only advances at pump calls (layer starts, waits), so the channel idles mid-layer and layers wait. Full image rebuilt: `build/Helix_Floor_v3.80.0_NAM2_PERSONAL.hxf` MD5 `2b03600cbf8d9573f7e9e790b315baf6` (build_floor2 sets NAM_MAX_STEADY=60000; bit-exactness still checked). Diag variant (nam_floor5d) is 90 words over: not built. Speed idea not yet done: link consecutive ready read jobs (F/R) into one chain so the channel doesn't idle mid-layer.
- **2026-11-03: nam_floor5 image (MD5 2b03600c…) INSTALLED and BOOTED**: started from normal mode 08:09 (bar sat at 0% a few minutes, then ran), 'Completed Successfully', restart 08:29, preset rebuild, back in normal mode 08:34:53. Sound / 2-NAM / load test pending the owner.
- **2026-11-03: nam_floor5 on hardware: step 1 (one NAM) SILENT.** Diagnostic built: `floor/nam_floor5d.py` with **one NAM slot per DSP** (`nam_floor5.SLOTS = 1`; the beep code is ~100 words over test2c with 2 slots, the second slot frees 190; diag spare R3 4 / R1 1 / R2 108, 0 over). Codes as nam_floor4d (channel 1 codes 2/3/7 cannot occur). Sim: good model = production output except call 0 (one inaudible call of beep while loading); empty slot = 5 beeps per ~0.68 s period. Image `build/Helix_Floor_v3.80.0_NAM2_DIAG.hxf` MD5 `70361e22c1f358335658b04c36c0ee7b` (l6ia ALL OK). Production rebuild after the SLOTS refactor still MD5 `2b03600c…` (identical). A 2nd NAM on one DSP in the diag image passes dry. Not installed yet.
- Helix Native "hardware mode" can't test the kernel: Native is x86 plugin code, it never runs the Floor's SHARC firmware; the mode only mirrors the Floor's model list/DSP limits.
- **2026-11-03: diag (nam_floor5d v1, MD5 70361e22…) on the Floor = 1 beep: channel 0 busy or P9I unmasked at entry.** nam_floor4d had passed the same check (it got to code 3), so the stock program leaves ch0 free: most likely OUR leftover. But v1's backoff beeped the LATEST failure, so 1 may be only the aftermath of an earlier abort (e.g. a timeout whose dma_abort waited just 100 polls for EXTS alone, leaving DMAS/CHS set; every retry then fails "busy"). Normal exit also writes DMAC0 = 0 without waiting for the status bits.
- **diag v3** (`nam_floor5d.PATCHES_V3`): beeps the FIRST failure since boot (sticky DCAUSE), 1 = DMAC0 busy bits vs 11 = P9I unmasked, and the channel is waited idle (all BUSYM bits, ≤1000 reads) after the exit's switch-off and in dma_abort. Fits (spare R3 9 / R1 8 / R2 74). Sim: good model = production except call 0; empty slot 5 beeps; stalled channel = 4 beeps on every retry (sticky). Image `build/Helix_Floor_v3.80.0_NAM2_DIAG.hxf` MD5 `d3cd4ccbe2345664fb2e8792257d7745`. If it now PLAYS, the idle-wait is the fix: port it to nam_floor5.
- **2026-11-03: diag v3 on the Floor = 11 beeps: FIRST failure = channel 0's interrupt (LIRPTL P9IMSK) UNMASKED, channel itself idle.** (nam_floor4d had seen it masked: not unmasked all the time, or only once something ran.) The Floor's stock DSP program enables the EPDMA0 interrupt; the Stomp's keeps it masked. Static search of Entry 2 (16-bit VISA parcels + 48-bit code) for `BIT SET/CLR LIRPTL`, `LIRPTL = Rn / imm / DM(...)` found the same handful of hits on both units, none setting 0x2000: the unmask goes through a form not searched (e.g. a compute + ureg move), not found.
- **diag v4 = `nam_floor5.P9_SHARE`** (on in nam_floor5d only): channel idle + P9I unmasked → mask P9I for the call (keep mask + latch bits in MSKD), at every exit wait the channel idle, clear the P9I latch (bit 3) unless it was already set at entry, unmask again. Risk: a Line 6 ISR starting a ch0 transfer mid-call would collide (not detected). Sim: LIRPTL 0 / 0x2000 / 0x2008 all give production's output (after call 0) and LIRPTL comes back unchanged. Spare R3 9 / R1 1 / R2 54. Image `build/Helix_Floor_v3.80.0_NAM2_DIAG.hxf` MD5 `4e91600c276de9aadb07891321a4937e`. If it PLAYS clean: set P9_SHARE (+ v3's idle-wait) in production nam_floor5 and rebuild the 2-NAM image.
- diag v4 rebuilt with SLOW beeps (easier counting): 171 ms beep every ~0.51 s, ~1.4 s pause (nam_floor5d.SLOW_BEEPS; sim-checked). MD5 `4e91600c276de9aadb07891321a4937e`.
- **2026-11-03: diag v4 WORKS ON THE FLOOR: one NAM plays** (first beeped 5 = no capture on the chosen Model slot, then played: a Model/slot choice, not a kernel fault). So the silence was the P9I check: the Floor's stock program keeps channel 0's interrupt unmasked while the channel sits idle; masking it for the call and restoring it is enough.
- **Production 2-NAM build with the fix:** `nam_floor5.P9_SHARE = True` (mask P9I per call, idle-wait + latch clear + unmask at every exit, dma_abort waits all status bits). Room (was 30 over): the REP R_POLLS / R_MAXPOLLS counting removed under P9_SHARE (4 wait loops + the max; only the sim bench and meter builds read it), and v3's extra exit wait at n_ewd dropped (the restore's wait covers it). Spare R3 1 / R1 1 / R2 12. **KernelCheck PASS, steady mean 34,874**; sim with 2 instances and LIRPTL 0x2000 / 0x2008: output identical to the masked case, LIRPTL restored. Image **`build/Helix_Floor_v3.80.0_NAM2_SHARE.hxf` MD5 `95d9e096cbf4f334d8cf7cd0b94e3eb8`** (2 NAM per DSP, normal codes, no beeps). NOT installed. (`NAM2_PERSONAL.hxf` = the old silent build; build_floor2's default output name still points there.)
- **2026-11-03: NAM2_SHARE (2 NAM per DSP) on the Floor.** 1 NAM on Path 1 and on Path 2: play. **2 NAMs on one path: "very weird, glitchy, like a broken sample rate"** (overrun). 1 NAM + Boctaver, Minotaur, Script Phase, Dynamic Hall: fine; **+ Simple Delay: crackling**. So the real per-block cost is above the declared DSP cost (2700/9000) and the Floor's budget lets presets overload the chip. Sim: 2 instances on one DSP ~41.5K instructions per call each (~28% of 150K each; 55% for the pair before Line 6's own load).
- **Meter build** `floor/nam_floor5m.py` (`build_floor2.py --meter`): every NAM block outputs its call's EMUCLK cycles x 2^-18 as a ±square (sign flips each call); sim (EMUCLK patched to the sim's cycle count) reads back the sim cycles minus the ~190-cycle restore. Room: REP report words/counters dropped (no KernelCheck on a meter image). `floor/meter_read.py [seconds|file]` records the Floor's USB input "Digital Audio Interface (Line 6 Helix)" via ffmpeg dshow (48 kHz, 2 ch; works from this PC) and prints median/99%/max cycles per channel. Image `build/Helix_Floor_v3.80.0_NAM2_METER.hxf` MD5 `57eb442b1189fb0355717966527c5970`. Not installed.
- **2026-11-03: METER v1 results on the Floor** (Windows' capture endpoint "Digital Audio Interface (Line 6 Helix)" is **1 channel** (48k/24): only USB 1 = main L is recorded, duplicated; pan the lane under test 100L):
  - A, 1 NAM alone, plain path: **55,064 cycles/call median (36.7%)**, max 58K. Sim steady ~41.8K → hardware ≈ 1.32× sim (Stomp ~1.35×).
  - C, 1 NAM last after Volume, Boctaver, Minotaur, Script Phase, Dynamic Hall: 55,064 (same). D, + Simple Delay: NAM still 55K, but ~17 broken frames in 5 s (DSP overrun = the crackle). So the single-NAM overload is the declared DSP cost (2700 = 30%) being too low.
  - **Split path (split at start, merge at end): 77.8K cycles/call (52%)**, whether lane B holds a second NAM (each NAM 77.8K → 104%: the "broken sample rate" glitch), a bypassed NAM (the Floor still calls a bypassed NAM every block) or just a Gain block (E). **Slowdown is the split layout, not two NAMs.** Sim: one or two instances cost the same.
  - Freeze once while building presets on the meter image (overload); power-cycle recovered.
- **METER v2** (`nam_floor5m`, SLOTS 1, KEEP_POLLS): per call 4 fields x 4 samples, ints/32768 exact through 16-bit capture: cycles/8, -wait polls, (I0-0x80000)/16, -(I8-0x80000)/16; `meter_read.py --v2`. Sim: 41.5K cycles, 538 polls, I0/I8 = rig's. Image `build/Helix_Floor_v3.80.0_NAM2_METER2.hxf` MD5 `38c20a16d884fa7dce9e89e6beab1d89`. Purpose: plain vs split — waits (DMA) or compute, and where the instance memory lands.
- **2026-11-03: METER v2 on the Floor.** A (plain path, NAM alone): 54.6K cycles, 276 wait polls/call, instance DM (caller's I0) **0x9a310** (heap a, Block 0), PM (I8) **0xe5de0** (heap b, Block 3). E2 (Split Y with Balance A 100L/B 100R, NAM on lane A, Gain on lane B, Merge A 100L/B 100R): **77.1K cycles, 391 polls, I0 0xa4ff0 (Block 1, outside heap a), I8 > 0x100000 (field clipped)**. So in a split path the Floor gives the block instance memory outside heaps a/b, and the kernel used it: the bounds guard only runs in m_init (slot start), the block had started in a plain path, and S_INIT survived the move (m_sdrok only re-inits on a new SDRAM block). **Bug: re-check I0/I8 every call (or on change) and re-init.** Likely slowdown cause: instance PM (near rings, touched every sample) in slower memory. (Windows capture is 16-bit through dshow: values jitter ±1-2.)
- **METER v3**: fields cycles/8, -(I8/64), (I0-0x80000)/16, -(SDRAM block/512). Sim OK. Image `build/Helix_Floor_v3.80.0_NAM2_METER3.hxf` MD5 `3565593ab440a4da5726ea24f67f3a17`.

## Split path explained + safety fix + speed decision (2026-11-04/06)

**The "52% in a split path" was a meter artifact, not a slower block.** Every field the meter read in the split path was 1.41x the plain path's, at once: cycles 77.1K / 54.6K = 1.412 (v1: 77.8K / 55.06K = 1.413), wait polls 391 / 276 = 1.417, I0 field 9471 / 6705 = 1.413. Independent quantities (time, a count, an address) cannot all grow by the same factor; a gain on the meter tone can: x1.414 = +3.01 dB, i.e. the Split Y / Merge balance (A 100L) pan law boosts lane A by 3 dB before USB 1. Corrected, the split path reads: cycles ~54.6K (same 36-37%), polls ~276, **I0 ~0x9a290 and I8 ~0xe5980 (inside heaps a and b), SDRAM ~0x82d600 (heap c)**. So:
- No split-lane pool, no second allocator: a NAM in a split lane gets ordinary heap a/b/c blocks. Heaps d/e/f/g are NOT where split lanes live (heap e, Block 1 0xb2000..0xb73b8, purpose still unknown; nothing measured points at it).
- The contradiction with the simulator disappears: the m_init bounds guard passed on the unit because the addresses were in range; the sim "guard2" test fed it the un-corrected (fake) addresses and correctly played silence.
- The real DSP cost per NAM is ~37% of a block in any path. "2 NAMs on one path glitch" = 2 x 37% + Line 6's own path load > 100%.
- Old conclusion in this file ("in a split path the Floor gives the block instance memory outside heaps a/b") is withdrawn.

**Meter v4** (`floor/nam_floor5m.py`, `meter_read.py --v4`) settles it on the unit: field 0 is a fixed 0.5 calibration, so the reader prints the gain after the block and corrects all fields; also I0, I8, DM(3,I0) (the stock "knob written" flag: turning a knob should blip it to 1, proving I0 is the real parameter block), DM(7,I0) (the Model knob word), and slot state (P_SLOT, DM guard, PM guard, S_INIT). Sim: in-range state 15 (slot 1, both guards ok, initialised, plays), DM out of range state 10 (silent). Image `build/Helix_Floor_v3.80.0_NAM2_METER4.hxf` (MD5 below). Test: same E2 split preset as v2; expect "gain x1.414 (+3.01 dB)", cycles ~55K, state 15. Then turn the Drive knob while recording: DM(3,I0) should show 1.

**Safety bug (latent) fixed in `floor/nam_floor5.py` (`PM_RECHECK`).** The near rings' pointers (S_RP) and the bounds guard come from I0 and I8 only at m_init. A new I0 restarts the slot (I0 is the owner key), but a new I8 with the same I0 kept the old PM ring pointers: shown in the sim, old kernel with I8 moved out of bounds kept playing (writing into memory it no longer owns). Fix: every call compares I8 with the slot's S_PMB (state word 71, free: S_LW 48..70, stream at 72); a change restarts the slot, so m_init's guard accepts the new blocks or the block plays silence. Room: the guard rewritten as two unsigned range checks (`COMPU`, I0 - LO <= HI - NEED - LO; same rule, 6 instructions fewer). Fits test2c: spare R3 1 / R1 1 / R2 11, 0 over. `floor/guard5.py`: inside plays; DM out, PM out, one word past the DM edge silent; last in-range DM edge plays; I8 moves out -> silent at once, back in -> restarts and plays: **PASS**.

**Speed: recommendation = faster streaming on channel 0, not more on-chip memory.** Simulated per NAM call (KernelCheck steady mean, instructions):

| Kernel | Weights | Sim instr | vs on-chip |
|---|---|---|---|
| nam_floor (1 slot) | on chip | 24,991 | - |
| nam_floor4 (ch1, banned on Floor) | streamed, channel always fed | 25,477 | +2% |
| nam_floor5 (installed design) | streamed, ch0 queue pumped only at layer starts/waits | ~34,9K | +40% |

Hardware: nam_floor5 = ~55K cycles = 37% (meter, gain-corrected). Streaming itself costs ~2%; the other ~38% is the channel idling mid-layer and layers waiting (~9.5K sim instr; the unit's ~276 wait polls/call). Projection for a streaming kernel that keeps channel 0 fed (chain ready F/R jobs, pump inside long layers): ~25.5-27K sim -> ~37-43K cycles = **25-29%** per NAM (range = the two hw/sim factors seen: 1.32 cycles-sim, 1.58 vs KernelCheck instructions), with no new memory beyond a few code words. DMA load per call (~14K taps + ~4.1K weights) fits under the ~25K compute, so the overlap is physically possible.

Weights on chip instead: at best -2% over that, and needs ~1.9K more on-chip words per DSP (findings 2026-11-01: 1 slot with weights on chip 6,568 static vs test2c 4,634). The only legal source is turning big slots to normal (+1,236 each; smaller-than-normal and deleted slots fail at boot). One more big slot -> 5,870: still ~500 short, and leaves 1 big slot per DSP (1 amp-type block per path; 2 NAMs per DSP impossible). Two more -> no big slot left for the NAM itself. **Not worth it.** Heap e (21K words, Block 1) is the only big unknown; shrinking it blind risks the same boot failure as test2d.

Next: (1) the owner installs METER4, records the split preset (confirms +3 dB, state 15); (2) DSP_COST to the real figure: 37% of 9000 ≈ 3,300, use ~3,400 so the Floor refuses overloads instead of crackling; (3) the fed-channel streaming kernel (nam_floor6), target 25-29%.

## 2026-11-06: UI freezes on the NAM images (the owner, last few days)

Symptom: buttons and screen stop responding until power-cycle; **audio keeps passing and playing**. So the SHARC audio loop runs; the ARM main program (UI) is stuck, or waiting on something from a DSP that never comes. Suspects, ranked:
1. **P9_SHARE latch race (NAM kernel).** The Floor's stock program keeps channel 0's interrupt (P9I) unmasked: Line 6 uses EP DMA channel 0 with interrupts (plausibly DSP<->host messaging). The kernel masks P9I for its call and at exit clears the P9I latch unless it was set at entry. If a Line 6 ISR starts a channel 0 transfer during our call, it collides with our chains, and its completion latch is then cleared by us: Line 6's handler never runs, its transfer state machine waits forever. Rare race -> freeze after hours; audio unaffected; fits the symptom. Only possible while a NAM block is in the running preset.
2. **Main-program patches (Entry 0):** guard HOOK, IR-title hooks, tables in the seg0 local-SRAM cave (`0x10011870..`, judged free by static checks only, never proven at runtime). Would freeze with or without NAM in the preset.
3. DSP overload: unlikely as the cause (audio would break up first).
Discriminator asked of the owner: does it freeze on presets with no NAM block? Yes -> 2; only with NAM -> 1. Advice meanwhile: stock firmware for anything that matters.
- Builds 2026-11-06: `build/Helix_Floor_v3.80.0_NAM2_METER4.hxf` MD5 `cea242c03eeb7402fa49351612ddfa82` (meter v4); `build/Helix_Floor_v3.80.0_NAM2_SAFE.hxf` MD5 `441abd90623c91f58c9e0f848738ae7f` (production 2-NAM with PM_RECHECK; KernelCheck PASS with MAX_STEADY 60000, steady mean 34,878). Neither installed. Bare `nam_floor5.py --check` fails only the default 33,000 speed limit (as always for nam_floor5).
- Upstream (nocaseguy/hx-stomp-nam-lite) news to port: HX Edit keeps NAM blocks by taking a stock model's preset ID with matching knob types (Stomp: 4 knobs on MM4 Frequency Shifter 461 on 11-03; since 11-04 ten knobs on Xenomorph Fuzz Mono 555); tone bands were dropped 11-03 (-0.5%/block) but **came back 11-04** as a fuller tone stack (Bass shelf, sweepable Mid + Q, Treble, High Cut; DSP cost 2275), so 'no tone bands' is NOT upstream's current state (the owner's correction); Stomp metering: 1/2/3 blocks 41.0/63.6/86.1% of the DSP total, i.e. ~22.6% per block on top of ~18% base; far rings in the block's own DM/PM (23.1%/block); 3 blocks per Stomp DSP (needs the Stomp's free Block 3: not portable as is).
- 2026-11-06: the owner: the freezes happened with a NAM block in the preset, **while just playing** (no buttons, no edits); no-NAM presets not tried yet. Main-program patches mostly run on UI events (block add/move, title redraw on knob), so suspect 1 (P9I latch race) moves up (~70%). Test build: `nam_floor5.P9_KEEP_LATCH` (env `NAM_KEEP_LATCH=1`) drops the latch clear at exit: a Line 6 completion during our call can no longer be lost; cost: Line 6's channel-0 handler also runs once after each NAM call for our own chain end (spurious; unknown whether it tolerates that: if not, expect a different symptom quickly, e.g. glitches or a fast freeze). Image `build/Helix_Floor_v3.80.0_NAM2_KEEPLATCH.hxf` (based on NAM2_SAFE).

## Lessons from upstream (nocaseguy/hx-stomp-nam-lite, read 2026-11-06: commits since 10-30 + docs/research + README)

- **Their overload symptom = the owner's freeze.** NAM_LITE_DSP_LOAD.md: "the overload hangs the UI/USB (the audio kept going)"; a heavy delay admitted by a too-low dsp_cost 2200 "hung (UI and USB; power cycle)". So an overloaded SHARC starves the host link while audio continues. **Freeze suspects re-ranked: (1) DSP overload from our too-low DSP_COST 2700 (~60%), (2) P9I latch race (~25%), (3) Entry 0 patches (~15%).** My earlier "overload would crackle first" was wrong.
- **Budget calibration (Stomp):** ~100 units per 1% real (delays ~175), the 9,000 cap ~95.7% real, an empty preset ~20% real but counted ~1,500 units; NAM block real = kernel call + ~1% graph overhead. Line 6's own load meter is the **idle-% word (Stomp DM 0xC2FD5)**: find the Floor's equivalent (relinked, shifted) and meter it to calibrate the Floor. -> `stage_main.DSP_COST` now 3800 (env `NAM_DSP_COST`).
- **Speed (their ladder, Stomp chip):** 26.9% -> 23.1%/block from: pair loop laid out so no I-cache set holds 3+ PM-data instructions (~1.7k cycles), signature check every 64 calls (have it), I-register loads off first use, X/HS/IN out of the weights' block, near-layer weights copied to WBUF in another block, fcopy SIMD, n_put two words a move (have it), far rings in the block's own DM (dm_words) and PM (pm_words). DMA was only ~4.4%/block for them (~29 wait polls/call vs our ~276): our extra cost is the channel-0 queue, as concluded above.
- **Block conflicts are the Floor's big tax.** HELIX_FLOOR_KERNEL_COST.md (their model of the Floor, not run): everything in Block 3 = +8.3k cycles (+5.5%/block) from DM/PM same-block and fetch conflicts. Our hot code and LB weights both sit in Block 3 (R1/R2): move the tap-loop DM operands (SB staging, X/HS) to Block 0 (R3) where room allows. Their chip/ssim ratio ~1.4-1.5 (ours 1.32-1.58) is mostly these stalls.
- **Heap e answered (Stomp twin):** Block 1 heap = 8 per-slot arenas of 2,571 words (call lists, instance records); a reverb fills its arena. No free memory there. Only ~1,700 words at the top of one Block 0 arena heap stayed unwritten (owner unknown).
- **HX Edit drops NAM blocks** on whole-preset writes (HX_EDIT_DROPS_NAM.md: a drag can send cmd 0x15 with the full preset built from HX Edit's own model list). Fix = take a stock model's preset ID and knob value types (Stomp: Xenomorph Fuzz Mono 555, ten knobs). The Floor will need the same (the owner uses HX Edit?).
- **NAM as an effect (kind 1)** escapes the 2-amp limit; needs per-instance DM within the effect slot (their dm_words 0x303 <= 0x38b). Ours uses 1,418 DM for near rings: would need the rings in SDRAM (slower) - not now.
- **Tooling:** `tools/hx_ctl.py` speaks HX Edit's USB protocol (HelixEditorService, select/load/set edit buffer, move blocks, `--pid`): could drive Floor tests and detect a freeze (edit port stops answering). Uses libusb: on Windows the Line 6 driver owns the device (driver swap = risk; not tried). Stock firmware also hangs after ~31 whole-preset USB writes per boot (their finding).
- Tone stack: dropped 11-03, back 11-04 (Bass/Mid sweep+Q/Treble/High Cut). Model change crossfades (~5 ms).
- Upstream and the Floor: README says "Not the Helix Floor, LT or Rack". Their research has a Floor first look (2026-10-28, static, "no Floor to test on") and a modelled Floor kernel cost (2026-11-04, "step 1", refers to a private HELIX_FLOOR_SHARC_MAP.md with the same 3,430 free Block 3 words we found and a "redesign"; next step a Stomp prototype in a 3,430-word window). So they are studying it, with no Floor and nothing built. Their estimate for the Floor: ~32-35%/block, 2 per DSP (ours: 37% today on hardware).

## Freeze test images (2026-11-06), both from the PM_RECHECK kernel, KernelCheck PASS 34,878
1. `build/Helix_Floor_v3.80.0_NAM2_HONEST.hxf` MD5 `5699df502341c608444b06d72886b3bb`: DSP_COST 3800 only (2 NAMs on one path now refused). Install first.
2. `build/Helix_Floor_v3.80.0_NAM2_KEEPLATCH.hxf` MD5 `538c3ba5358f9f7b2e40f232ee017167`: DSP_COST 3800 + P9I latch never cleared. Only if 1 still freezes.
(`NAM2_SAFE.hxf` = PM_RECHECK with the old 2700: superseded.)
- 2026-11-06: the owner installing NAM2_HONEST (MD5 5699df50...). Watch: freezes? 2nd NAM on one path refused? 1 NAM + effects clean?
- **2026-11-06: the freezing preset was overloaded on paper.** the owner: froze on NAM2_SHARE, his main live preset the main test preset (confirmed by the owner) with NAM replacing the distortion on Path 1 and 1 NAM replacing the 2 amps on Path 2. Declared costs (Floor Table 1, bypassed blocks count; scratch `pcost.py`): Path 1 stock 6,342 (Dual Pitch 710 off, Kinky Comp 535, Vol 35, Dhyana 650 off, Teemah 555, Transistor Tape 619, Chamber 793, Shimmer 1,800 off, Tremolo 145 off, Retro Reel 500 off); with NAM for a 650 drive: **8,392 of 9,000 at NAM's declared 2,700**, but NAM really costs ~3,800 -> ~9,500 equivalent: past the cap -> overload -> UI/USB hang with audio running (upstream's exact symptom). Path 2: 6,166 -> ~4,566, fine. Overload now ~80%. Note: preset LOAD runs no budget check, so an already-saved preset overloads even on NAM2_HONEST; Path 1 must shed ~600+ units (e.g. the bypassed Shimmer, 1,800). Recommendation flipped to NAM2_HONEST (no new risk) over KEEPLATCH.
- 2026-11-06 08:19: NAM2_HONEST installed, Floor back in normal mode (USB serial <serial>). Pending: budget check (re-add NAM per path), long play test of the main test preset (drives + Shimmer moved to Path B).
- 2026-11-06: HONEST budget check: NAM re-add allowed on Path A and Path B of the main test preset (both within 9,000 at cost 3800). Play test: 5 min, no freeze so far (not conclusive).
- 2026-11-06: HONEST live check: with one NAM on Path 1 of the main test preset the whole Amp category is greyed out (no room for another amp-sized block; est. ~360 units left): the 3800 cost is enforced.
- 2026-11-06: the owner: the controller-assign screen for a NAM block's Input (knob 1; footswitch toggles Input for extra drive) is laggy when fine-tuned with the encoders. Not ir_title: site B's redraw path (0x280ad38e) redraws only for knob 0, or knob 6 of subcategory 1; Input is knob 1. Likely cause: Path 1 near the cap (~96% real est.), so the DSP has little idle time to answer the host's parameter messages (a mild form of the overload hang). Test asked: does a stock block's knob on the same path lag the same way?
- **2026-11-06 ~09:00: NAM2_HONEST FROZE** (the owner: soon after the "5 min, no freeze" report, far less than 40 min of playing; my 40 min counted from boot at 08:19 incl. setup and checks; the main test preset within the 3800 budget on both paths; around the laggy NAM-Input controller screen, before any stock-block test). USB device still enumerated (OK) after the freeze. So DSP_COST alone does not fix it. Re-read: the lag + freeze both appear when the host sends many parameter messages (encoder fine-tuning). That fits the P9I/channel-0 theory well: if Line 6's DSP<->host messaging rides EP DMA channel 0, our kernel holds the channel and masks P9I for ~37% of every block (lag), and a Line 6 completion landing in our call gets its latch cleared (permanent hang). Next: NAM2_KEEPLATCH. If that still freezes: the channel-0 sharing itself (Line 6 transfer started mid-call colliding with our chains), i.e. need ch0 left alone (weights back on chip / a different transfer path), or the Entry 0 patches.
- 2026-11-06 09:27: NAM2_KEEPLATCH installed (the owner), Floor on USB in normal mode (<serial>). Test: the main test preset + fine-tuning the NAM Input controller screen.
- 2026-11-06 evening: KEEPLATCH active test (the owner, the main test preset): no freeze so far; idle day soak also survived. All knobs/controls smooth EXCEPT the controller-assign screen (still laggy). Not yet compared with a controller assign on a stock block, so whether that lag is ours or stock Line 6 is open. Not proof yet: HONEST froze ~5-15 min into play.
- 2026-11-06 evening: controller-assign lag comparison: stock Line 6 blocks lag too on that screen, just less than NAM. So the lag is partly stock behaviour; the extra on NAM likely comes from our call's length (P9I masked ~37% of the block) and should shrink with a faster kernel. the owner stepped away with the Floor running; will report frozen / not frozen.
- 2026-11-06 correction: the daytime "idle soak" proves nothing: after an update the Floor boots to preset 01 (no NAM block), so our kernel never ran. Real KEEPLATCH data so far = the short evening play only (no freeze).
- **2026-11-06 17:41: NAM2_KEEPLATCH FROZE** (same symptom: UI/buttons dead). Latch-clear race alone is not the cause. Next: bisect (a) NAM vs no-NAM preset on the same image (Entry 0 patches?), (b) a no-DMA diagnostic kernel (channel-0 sharing?).
- **2026-11-06: upstream lessons for the freeze** (upstream 003bc0d):
  1. Their DMA rule (nam_multi_kernel.asm header): a channel found busy, OR with its interrupt unmasked, is never used (silent + backoff). On the Stomp the stock never uses EP DMA, so the rule always passes. The Floor's stock keeps P9I unmasked and has a real ch1 handler; our P9_SHARE overrides their rule. Their proven-safe condition does not exist on the Floor. Two freezes (HONEST, KEEPLATCH) fit "sharing ch0 is the problem", not just the latch.
  2. Their other UI hangs (audio running) were memory overlap: stock blocks quietly take a few words of the "free" region NAM used (NAM_A2_FULL_STOCK_UNIT.md: delays/EQs/comp take up to 199 words at fixed spots; a canary written over a delay hung the unit). They mapped it with a canary probe (nam_full.py --probe) and left --room gaps. the main test preset is block-heavy and our test2c layout shrank stock slots: same risk class, never probed on the Floor.
  3. Overload -> UI hang (handled: DSP_COST 3800).
  4. Automated soak over USB (hx_smoke.py stress --soak, hx_ctl.py = HX Edit's protocol) could reproduce freezes without the owner playing; Stomp-only, needs a Floor port.
  Next bisect: no-DMA diag image (tests 1); canary probe (tests 2); non-NAM preset on current image (tests Entry 0 patches).
- 2026-11-06 auto-tester groundwork (`floor/auto/midi.py`, winmm ctypes, no packages): Floor MIDI over USB works (PC 21/22 = 06B/06C in setlist USER 1 confirmed on screen); Floor sends nothing back by default (no identity reply, no PC echo). Power: Kasa EP10 "Fan" at <plug-ip>, local control, no login (python-kasa 0.7.7, discover with target <plug-ip>). Next: a heartbeat from the Floor (MIDI clock send over USB) for freeze detection.
- 2026-11-06 ~17:53-18:05: KEEPLATCH froze AGAIN, idle on 06C (the main test preset) within ~10 min of a fresh boot+MIDI preset hops. HX Edit (3.82) could not connect while frozen; after a Kasa power cycle (plug.py cycle) it connected fine (so 3.82 talks to 3.80). HX Edit's window title ('No device connected' vs 'Helix Floor') is a usable freeze signal.
- 2026-11-06 ~18:50: **auto-tester working** (`floor/auto/`): midi.py (winmm), plug.py (Kasa cycle; refuses while INSTALLING.lock exists), probe.py (ASIO Helix via sounddevice SD_ENABLE_ASIO=1: 1 kHz on USB 3/4, record USB 1/2; Windows WDM/MME only reach USB 1/2 out / 1 ch in), soak.py (06C NAM runs, every 60 s PC 23 -> tone must appear (-15 dBFS) and PC 22 -> gone (-92), confirm twice, else power-cycle and log time-to-freeze), gui.py (pyautogui + screenshots; desktop is session 1, works). 06D = FREEZE PROBE (USB 3/4 in -> out, no NAM) made in HX Edit. **HX Edit must never edit/copy NAM presets** (upstream HX_EDIT_DROPS_NAM: it rewrites presets from its own model list and drops NAM). Note the probe itself unloads/reloads NAM each minute (a stressor/confounder). First soak: KEEPLATCH, 2 h, stop after 3 freezes (soak_keeplatch.log).
- **2026-11-06 soak KEEPLATCH on 06C (NAM), unattended: 3 freezes at 32.8, 2.8, 12.4 min (mean ~16)**, each recovered by plug cycle. Random spacing -> a race, not a buildup. Freezes need no user input. Next soak: same image, home 06A (empty, no NAM) for 1.5 h (soak_keeplatch_nonam.log): freezes there = Entry 0 patches; none = NAM running is the trigger.
- **2026-11-06 ~20:20: ROOT CAUSE FOUND (very likely): P9I is link port 1, not EP DMA channel 0.** Both stock DSP programs (Floor and Stomp, identical code at 0x8c12c..0x8c133) write PICR0 = 0x0A821C66, PICR1 = 0x241D6570, PICR2 = 0x000DDC13 at boot. Decoded (HRM Table A-6 codes): P0I SP0, P1I SP1, P2I SP2, P3I SP3, P4I SP4, P5I SP5, P6I SP6, P7I SP7, **P8I LP0I (0x19), P9I LP1I (0x1A)**, P10I SPIHI, P11I SPILI, P12I UART0Rx, P13I DAIHI, P14I TWI, P15I ACC0. **EPDM0I (0x09) and EPDM1I (0x0D) are routed nowhere: neither EP DMA channel raises any interrupt on either unit.** Our earlier reading "Floor unmasks EP DMA ch0's interrupt / has a ch1 handler" was wrong: the Floor unmasks P9I because it runs **link port 1 between its two SHARCs** (the Stomp, one DSP, leaves it masked; vector 0x17 = P13I = DAI high-priority handler, not EP DMA 1). So P9_SHARE masked the **inter-DSP link interrupt** for our whole call (~37% of every block) and HONEST/SHARE cleared its latch: delayed (lag) and occasionally lost (freeze) link-port interrupts. Fits: freezes only with NAM running (no-NAM soak clean), random timing, audio on, UI/host messaging dead, more lag on NAM screens.
- Fix: `nam_floor5.P9_MODE = "nomask"` (default; env NAM_P9_MODE=share for the old images): never touch LIRPTL; use channel 0 when DMAC0 is idle; wait the channel fully idle at exit and in dma_abort. Image NAM2_NOMASK. Bonus: channel 1 is equally free (no interrupt, no stock references), so the faster ch1 design (nam_floor4: 25.4K vs 34.9K steady) is back on the table.
- NAM2_NOMASK built 20:19: MD5 58e359a9d6cb3e5f052e2aa103fc3a05, KernelCheck PASS steady 34,874, l6ia ALL OK, 0 budget errors.
- 2026-11-06 no-NAM soak (KEEPLATCH image, home 06A empty, same per-minute probe): **0 freezes in 48 min** (vs 3 in 48 min on 06C NAM, mean 16). Stopped early for NOMASK. => freezes need NAM running.
- 2026-11-06 20:22-20:58: **NAM2_NOMASK installed by Claude** (Line 6 Updater, Offline Mode, local file; EULA accepted with the owner's OK), back on USB 20:58. After an update the Floor sits in a factory setlist: MIDI PC must be preceded by CC32 = 2 (setlist USER 1); midi.pc now does that.
- 2026-11-06: **why nam_floor4 (weights on channel 1) was silent on the unit:** its start check skipped the block whenever LIRPTL P13IMSK was set, and on the Floor P13I = DAI high priority (always unmasked), not EP DMA 1. `floor/exp_ch1_nomask.py` = nam_floor4 with both LRPTL checks removed: sim KernelCheck PASS, **steady mean 25,469 / worst 32,504** (NOMASK ch0-only: 34,874), 0 over, spare R3 5 / R1 2 / R2 190. Still lacks nam_floor5's PM_RECHECK safety (S_PMB, unsigned guard). Candidate next image once NOMASK proves stable (~27% less DSP per NAM).
- NAM2_CH1 built 21:4x: MD5 7b6a6906edd1db095a42666b63ffe563, KernelCheck PASS steady 25,473, ALL OK (DSP_COST still 3800 until measured). Meter variant: build_floor2.py --ch1 --meter (exp_ch1_meter.py, v4 fields, 2 slots fit: spare R3 1 / R1 1 / R2 78).
- NAM2_CH1_METER built: MD5 43a9bf8ae1d68702e0f4a66da82a3574 (meter v4 fields from the ch1 kernel; read with METER_DEVICE=ASIO meter_read.py 3 --v4 while 06C plays).
- 2026-11-06 NOMASK idle soak (per-minute preset hop only): **0 freezes in 51 min** (KEEPLATCH same test: 3 in 48). Stopped to switch to a stress soak (SOAK_STRESS=1: ~8 MIDI msgs/s between checks: FS1-5/7-11 presses CC49-58, snapshots CC69, EXP1/2 CC1/2 sweeps, tap CC64; no save/looper/mode CCs).
- **2026-11-06 22:41: NOMASK VERDICT: freeze fixed.** Realistic soak (one FS toggle or EXP sweep every 10-20 s, the owner's profile) 0 freezes in 42 min, plus the idle soak 0 in 51: 93 min NAM running, 0 freezes (KEEPLATCH: 3 in 48, mean 16; p(luck) ~0.3%). NAM sound on NOMASK still unconfirmed by ear. Next: CH1_METER (real cost) -> CH1.
- 2026-11-06 22:42: the owner: accept the Line 6 EULA for all test installs tonight. CH1_METER install started.
- 2026-11-06 23:03 CH1_METER installed (Claude), Floor up 23:08, probe ALIVE; 06C reads exact digital silence (-180 dBFS) on this image (NOMASK: -92 noise).
- **2026-11-06 23:10: NAM2_CH1_METER HANGS THE FLOOR when a NAM block runs.** First boot: 06D (no NAM) alive; 06C (NAM) gave exact digital silence (-180 dBFS, not noise) = DSP output dead. hx_ctl status/get-preset still worked once, then the next requests timed out ("no SYN reply"), the Floor stopped answering USB control, audio all-zero. Every power cycle boots into 06C again (last preset) and hangs again (06D PC spam at boot did not help); Line 6 Updater sees no device. Needs the 6+12 recovery boot (the owner) -> reinstall NOMASK. So channel 1 is NOT freely usable on the unit after all (or the ch1 kernel has a hardware-only bug: nam_floor4 never got past its P13I check on the unit before, so its ch1 path was never run on hardware). CH1 shelved until understood.
- 2026-11-06 23:25 the owner did the 6+12 recovery boot; NOMASK reinstalled by Claude, up 23:50 (ALIVE, 06C -91.6 dBFS noise = normal). Overnight realistic soak started (soak_nomask_night.log, 8 h, stop after 3 freezes).
- 2026-11-06 ~23:58 overnight soak stopped at the owner's request (squeeze first, soak only the final build). Sim profile of NOMASK (2 instances, steady, sim cycles): real DMA timing 41.7K/call, instant DMA 29.0K (waits = 30%), DMA 2x faster 31.8K, 2x slower 59.4K; channel busy 24.6K/call (~all of it taps+weights). A perfectly fed channel 0 -> ~29K = ~0.70 x today = ~26% real per NAM. Constraint: code space (spare R3 1 / R1 1 / R2 11 words).
- 2026-11-07 00:2x: **NAM SOUND CONFIRMED on NOMASK** (no guitar): namtest.py put 06C's path-0 NAM block (model 380) into 06D's edit buffer (USB 3/4 in, never saved) via hx_ctl; 220 Hz in -> -22.1 dBFS out with amp-like harmonics (H2 -25, H3 -11.5, H5 -19 dB). hx_ctl edit-buffer writes work on the Floor (re-encode byte exact; slot_index(0,4)=5 matches).
- 2026-11-07 ~00:05: **2 NAM in one path refused on NOMASK** (hx_ctl edit buffer, 06D + 2 copies of 06C's NAM on path 0: the unit dropped both; 1 copy plays clean: -22.1 dBFS steady, no dropouts). Budget: 2 x 3800 + ~1500 base > 9000; real ~37% x2 + ~20% base ~ 94-96% = at the cap anyway.
- **MID_PUMP (pump between chunks of the pair loop) does NOT help** (sim, real DMA timing: off 41.7K, 2 chunks 42.2K, 4: 42.6K, 8: 43.5K). The channel is not idle for lack of a pump; it is buffer/dependency-bound (one layer of prefetch: LB/SB double buffers; no memory for more). Default MID_PUMP=0 (unchanged images).
- **DMA per call (sim): 5,890 words, 303 TCBs, busy 25.3K cycles = 12.4K words + 12.1K TCB overhead** (sim's guess 40 cycles/TCB). Far layers 3-6, 10-13, 19-22 (12), groups of 4. Tap jobs = 12 x 15 TCBs of 16 words. Interleaving the 3 channels of a ring (one 48-word TCB per tap, 60 instead of 180) would cut ~1/3 of DMA time; projected maybe ~10% per call. Perfect DMA (instant) floor = 29.0K sim ~ 26% real.
- 2026-11-07 ~00:10: the owner: 2 NAM on the SAME chip needed. **Sim lever: per-TCB overhead.** tcb=0 -> 32.5K (-22%), TCB cost /3 -> 34.4K (-17.5%). **Plan: scatter/gather (tap list) EP DMA** (HRM 4-133, TCB Table 3-26: 8 words CPEP,TPEP,TCEP,EMEP,EIEP,ICEP,IMEP,IIEP; DMACx TLEN bit 9; offsets 27-bit signed, pre-modify EIEP + TL[i] + EMEP*k; block size ICEP per tap; chaining supported). A far layer's taps: 1 TCB with 18 offsets (3 channels x (5 taps + 1 dummy that fcopy overwrites)) instead of 15; write-back: 1 scatter TCB per far layer. ~303 -> ~110 TCBs/call. Projected ~29-31% per NAM real; 2 NAM + base ~80%. Needs: sim ChainDma tap-list model, pump TCB builder, chain tables (8-word TCBs). Hardware test only via 06D edit buffer (namtest.py), never a saved NAM preset.
- 2026-11-07 ~00:20: **GATHER (NAM_GATHER=1) works in sim: KernelCheck bit-exact PASS, steady mean 31,693 (NOMASK 34,874, -9.1%), worst 38,872**; sim cycles 37.9K vs 41.7K; DMA/call 6,466 words, 135 TCBs, busy 20.7K (TCB part 5.4K). Frees memory: spare R2 156 (RCH 96 -> 35 words each). Projected real ~33.6%/NAM. Model assumes HRM pre-modify (first word at EIEP + TL + EMEP) and 4 cycles/tap (guess): to verify on the unit.
- 2026-11-07 ~00:25: reference for on-unit equivalence: NOMASK NAM (06D edit buffer, NAM block copied from saved 06C_editbuf.bin, never loading 06C) with 220+523 Hz tone: two takes match at -49.8 dB residual, lag 0 (auto/tonerec.py). A kernel that fetches the wrong taps would differ grossly.
- 2026-11-07 00:29: NAM2_GATHER (MD5 8482e362a6cdc5c39d194c9928a1e734) install started by Claude (auto/install.py), Floor left on 06D before.
- 2026-11-07 00:34: GATHER_W (scatter write-back, default on with NAM_GATHER=1; NAM_GATHER_W=0 off): sim bit-exact PASS, steady 31,172 (GATHER taps only 31,693; NOMASK 34,874), spare R3 7 / R1 7 / R2 171. Not in the NAM2_GATHER image being installed (taps only).
- **2026-11-07 00:56: NAM2_GATHER on the unit: as soon as NAM ran (06D edit buffer), ALL audio went to exact digital zero (-240/-180 dBFS) while the ARM/UI kept answering (hx_ctl status OK) = same symptom as CH1.** Safe protocol worked: plug cycle -> boots 06D (no NAM) -> healthy at 00:57, no the owner needed. Theory: longer unbroken EP DMA bursts (gather: 288-word TCBs; CH1: two channels) starve the audio/link DMA on the IOP bus -> audio engine stops. NOMASK's many 16-word TCBs leave gaps. Check EPCTL arbitration/freeze.
- 2026-11-07 01:05: control NOMASK2 (current code, no gather) = byte-identical to NOMASK (MD5 58e359a9...): the MSKD/alloc edits changed nothing; GATHER's failure is the gather itself. NOMASK2 being installed (restores the good build). Built **NAM2_TLPROBE** (MD5 41abb56c47e19944ee665d666b701b4e, nam_floor5t.py): NOMASK + meter; at each call's exit one 2-tap x 4-word tap-list DMA from the instance's own SDRAM into PRB, polled; reports polls, DMAC0 status, which words landed (pre/post-modify). Sim: 12 polls, status 0, match 13 (pre-modify).
- **2026-11-07 01:59 TLPROBE on the unit: a single (unchained) tap-list DMA WORKS** (7 polls, DMAC0 status 0, data landed: not poison; audio kept running; 06D NAM edit buffer). Source words G_SDR+0..25 all equal (low bits 5847) -> pre/post-modify undecided. Note: ASIO capture must run at 48 kHz for meter frames (44.1 kHz resamples). GATHER differs by CHAINING two tap-list TCBs (TCB0 -> sentinel TCB1, CP = next TCB + 7): prime suspect. Next: TLPROBE2 = chained pair, distinct source (weights).
- **2026-11-07 02:30 TLPROBE2 on the unit: CHAINED tap-list TCBs WORK** (9 polls, status 0, TCB 1 ran). **Addressing is POST-modify: block i word k at EIEP + TL[i] + EMEP*k** (d0 = S5, d4 = S21, TCB1 word = S40), not the HRM table's pre-modify reading. So GATHER read every window 1 word early AND its sentinel read SENT-1 (never MAGIC) -> every tap job timed out -> dma_abort -> NAM silent (06D's only path runs through NAM, hence 'dead' audio; UI fine). Not a hang. Fix: EIEP = ring, sentinel EI = SENT, write-back EI = window (no -1); sim GatherDma post-modify.
- **2026-11-07 03:11: NAM2_GATHER2 WORKS ON THE UNIT** (MD5 26aa826af5f657dbbdf3befc47365eff; NAM_GATHER=1, taps gathered + write-back scattered, post-modify): 06D edit-buffer NAM with 220+523 Hz tone matches the NOMASK reference at -46.2 dB residual, lag 0 (two NOMASK takes: -49.8), level -22.1 dBFS steady, same harmonics, 0 jumps. Sim steady 31,139 vs 34,874. Next: NOMASK_METER (d828f6d3...) and GATHER2_METER (a533b09d...) for real cycles.
- 2026-11-07 03:41: **GATHER2_METER on the unit: ~52.8K cycles a call** (51.9-53.5K; fields: I0 field 6705, I8 field 14711, Model 50, state 15). Earlier NOMASK-era meter (v2, 11-03, P9_SHARE): 54.6K. Real gain looks ~3%, sim said ~11%: sim overstates TCB cost. NOMASK_METER next (same conditions).
- 2026-11-07 04:08: meter after the NOMASK_METER install (Updater's final page showed a Line 6 web 503, install probably done): 52.7-52.8K cycles median (max 56.7K) = same as GATHER2_METER (~52.8K). Either gather saves ~nothing on the unit (real per-TCB cost small; sim's 40 cycles/TCB too high) or the install did not take; unconfirmed. Both ~35% of a 150K-cycle block. Built NAM2_GATHER2_C3600 (DSP_COST 3600, MD5 35b0a2ba39cba23fb2ccb0bd1d7acc0c) for the 2-NAM-per-DSP test.
- **2026-11-07 04:40: 2 NAM ON ONE DSP PLAYS** (NAM2_GATHER2_C3600, DSP_COST 3600; 06D edit buffer, 2 copies of 06C's NAM on path 0 = same DSP): accepted (was refused at 3800), 220 Hz: -22.6 dBFS steady over 10 s, 0 jumps, harmonics of two amps in series; UI/hx_ctl responsive. 1 NAM on C3600 matches the NOMASK reference (-45.5 dB). The 503 page at the Updater's end is its web panel only (install fine) -> the NOMASK_METER reading was real: **NOMASK ~= GATHER2 ~= 52.8K cycles on the unit (35%)**; gather's sim gain does not show on hardware.
- 2026-11-07 05:02: **2 NAM on one DSP, 20-min stability: 0 bad checks** (stab2.py: every ~37 s a 4 s 220 Hz check = -22.6 dBFS steady, 0 jumps; hx_ctl status OK every time). Next: NOMASK_C3600 (f4338695...) = same test, as the preferred final kernel.
- 2026-11-07 05:28: NOMASK_C3600 on the unit: 1 NAM matches the reference (-46.1 dB), 2 NAM on one DSP accepted and plays (-22.6 dBFS steady, 0 jumps). Stability run started.
- **2026-11-07 05:50: NOMASK_C3600 (f4338695c5fa965f9100a0d82e632b7e) = current best, ON THE FLOOR.** 2 NAM on one DSP, 20 min: 33 checks, 0 bad. Same kernel as the freeze-fixed NOMASK (only DSP_COST 3800 -> 3600, matching the measured ~35% + overhead). Practical layout: 2 NAM on Path 1, effects on Path 2 (other DSP), Path 1 -> Path 2. Open: a realistic soak on a real preset with 2 NAM (the owner builds it on the device: HX Edit must not touch NAM presets).
- 2026-11-07 ~06:00: the owner built 07A (PC 24): 2 NAM on Path 1 (split, stereo) + Path 2: 3 mod, 2 delay, 3 reverb. Realistic soak on NOMASK_C3600 started (soak_c3600_07a.log).
