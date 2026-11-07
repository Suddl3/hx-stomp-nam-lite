#!/usr/bin/env python3
"""Main-program (ARM, Entry 0) guards for the 13-block layout (floor-port-findings.md,
"How the main program limits blocks per DSP").

The stock budget check 0x28135070 (new DSP cost total <= 9000 -> 1) has exactly two
callers: the browser's availability pass (returns to 0x2814b7fe) and the move/paste
check 0x2811de44 (returns to 0x2811de74). Its first 8 bytes become a jump to HOOK, in
the local-SRAM cave (seg0 grown past 0x10011870). HOOK keeps the budget check and adds:

- browser: a model is unavailable when the target position is empty and the DSP already
  has 13 blocks; and when it is a big-slot block (amp 0x11, amp + legacy cab 0x12,
  amp + cab 0x21, legacy dual cab 0x10) and the DSP's big-slot blocks, less the one it
  replaces, are already 2;
- move/paste: a block already inside the target DSP's struct (a move within the DSP) is
  allowed; otherwise, onto an empty position (r5 == 0 there), refused when the DSP already
  has 13 blocks, or when the block is a big-slot one and the DSP already has 2. The block's
  descriptor comes from 0x2811de44's saved registers, by its caller. Onto an occupied
  position the counts are taken as unchanged (the replaced block's type is not at hand).

Block counting mirrors the stock counter 0x2811c804: the DSP struct's n = [+0xac4]
records at +0xaf0 + k * 0x9f4 and 3 more at +0x8c54 + j * 0x9f4; a record counts when
bit 0 of [+0x24] is set and its type byte [+0x28] is 1..0x21 (a browser block type).

Output: the cave bytes at CAVE and the 8-byte patch at 0x28135070, each checked by
disassembling it back (capstone). Nothing is written to any firmware file.
usage: arm_guards.py [--bytes]
"""
import struct
import sys


CAVE = 0x10011870
TRAMP = 0x28135070
AVAIL_RET = 0x2814B7FF          # the availability pass's return address (bl at 0x2814b7fa), Thumb bit set
MOVE_RET = 0x2811DE75           # the move/paste check's (bl at 0x2811de70)
C1_RET, C2_RET = 0x28125ADF, 0x28125CF9   # 0x2811de44's two callers' return addresses
DSP_STRUCT = 0xB424                         # a DSP struct's size (base + 0xb424 * index in both callers)
import os  # noqa: E402
MAX_BLOCKS, MAX_BIG = int(os.environ.get("NAM_MAX_BLOCKS", "13")), 2   # (16: the 2-NAM build keeps every block slot)
COND = dict(eq=0, ne=1, hs=2, lo=3, mi=4, pl=5, hi=8, ls=9)


class Asm:
    """Just the Thumb encodings this file uses; labels resolved in a second pass."""

    def __init__(self, base):
        self.base, self.items, self.labels = base, [], {}

    def label(self, name):
        self.items.append(("label", name))

    def h(self, hw):
        self.items.append(("h", hw))

    def b(self, cond, target):
        self.items.append(("bcc", cond, target))

    def bl(self, target):
        self.items.append(("bl", target))

    def lit(self, rt, name):
        self.items.append(("lit", rt, name))

    def word(self, name, value):
        self.items.append(("word", name, value))

    def ldrpc(self, name):
        """ldr.w pc, [pc, #imm]: a jump through the literal `name` (anywhere in memory)."""
        self.items.append(("ldrpc", name))

    def align4(self):
        self.items.append(("align",))

    def size(self, it, pc):
        k = it[0]
        if k == "label":
            return 0
        if k in ("h", "bcc", "lit"):
            return 2
        if k in ("bl", "ldrpc"):
            return 4
        if k == "word":
            return 4
        if k == "align":
            return (-pc) & 3

    def assemble(self):
        pc, addr = self.base, {}
        for it in self.items:
            if it[0] == "label":
                self.labels[it[1]] = pc
            if it[0] == "word":
                addr[it[1]] = pc
            pc += self.size(it, pc)
        out, pc = bytearray(), self.base
        for it in self.items:
            k = it[0]
            if k == "h":
                out += struct.pack("<H", it[1])
            elif k == "bcc":
                off = self.labels[it[2]] - (pc + 4)
                assert off % 2 == 0
                if it[1] == "al":
                    assert -2048 <= off // 2 < 1024, it
                    out += struct.pack("<H", 0xE000 | ((off // 2) & 0x7FF))
                else:
                    assert -128 <= off // 2 < 128, it
                    out += struct.pack("<H", 0xD000 | COND[it[1]] << 8 | ((off // 2) & 0xFF))
            elif k == "lit":
                a = addr[it[2]]
                off = a - ((pc + 4) & ~3)
                assert off >= 0 and off % 4 == 0 and off // 4 < 256, it
                out += struct.pack("<H", 0x4800 | it[1] << 8 | off // 4)
            elif k == "bl":
                off = self.labels[it[1]] - (pc + 4)
                s = (off >> 24) & 1
                i1, i2 = (off >> 23) & 1, (off >> 22) & 1
                j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
                out += struct.pack("<HH", 0xF000 | s << 10 | (off >> 12) & 0x3FF,
                                   0xD000 | j1 << 13 | j2 << 11 | (off >> 1) & 0x7FF)
            elif k == "ldrpc":
                off = addr[it[1]] - ((pc + 4) & ~3)
                assert 0 <= off < 4096, it
                out += struct.pack("<HH", 0xF8DF, 0xF000 | off)
            elif k == "word":
                out += struct.pack("<I", it[2])
            elif k == "align":
                out += b"\x00\x00" * (self.size(it, pc) // 2)
            pc += self.size(it, pc)
        return bytes(out)


# 16-bit Thumb encodings
def movs(rd, imm): return 0x2000 | rd << 8 | imm
def cmpi(rn, imm): return 0x2800 | rn << 8 | imm
def addsi(rd, imm): return 0x3000 | rd << 8 | imm
def subsi(rd, imm): return 0x3800 | rd << 8 | imm
def adds3(rd, rn, rm): return 0x1800 | rm << 6 | rn << 3 | rd
def addsi3(rd, rn, imm3): return 0x1C00 | imm3 << 6 | rn << 3 | rd
def cmpr(rn, rm): return 0x4280 | rm << 3 | rn
def mov(rd, rm): return 0x4600 | (rd >> 3) << 7 | rm << 3 | (rd & 7)
def ldr_imm(rt, rn, off): assert off % 4 == 0 and off < 128; return 0x6800 | (off // 4) << 6 | rn << 3 | rt
def ldrb_imm(rt, rn, off): assert off < 32; return 0x7800 | off << 6 | rn << 3 | rt
def ldrb_reg(rt, rn, rm): return 0x5C00 | rm << 6 | rn << 3 | rt
def ldr_sp(rt, off): assert off % 4 == 0 and off < 1024; return 0x9800 | rt << 8 | off // 4
def add_sp(rd, off): assert off % 4 == 0 and off < 1024; return 0xA800 | rd << 8 | off // 4
def lsls(rd, rm, imm): return imm << 6 | rm << 3 | rd
PUSH_R4_R7_LR, POP_R4_R7_PC, BX_LR = 0xB5F0, 0xBDF0, 0x4770
FP, LR = 11, 14
FRAME = 20                      # HOOK's push {r4-r7, lr}: the caller's sp is sp + 20


def is_big(a, rt, rflag, tag):
    """rflag = 1 when the type in rt is a big-slot block type (0x10..0x12 or 0x21); rt kept."""
    a.h(movs(rflag, 0))
    a.h(cmpi(rt, 0x21))
    a.b("eq", f"{tag}_y")
    a.h(mov(7, rt))
    a.h(subsi(7, 0x10))
    a.h(cmpi(7, 2))
    a.b("hi", f"{tag}_n")
    a.label(f"{tag}_y")
    a.h(movs(rflag, 1))
    a.label(f"{tag}_n")


def build():
    a = Asm(CAVE)
    # ---- HOOK: r1 = the DSP's cost total with the change; returns r0 = 1 if allowed
    a.label("hook")
    a.lit(2, "k9000")
    a.h(cmpr(1, 2))
    a.b("hi", "over")
    a.h(PUSH_R4_R7_LR)
    a.h(mov(4, LR))
    a.lit(7, "avail_ret")                           # (r5, r6 stay as the caller left them)
    a.h(cmpr(4, 7))
    a.b("eq", "avail")
    a.lit(7, "move_ret")
    a.h(cmpr(4, 7))
    a.b("eq", "move")
    a.label("yes")
    a.h(movs(0, 1))
    a.h(POP_R4_R7_PC)
    a.label("no")
    a.h(movs(0, 0))
    a.h(POP_R4_R7_PC)
    a.label("over")
    a.h(movs(0, 0))
    a.h(BX_LR)
    # browser: fp = the DSP struct; the caller's [sp + 0x38] = the model's browser entry
    # (word 0: its block type), [sp + 0x60] = the target position's block type (0: empty)
    a.label("avail")
    a.h(mov(0, FP))
    a.bl("count")                                   # r0 = blocks, r1 = big-slot blocks
    a.h(ldr_sp(2, FRAME + 0x38))
    a.h(ldr_imm(2, 2, 0))                           # r2 = the new block's type
    a.h(add_sp(3, FRAME + 0x60))
    a.h(ldrb_imm(3, 3, 0))                          # r3 = the replaced block's type
    a.h(cmpi(3, 0))
    a.b("ne", "a_big")
    a.h(cmpi(0, MAX_BLOCKS))
    a.b("hs", "no")
    a.label("a_big")
    is_big(a, 2, 4, "n")                            # r4: the new one is big
    a.h(cmpi(4, 0))
    a.b("eq", "yes")
    is_big(a, 3, 5, "o")                            # r5: the replaced one is big
    a.h(adds3(1, 1, 4))                             # bigs + 1 - replaced
    a.h(0x1A00 | 5 << 6 | 1 << 3 | 1)               # subs r1, r1, r5
    a.h(cmpi(1, MAX_BIG))
    a.b("hi", "no")
    a.b("al", "yes")
    # move/paste (0x2811de44): r6 = the target DSP struct, r5 = 0 when the target position is
    # empty. Its frame (push {r4-r8, lr}; sub sp, #8) is at sp + FRAME: its caller's return
    # address at +28 tells where the new block's descriptor (byte 0: its type) was saved:
    # 0x28125a2c passed it in r8 (saved at +24), 0x28125c80 in r6 (saved at +16).
    a.label("move")
    a.h(ldr_sp(0, FRAME + 28))
    a.lit(7, "c1_ret")
    a.h(cmpr(0, 7))
    a.b("eq", "m_c1")
    a.lit(7, "c2_ret")
    a.h(cmpr(0, 7))
    a.b("eq", "m_c2")
    a.h(movs(4, 0))                                 # another caller: the block is not known
    a.b("al", "m_rules")
    a.label("m_c1")
    a.h(ldr_sp(4, FRAME + 24))
    a.b("al", "m_rules")
    a.label("m_c2")
    a.h(ldr_sp(4, FRAME + 16))
    a.label("m_rules")
    # a block that already lives in the target DSP's struct moves within it: no count changes
    a.h(cmpi(4, 0))
    a.b("eq", "m_cnt")
    a.h(cmpr(4, 6))
    a.b("lo", "m_cnt")
    a.lit(7, "kb424")
    a.h(adds3(7, 6, 7))
    a.h(cmpr(4, 7))
    a.b("lo", "yes")
    a.label("m_cnt")
    a.h(cmpi(5, 0))
    a.b("ne", "yes")                                # onto a block: counts unchanged
    a.h(mov(0, 6))
    a.bl("count")
    a.h(cmpi(0, MAX_BLOCKS))
    a.b("hs", "no")
    a.h(cmpi(4, 0))
    a.b("eq", "yes")
    a.h(ldrb_imm(2, 4, 0))                          # the new block's type
    is_big(a, 2, 3, "m")
    a.h(cmpi(3, 0))
    a.b("eq", "yes")
    a.h(cmpi(1, MAX_BIG))
    a.b("hs", "no")
    a.b("al", "yes")
    # ---- count(r0 = DSP struct) -> r0 = blocks, r1 = big-slot blocks (r2, r3 clobbered)
    a.label("count")
    a.h(PUSH_R4_R7_LR)
    a.lit(4, "kac4")
    a.h(ldrb_reg(4, 0, 4))                          # n
    a.h(addsi3(5, 4, 3))                            # n + 3 records
    a.lit(6, "kaf0")
    a.h(adds3(6, 0, 6))                             # the first record
    a.h(movs(2, 0))
    a.h(movs(3, 0))
    a.h(movs(7, 0))
    a.label("c_loop")
    a.h(cmpr(7, 5))
    a.b("hs", "c_done")
    a.h(cmpr(7, 4))
    a.b("ne", "c_rec")
    a.lit(6, "k8c54")                               # past the n records: the 3 more
    a.h(adds3(6, 0, 6))
    a.label("c_rec")
    a.h(ldr_imm(1, 6, 0x24))
    a.h(lsls(1, 1, 31))
    a.b("pl", "c_next")                             # not in use
    a.h(mov(1, 6))
    a.h(addsi(1, 0x28))
    a.h(ldrb_imm(1, 1, 0))                          # its type
    a.h(cmpi(1, 0))
    a.b("eq", "c_next")
    a.h(cmpi(1, 0x21))
    a.b("hi", "c_next")
    a.h(addsi(2, 1))                                # a block
    a.h(cmpi(1, 0x21))
    a.b("eq", "c_big")
    a.h(subsi(1, 0x10))
    a.h(cmpi(1, 2))
    a.b("hi", "c_next")
    a.label("c_big")
    a.h(addsi(3, 1))
    a.label("c_next")
    a.lit(1, "k9f4")
    a.h(adds3(6, 6, 1))
    a.h(addsi(7, 1))
    a.b("al", "c_loop")
    a.label("c_done")
    a.h(addsi3(0, 2, 0))
    a.h(addsi3(1, 3, 0))
    a.h(POP_R4_R7_PC)
    a.align4()
    for name, v in (("k9000", 9000), ("avail_ret", AVAIL_RET), ("move_ret", MOVE_RET), ("kac4", 0xAC4),
                    ("kaf0", 0xAF0), ("k8c54", 0x8C54), ("k9f4", 0x9F4), ("c1_ret", C1_RET), ("c2_ret", C2_RET),
                    ("kb424", DSP_STRUCT)):
        a.word(name, v)
    return a


def tramp_bytes():
    """ldr.w pc, [pc, #0]; .word HOOK | 1 (pc base = 0x28135074, the word itself)."""
    return struct.pack("<HHI", 0xF8DF, 0xF000, CAVE | 1)


def show(code, base):
    import capstone                     # (only for the listing; the build itself does not need it)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
    md.skipdata = True
    for ins in md.disasm(code, base):
        print(f"{ins.address:#x}: {ins.mnemonic:8s} {ins.op_str}")


def main():
    a = build()
    code = a.assemble()
    print(f"HOOK at {CAVE:#x}, {len(code)} bytes; labels: " +
          ", ".join(f"{k} {v:#x}" for k, v in a.labels.items() if k in ("hook", "avail", "move", "count")))
    show(code, CAVE)
    print(f"\npatch at {TRAMP:#x}:")
    show(tramp_bytes(), TRAMP)
    if "--bytes" in sys.argv:
        print(code.hex(), tramp_bytes().hex())


if __name__ == "__main__":
    main()
