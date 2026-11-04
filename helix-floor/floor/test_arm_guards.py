"""Run arm_guards' HOOK in a small Thumb interpreter (capstone decode, the instructions it
uses only) against made-up DSP structs: block cap, big-slot cap, move/paste, budget."""
import struct
import sys

import capstone
from capstone import arm

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arm_guards as g  # noqa: E402

RET_AV, RET_MV = g.AVAIL_RET, g.MOVE_RET


class Cpu:
    def __init__(self, code, base):
        self.mem = {}
        for i, b in enumerate(code):
            self.mem[base + i] = b
        self.r = [0] * 16
        self.n = self.z = self.c = self.v = False
        self.md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
        self.md.detail = True

    def w8(self, a, v): self.mem[a] = v & 0xFF
    def w32(self, a, v):
        for k in range(4): self.mem[a + k] = (v >> 8 * k) & 0xFF
    def r8(self, a): return self.mem.get(a, 0)
    def r32(self, a): return sum(self.mem.get(a + k, 0) << 8 * k for k in range(4))

    def flags_sub(self, a, b):
        res = (a - b) & 0xFFFFFFFF
        self.n, self.z, self.c = bool(res >> 31), res == 0, a >= b
        self.v = bool(((a ^ b) & (a ^ res)) >> 31)
        return res

    def flags_add(self, a, b):
        full = a + b
        res = full & 0xFFFFFFFF
        self.n, self.z, self.c = bool(res >> 31), res == 0, full > 0xFFFFFFFF
        self.v = bool((~(a ^ b) & (a ^ res)) >> 31)
        return res

    def cond(self, cc):
        return {arm.ARM_CC_EQ: self.z, arm.ARM_CC_NE: not self.z, arm.ARM_CC_HS: self.c,
                arm.ARM_CC_LO: not self.c, arm.ARM_CC_HI: self.c and not self.z, arm.ARM_CC_PL: not self.n,
                arm.ARM_CC_AL: True, arm.ARM_CC_INVALID: True}[cc]

    def val(self, op):
        return op.imm & 0xFFFFFFFF if op.type == arm.ARM_OP_IMM else self.r[self.reg(op.reg)]

    def reg(self, cs):
        names = {arm.ARM_REG_R0 + i: i for i in range(13)}
        names.update({arm.ARM_REG_SB: 9, arm.ARM_REG_SL: 10, arm.ARM_REG_FP: 11, arm.ARM_REG_IP: 12,
                      arm.ARM_REG_SP: 13, arm.ARM_REG_LR: 14, arm.ARM_REG_PC: 15})
        return names[cs]

    def run(self, pc, limit=5000):
        self.r[15] = pc
        for _ in range(limit):
            pc = self.r[15] & ~1
            code = bytes(self.r8(pc + k) for k in range(4))
            ins = next(self.md.disasm(code, pc, 1))
            nxt = pc + ins.size
            m, ops = ins.mnemonic, ins.operands
            r = self.reg
            if m == "push":
                for op in reversed(ops):
                    self.r[13] -= 4
                    self.w32(self.r[13], self.r[r(op.reg)])
            elif m == "pop":
                for op in ops:
                    self.r[r(op.reg)] = self.r32(self.r[13])
                    self.r[13] += 4
                if any(r(op.reg) == 15 for op in ops):
                    nxt = self.r[15]
                    if nxt in (RET_AV, RET_MV):
                        return self.r[0]
            elif m == "bx":
                nxt = self.r[r(ops[0].reg)]
                if nxt in (RET_AV, RET_MV):
                    return self.r[0]
            elif m in ("ldr", "ldr.w") and ops[1].type == arm.ARM_OP_MEM:
                base = ((pc + 4) & ~3) if ops[1].mem.base == arm.ARM_REG_PC else self.r[r(ops[1].mem.base)]
                v = self.r32(base + ops[1].mem.disp)
                if r(ops[0].reg) == 15:
                    self.jumped = v
                    return v
                self.r[r(ops[0].reg)] = v
            elif m == "str" and ops[1].type == arm.ARM_OP_MEM:
                self.w32(self.r[r(ops[1].mem.base)] + ops[1].mem.disp, self.r[r(ops[0].reg)])
            elif m == "ldrb":
                mm = ops[1].mem
                a = self.r[r(mm.base)] + (self.r[r(mm.index)] if mm.index else mm.disp)
                self.r[r(ops[0].reg)] = self.r8(a)
            elif m in ("cmp", "cmp.w"):
                self.flags_sub(self.r[r(ops[0].reg)], self.val(ops[1]))
            elif m == "movs":
                v = self.val(ops[1])
                self.r[r(ops[0].reg)] = v
                self.n, self.z = bool(v >> 31), v == 0
            elif m == "mov":
                self.r[r(ops[0].reg)] = self.val(ops[1])
            elif m == "adds":
                a_, b_ = (self.r[r(ops[0].reg)], self.val(ops[1])) if len(ops) == 2 else (self.val(ops[1]), self.val(ops[2]))
                self.r[r(ops[0].reg)] = self.flags_add(a_, b_)
            elif m == "subs":
                a_, b_ = (self.r[r(ops[0].reg)], self.val(ops[1])) if len(ops) == 2 else (self.val(ops[1]), self.val(ops[2]))
                self.r[r(ops[0].reg)] = self.flags_sub(a_, b_)
            elif m == "add":                      # add rd, sp, #imm
                self.r[r(ops[0].reg)] = self.val(ops[1]) + self.val(ops[2])
            elif m == "lsls":
                v = self.val(ops[1]); s = ops[2].imm
                self.c = bool((v >> (32 - s)) & 1)
                v = (v << s) & 0xFFFFFFFF
                self.r[r(ops[0].reg)] = v
                self.n, self.z = bool(v >> 31), v == 0
            elif m == "bl":
                self.r[14] = nxt | 1
                nxt = ops[0].imm
            elif m.startswith("b") and ops and ops[0].type == arm.ARM_OP_IMM:
                if self.cond(ins.cc):
                    nxt = ops[0].imm
            else:
                raise RuntimeError(f"unhandled {m} {ins.op_str} at {pc:#x}")
            self.r[15] = nxt
        raise RuntimeError("no return")


DSP, SP = 0x20100000, 0x20200000
ENTRY = 0x20300000


def dsp_with(blocks, n=16):
    """blocks: list of (record index, type); records beyond n go to the 3 extra ones."""
    mem = {}
    for k, t in blocks:
        rec = DSP + (0xAF0 + k * 0x9F4 if k < n else 0x8C54 + (k - n) * 0x9F4)
        mem[rec + 0x24] = 1
        mem[rec + 0x28] = t
    return mem


def call(kind, blocks, new_t=0x01, cur_t=0, cost=5000, empty_target=True, n=16, caller=1, inside=False):
    code = g.build().assemble()
    cpu = Cpu(code, g.CAVE)
    cpu.w8(DSP + 0xAC4, n)
    for a, v in dsp_with(blocks, n).items():
        cpu.w8(a, v)
    cpu.r[13] = SP
    cpu.r[1] = cost
    if kind == "avail":
        cpu.r[11] = DSP
        cpu.w32(SP + 0x38, ENTRY)
        cpu.w32(ENTRY, new_t)
        cpu.w8(SP + 0x60, cur_t)
        cpu.r[14] = RET_AV
    else:
        cpu.r[6] = DSP
        cpu.r[5] = 0 if empty_target else 1234
        cpu.r[14] = RET_MV
        desc = DSP + 0x1000 if inside else ENTRY          # inside the DSP struct: a move within it
        cpu.w8(desc, new_t)
        ret = {1: g.C1_RET, 2: g.C2_RET, 0: 0x28000001}[caller]
        cpu.w32(SP + 28, ret)                               # 0x2811de44's frame
        cpu.w32(SP + (24 if caller == 1 else 16), desc)
    keep = list(cpu.r[4:12])
    res = cpu.run(g.CAVE | 1)
    assert cpu.r[13] == SP, "stack not balanced"
    assert cpu.r[4:12] == keep, "callee-saved registers changed"
    return res


def main():
    FX, AMP, AMPCAB, LDUAL, NDUAL, IR = 0x01, 0x11, 0x21, 0x10, 0x20, 0x13
    cases = [
        ("budget over 9000", call("avail", [], cost=9001), 0),
        ("budget at 9000", call("avail", [], cost=9000), 1),
        ("12 blocks + new into empty", call("avail", [(k, FX) for k in range(12)]), 1),
        ("13 blocks + new into empty", call("avail", [(k, FX) for k in range(13)]), 0),
        ("13 blocks, replace one", call("avail", [(k, FX) for k in range(13)], new_t=FX, cur_t=FX), 1),
        ("13 counted incl. extra records", call("avail", [(k, FX) for k in range(12)] + [(17, FX)]), 0),
        ("unused record ignored", call("avail", [(k, FX) for k in range(12)] + [(20, 0)]), 1),
        ("types > 0x21 ignored", call("avail", [(k, FX) for k in range(12)] + [(12, 0x30)]), 1),
        ("1 amp + 2nd amp", call("avail", [(0, AMP)], new_t=AMP), 1),
        ("2 amps + 3rd amp", call("avail", [(0, AMP), (1, AMPCAB)], new_t=AMP), 0),
        ("2 amps, swap an amp", call("avail", [(0, AMP), (1, AMP)], new_t=AMPCAB, cur_t=AMP), 1),
        ("2 amps + legacy dual cab", call("avail", [(0, AMP), (1, AMP)], new_t=LDUAL), 0),
        ("2 amps + new dual cab", call("avail", [(0, AMP), (1, AMP)], new_t=NDUAL), 1),
        ("amp + legacy dual + amp", call("avail", [(0, AMP), (1, LDUAL)], new_t=AMP), 0),
        ("2 amps + IR", call("avail", [(0, AMP), (1, AMP)], new_t=IR), 1),
        ("move into empty, 12 blocks", call("move", [(k, FX) for k in range(12)]), 1),
        ("move into empty, 13 blocks", call("move", [(k, FX) for k in range(13)]), 0),
        ("move onto a block, 13 blocks", call("move", [(k, FX) for k in range(13)], empty_target=False), 1),
        ("move over budget", call("move", [], cost=9500), 0),
        ("paste (caller 2) into empty, 13 blocks", call("move", [(k, FX) for k in range(13)], caller=2), 0),
        ("move within the DSP at 13 blocks", call("move", [(k, FX) for k in range(13)], inside=True), 1),
        ("move amp in, 1 amp there", call("move", [(0, AMP)], new_t=AMP), 1),
        ("move amp in, 2 amps there", call("move", [(0, AMP), (1, AMP)], new_t=AMP), 0),
        ("paste amp+cab, amp + legacy dual there", call("move", [(0, AMP), (1, LDUAL)], new_t=AMPCAB, caller=2), 0),
        ("move effect in, 2 amps there", call("move", [(0, AMP), (1, AMP)], new_t=FX), 1),
        ("move amp within DSP, 2 amps", call("move", [(0, AMP), (1, AMP)], new_t=AMP, inside=True), 1),
        ("move amp onto a block, 2 amps", call("move", [(0, AMP), (1, AMP)], new_t=AMP, empty_target=False), 1),
        ("unknown caller, 12 blocks, amp, 2 amps", call("move", [(0, AMP), (1, AMP)] + [(k, FX) for k in range(2, 12)],
                                                        new_t=AMP, caller=0), 1),
    ]
    bad = [(name, got, want) for name, got, want in cases if got != want]
    for name, got, want in cases:
        print(f"{'ok ' if got == want else 'BAD'} {name}: {got}")
    print("PASS" if not bad else f"FAIL {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
