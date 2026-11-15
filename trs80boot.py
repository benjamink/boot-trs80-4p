#!/usr/bin/env python3
"""trs80boot -- serial boot server for the TRS-80 Model 4P (Linux, no dependencies).

The 4P has a serial loader in ROM (right-shift + reset). It accepts a TRSDOS
Load Module Format stream at 19200 baud, loads it into RAM and jumps to the
entry point. This script sends one: a built-in test program, an Intel HEX
file, or an existing /CMD file. Afterwards it can act as a dumb terminal.

  trs80boot.py --test                  # on-screen "hello" proof-of-life
  trs80boot.py prog.hex                # Intel HEX (entry from type-03 record)
  trs80boot.py prog.cmd                # already load-module format, sent as-is
  trs80boot.py --test --terminal       # keep the link open afterwards
Options: -p /dev/ttyUSB0   -b 19200   --entry 0x6000 (override entry point)

Handshake: send 0x55 until the ROM answers "Found Baud Rate", send 0xFF, ROM
answers "Loading ", then the load module follows. Serial format is 8 data bits, ODD parity (error B/C/D = parity/framing/both).
Protocol per Douglas Beattie Jr.'s SBOOT4 (hytherion.com/beattidp/comput/trs80.htm).
"""
import argparse, os, select, sys, termios, time, tty

from trs80.lmf import build_lmf, parse_hex
from trs80.serialio import (BAUDS, FORMATS, LoaderNotReady, handshake, open_port,
                            read_all, set_format)


# ---------- built-in test program (hand-assembled Z80, loaded at 6000h) ----
class Asm:
    """Tiny Z80 byte emitter with labels (just what the test program needs)."""
    def __init__(self, org):
        self.org, self.b, self.lab, self.fix = org, bytearray(), {}, []
    def label(self, n): self.lab[n] = self.org + len(self.b)
    def emit(self, *x): self.b += bytes(x)
    def abs16(self, op, n):          # opcode(s) followed by 16-bit label address
        self.b += bytes(op); self.fix.append((len(self.b), n, "a")); self.b += b"\0\0"
    def rel8(self, op, n):           # opcode followed by relative displacement to label
        self.b += bytes([op]); self.fix.append((len(self.b), n, "r")); self.b += b"\0"
    def data(self, n, d): self.label(n); self.b += d
    def done(self):
        for off, n, k in self.fix:
            t = self.lab[n]
            if k == "a":
                self.b[off], self.b[off + 1] = t & 255, t >> 8
            else:
                d = t - (self.org + off + 1)
                assert -128 <= d <= 127, n
                self.b[off] = d & 255
        return {self.org: bytes(self.b)}


def test_program():
    """Shows text on screen under BOTH possible memory maps (F800h = Model 4 map,
    3C00h = Model III map) and endlessly sends it back out the RS-232 UART (port EBh)."""
    A = Asm(0x6000)
    msgs = [b"TRS-80 MODEL 4P: SERIAL BOOT OK", b"Hello from Linux over RS-232!"]
    A.emit(0xF3)                                              # DI
    A.emit(0x31, 0x00, 0x70)                                  # LD SP,7000h
    A.emit(0x21, 0x00, 0xF8, 0x11, 0x01, 0xF8, 0x01, 0x7F, 0x07, 0x36, 0x20, 0xED, 0xB0)  # clear F800
    A.emit(0x21, 0x00, 0x3C, 0x11, 0x01, 0x3C, 0x01, 0xFF, 0x03, 0x36, 0x20, 0xED, 0xB0)  # clear 3C00
    for i, m in enumerate(msgs):
        for base, cols in ((0xF800, 80), (0x3C00, 64)):
            pos = base + cols * (6 + 2 * i) + (cols - len(m)) // 2
            A.abs16([0x21], f"m{i}")                          # LD HL,msg
            A.emit(0x11, pos & 255, pos >> 8)                 # LD DE,screen pos
            A.abs16([0xCD], "puts")                           # CALL puts
    A.label("again")
    A.abs16([0x21], "smsg")                                   # LD HL,smsg
    A.label("snd")
    A.emit(0x7E, 0xB7)                                        # LD A,(HL); OR A
    A.rel8(0x28, "pause")                                     # JR Z,pause
    A.emit(0xD3, 0xEB)                                        # OUT (EBh),A   (UART data)
    A.abs16([0xCD], "dly")                                    # CALL dly
    A.emit(0x23)                                              # INC HL
    A.rel8(0x18, "snd")                                       # JR snd
    A.label("pause")
    A.emit(0x06, 0x40)                                        # LD B,40h
    A.label("pl")
    A.abs16([0xCD], "dly")
    A.rel8(0x10, "pl")                                        # DJNZ pl
    A.rel8(0x18, "again")
    A.label("dly")                                            # ~13 ms @ 4 MHz, preserves BC
    A.emit(0xC5, 0x01, 0x00, 0x08)                            # PUSH BC; LD BC,0800h
    A.label("d1")
    A.emit(0x0B, 0x78, 0xB1)                                  # DEC BC; LD A,B; OR C
    A.rel8(0x20, "d1")                                        # JR NZ,d1
    A.emit(0xC1, 0xC9)                                        # POP BC; RET
    A.label("puts")
    A.emit(0x7E, 0xB7, 0xC8, 0x12, 0x23, 0x13)                # LD A,(HL); OR A; RET Z; LD (DE),A; INC HL; INC DE
    A.rel8(0x18, "puts")
    for i, m in enumerate(msgs):
        A.data(f"m{i}", m + b"\x00")
    A.data("smsg", b"4P RUNNING: HELLO FROM THE TRS-80\r\n\x00")
    return A.done(), 0x6000


def send(fd, blob, byte_delay=0.0):
    t0 = time.time()
    step = 1 if byte_delay else 16
    for i in range(0, len(blob), step):
        os.write(fd, blob[i:i + step])
        termios.tcdrain(fd)
        if byte_delay:
            time.sleep(byte_delay)
        print(f"\rsent {min(i + step, len(blob))}/{len(blob)} bytes", end="", flush=True)
    print(f"  ({time.time() - t0:.1f}s)")
    reply = read_all(fd, 1.0)
    if reply:
        print("4P says:", reply.decode("latin-1").strip() or reply.hex(" "))


def terminal(fd):
    print("-- terminal mode: TRS-80 output shown here; Ctrl-] to quit --")
    old = termios.tcgetattr(sys.stdin)
    tty.setraw(sys.stdin)
    try:
        while True:
            r, _, _ = select.select([fd, sys.stdin], [], [])
            if fd in r:
                sys.stdout.buffer.write(os.read(fd, 256).replace(b"\r", b"\r\n"))
                sys.stdout.flush()
            if sys.stdin in r:
                c = os.read(sys.stdin.fileno(), 32)
                if b"\x1d" in c:
                    break
                os.write(fd, c.replace(b"\n", b"\r"))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="Intel .hex or load-module /CMD file")
    ap.add_argument("--test", action="store_true", help="send built-in on-screen test program")
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("-b", "--baud", type=int, default=19200, choices=BAUDS)
    ap.add_argument("--entry", type=lambda x: int(x, 0), help="override entry point")
    ap.add_argument("--format", choices=FORMATS, help="serial format (default: auto-detect)")
    ap.add_argument("--block", type=int, default=16, help="data bytes per load-module record (default 16, as SBOOT4)")
    ap.add_argument("--byte-delay", type=float, default=0.0, help="seconds to pause between bytes (try 0.002 if loads fail)")
    ap.add_argument("--terminal", action="store_true", help="act as a terminal after sending")
    ap.add_argument("-y", "--yes", action="store_true", help="don't wait for Enter before sending")
    a = ap.parse_args()
    if bool(a.file) == a.test:
        ap.error("give either a file or --test")

    if a.test:
        segs, entry = test_program()
        blob = build_lmf(segs, a.entry or entry, a.block)
    elif a.file.lower().endswith((".hex", ".ihx")):
        segs, entry = parse_hex(a.file)
        entry = a.entry if a.entry is not None else entry
        if entry is None:
            entry = min(segs)
            print(f"note: no entry record in HEX; using lowest address {entry:#06x}")
        blob = build_lmf(segs, entry, a.block)
    else:
        blob = open(a.file, "rb").read()               # assume already a load module
    print(f"{len(blob)} bytes of load module ready")

    fd = open_port(a.port, a.baud)
    if not a.yes:
        input("On the 4P: hold RIGHT SHIFT, press RESET, keep holding until 'Not Ready'/'Ready'\n"
              "appears, then press Enter here... ")
    fmts = [a.format] if a.format else list(FORMATS)
    try:
        fmt = handshake(fd, a.baud, fmts)
    except LoaderNotReady as e:
        raise SystemExit(str(e))
    print(f"handshake OK with {fmt}")
    if "O" not in fmt:
        print("note: handshake only passed in 8N1; switching to 8O1 (odd parity) for the file")
        fmt = "8O1"
    set_format(fd, a.baud, fmt)
    send(fd, blob, a.byte_delay)
    print("done. The program should now be running on the 4P.")
    if a.terminal:
        terminal(fd)


if __name__ == "__main__":
    main()
