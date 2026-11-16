"""A small Z80 interpreter covering the instructions our monitor/FDC code uses.
Test support only. Unknown opcodes raise NotImplementedError."""
from trs80 import lmf

S, Z, H, PV, N, C = 0x80, 0x40, 0x10, 0x04, 0x02, 0x01


def parity(v):
    return 0 if bin(v & 0xFF).count("1") & 1 else PV


class Z80:
    def __init__(self):
        self.mem = bytearray(65536)
        self.R = [0] * 8            # B C D E H L (HL) A
        self.F = 0
        self.iff = True             # interrupts start enabled, as the ROM loader may leave them
        self.sp = 0xFFFF
        self.pc = 0
        self.io_in = lambda port: 0xFF
        self.io_out = lambda port, val: None
        self.steps = 0

    # ---- register helpers ----
    def rp(self, hi, lo):
        return (self.R[hi] << 8) | self.R[lo]

    def set_rp(self, hi, lo, v):
        self.R[hi], self.R[lo] = (v >> 8) & 0xFF, v & 0xFF

    def hl(self): return self.rp(4, 5)

    def get_pair(self, i):          # 0 BC, 1 DE, 2 HL, 3 SP
        return [self.rp(0, 1), self.rp(2, 3), self.rp(4, 5), self.sp][i]

    def put_pair(self, i, v):
        v &= 0xFFFF
        if i == 3:
            self.sp = v
        else:
            self.set_rp(*[(0, 1), (2, 3), (4, 5)][i], v)

    def get_r(self, i):
        return self.mem[self.hl()] if i == 6 else self.R[i]

    def put_r(self, i, v):
        v &= 0xFF
        if i == 6:
            self.mem[self.hl()] = v
        else:
            self.R[i] = v

    # ---- memory / stack ----
    def fetch(self):
        v = self.mem[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch()
        return lo | (self.fetch() << 8)

    def rd16(self, a):
        return self.mem[a] | (self.mem[(a + 1) & 0xFFFF] << 8)

    def wr16(self, a, v):
        self.mem[a] = v & 0xFF
        self.mem[(a + 1) & 0xFFFF] = (v >> 8) & 0xFF

    def push(self, v):
        self.sp = (self.sp - 2) & 0xFFFF
        self.wr16(self.sp, v)

    def pop(self):
        v = self.rd16(self.sp)
        self.sp = (self.sp + 2) & 0xFFFF
        return v

    # ---- ALU ----
    def alu(self, op, b):
        a = self.R[7]
        if op in (0, 1, 2, 3, 7):                   # add adc sub sbc cp
            sub = op in (2, 3, 7)
            carry = 1 if (op in (1, 3) and self.F & C) else 0
            res = a - b - carry if sub else a + b + carry
            r = res & 0xFF
            f = (r & S) | (Z if r == 0 else 0) | (N if sub else 0)
            f |= C if (res < 0 if sub else res > 0xFF) else 0
            f |= H if ((a ^ b ^ r) & 0x10) else 0
            ov = ((a ^ b) & (a ^ r) & 0x80) if sub else (~(a ^ b) & (a ^ r) & 0x80)
            f |= PV if ov else 0
            self.F = f
            if op != 7:
                self.R[7] = r
        else:
            r = {4: a & b, 5: a ^ b, 6: a | b}[op]
            self.R[7] = r
            self.F = (r & S) | (Z if r == 0 else 0) | parity(r) | (H if op == 4 else 0)

    def inc8(self, v):
        r = (v + 1) & 0xFF
        self.F = (self.F & C) | (r & S) | (Z if r == 0 else 0) | (H if (v & 0xF) == 0xF else 0) | (PV if v == 0x7F else 0)
        return r

    def dec8(self, v):
        r = (v - 1) & 0xFF
        self.F = (self.F & C) | (r & S) | (Z if r == 0 else 0) | N | (H if (v & 0xF) == 0 else 0) | (PV if v == 0x80 else 0)
        return r

    def cond(self, cc):
        f = self.F
        return [not f & Z, bool(f & Z), not f & C, bool(f & C),
                not f & PV, bool(f & PV), not f & S, bool(f & S)][cc]

    # ---- execution ----
    def step(self):
        self.steps += 1
        op = self.fetch()
        R = self.R
        if op == 0x00:
            pass
        elif op & 0xCF == 0x01:                         # LD rr,nn
            self.put_pair((op >> 4) & 3, self.fetch16())
        elif op & 0xCF == 0x03:
            i = (op >> 4) & 3; self.put_pair(i, self.get_pair(i) + 1)
        elif op & 0xCF == 0x0B:
            i = (op >> 4) & 3; self.put_pair(i, self.get_pair(i) - 1)
        elif op & 0xCF == 0x09:                         # ADD HL,rr
            a, b = self.hl(), self.get_pair((op >> 4) & 3)
            res = a + b
            self.F = (self.F & (S | Z | PV)) | (C if res > 0xFFFF else 0)
            self.set_rp(4, 5, res)
        elif op == 0x0A: R[7] = self.mem[self.rp(0, 1)]
        elif op == 0x1A: R[7] = self.mem[self.rp(2, 3)]
        elif op == 0x02: self.mem[self.rp(0, 1)] = R[7]
        elif op == 0x12: self.mem[self.rp(2, 3)] = R[7]
        elif op == 0x22: self.wr16(self.fetch16(), self.hl())
        elif op == 0x2A: self.set_rp(4, 5, self.rd16(self.fetch16()))
        elif op == 0x32: self.mem[self.fetch16()] = R[7]
        elif op == 0x3A: R[7] = self.mem[self.fetch16()]
        elif op & 0xC7 == 0x06:
            self.put_r((op >> 3) & 7, self.fetch())
        elif op & 0xC7 == 0x04:
            i = (op >> 3) & 7; self.put_r(i, self.inc8(self.get_r(i)))
        elif op & 0xC7 == 0x05:
            i = (op >> 3) & 7; self.put_r(i, self.dec8(self.get_r(i)))
        elif op == 0x10:
            d = self.fetch(); d -= 256 if d > 127 else 0
            R[0] = (R[0] - 1) & 0xFF
            if R[0]: self.pc = (self.pc + d) & 0xFFFF
        elif op == 0x18 or (op & 0xE7 == 0x20):
            d = self.fetch(); d -= 256 if d > 127 else 0
            if op == 0x18 or self.cond((op >> 3) & 3):
                self.pc = (self.pc + d) & 0xFFFF
        elif op == 0x1F:                                # RRA
            c = R[7] & 1
            R[7] = (R[7] >> 1) | ((self.F & C) << 7)
            self.F = (self.F & (S | Z | PV)) | c
        elif op == 0x37: self.F = (self.F & ~(N | H)) | C
        elif 0x40 <= op <= 0x7F:
            if op == 0x76: raise NotImplementedError("HALT")
            self.put_r((op >> 3) & 7, self.get_r(op & 7))
        elif 0x80 <= op <= 0xBF:
            self.alu((op >> 3) & 7, self.get_r(op & 7))
        elif op & 0xC7 == 0xC6:
            self.alu((op >> 3) & 7, self.fetch())
        elif op & 0xC7 == 0xC0:
            if self.cond((op >> 3) & 7): self.pc = self.pop()
        elif op == 0xC9: self.pc = self.pop()
        elif op & 0xCF == 0xC1:
            v = self.pop(); i = (op >> 4) & 3
            if i == 3: R[7], self.F = v >> 8, v & 0xFF
            else: self.put_pair(i, v)
        elif op & 0xCF == 0xC5:
            i = (op >> 4) & 3
            self.push(((R[7] << 8) | self.F) if i == 3 else self.get_pair(i))
        elif op & 0xC7 == 0xC2:
            a = self.fetch16()
            if self.cond((op >> 3) & 7): self.pc = a
        elif op == 0xC3: self.pc = self.fetch16()
        elif op & 0xC7 == 0xC4:
            a = self.fetch16()
            if self.cond((op >> 3) & 7): self.push(self.pc); self.pc = a
        elif op == 0xCD:
            a = self.fetch16(); self.push(self.pc); self.pc = a
        elif op == 0xE9: self.pc = self.hl()
        elif op & 0xC7 == 0xC7:                         # RST n
            self.push(self.pc); self.pc = op & 0x38
        elif op == 0xF3: self.iff = False
        elif op == 0xFB: self.iff = True
        elif op == 0xD3: self.io_out(self.fetch(), R[7])
        elif op == 0xDB: R[7] = self.io_in(self.fetch())
        elif op == 0xCB:
            op2 = self.fetch()
            if op2 & 0xC0 == 0x40:                      # BIT b,r
                bit = (op2 >> 3) & 7
                z = not (self.get_r(op2 & 7) >> bit) & 1
                self.F = (self.F & C) | H | (Z if z else 0)
            else:
                raise NotImplementedError(f"CB {op2:02X} at {self.pc - 2:04X}")
        elif op == 0xED:
            op2 = self.fetch()
            if op2 & 0xCF == 0x42:                      # SBC HL,rr
                a, b = self.hl(), self.get_pair((op2 >> 4) & 3)
                res = a - b - (1 if self.F & C else 0)
                r = res & 0xFFFF
                self.F = (r >> 8 & S) | (Z if r == 0 else 0) | N | (C if res < 0 else 0)
                self.set_rp(4, 5, r)
            elif op2 == 0xB0:                           # LDIR
                while True:
                    self.mem[self.rp(2, 3)] = self.mem[self.hl()]
                    self.set_rp(2, 3, self.rp(2, 3) + 1)
                    self.set_rp(4, 5, self.hl() + 1)
                    self.set_rp(0, 1, self.rp(0, 1) - 1)
                    if self.rp(0, 1) == 0: break
                self.F &= ~(H | PV | N)
            elif op2 & 0xC7 == 0x40:                    # IN r,(C)
                v = self.io_in(R[1]); i = (op2 >> 3) & 7
                if i != 6: R[i] = v
                self.F = (self.F & C) | (v & S) | (Z if v == 0 else 0) | parity(v)
            elif op2 & 0xC7 == 0x41:                    # OUT (C),r
                i = (op2 >> 3) & 7
                self.io_out(R[1], 0 if i == 6 else R[i])
            elif op2 & 0xCF == 0x4B:                    # LD rr,(nn)
                self.put_pair((op2 >> 4) & 3, self.rd16(self.fetch16()))
            elif op2 & 0xCF == 0x43:                    # LD (nn),rr
                self.wr16(self.fetch16(), self.get_pair((op2 >> 4) & 3))
            else:
                raise NotImplementedError(f"ED {op2:02X} at {self.pc - 2:04X}")
        else:
            raise NotImplementedError(f"opcode {op:02X} at {self.pc - 1:04X}")

    def run_call(self, addr, sentinel=0xFFF0, max_steps=30_000_000):
        """CALL addr and run until it returns."""
        self.push(sentinel)
        self.pc = addr
        for _ in range(max_steps):
            if self.pc == sentinel:
                return
            self.step()
        raise RuntimeError(f"routine at {addr:04X} did not return")

    def run_until_idle(self, idle_pc, queue_empty, max_steps=20_000_000):
        """Run until the CPU is about to execute at idle_pc with nothing left to read."""
        for _ in range(max_steps):
            if self.pc == idle_pc and queue_empty():
                return
            self.step()
        raise RuntimeError("emulator did not go idle")


def load_hex(cpu, path):
    segs, _ = lmf.parse_hex(path)
    for addr, data in segs.items():
        cpu.mem[addr:addr + len(data)] = data
