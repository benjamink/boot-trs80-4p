#!/usr/bin/env python3
"""Run one of the LS-DOS FujiNet commands (FMOUNT, FUMOUNT, FDRIVE ...) in the Z80 interpreter against a REAL fujinet-nio.

  fujinet/cli_live.py /path/to/pty "FMOUNT :0 host:/images/ls631.img ss=256"

The text the program would show on the 4P is printed; the exit code is the program's return code.
Needs a fujinet-nio RS-232 build on the other end (see docs/superpowers/specs/*fujinet-nio-research-findings.md).
"""
import os, select, sys, tty

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.fakedos import DosExit, FakeDos  # noqa: E402
from tests.z80emu import Z80, load_hex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(port, command):
    name, _, args = command.partition(" ")
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    cpu = Z80()
    load_hex(cpu, os.path.join(ROOT, "build", name.lower() + ".hex"))
    pending = bytearray()

    def io_in(p):
        if p == 0xEA:
            if not pending and select.select([fd], [], [], 0)[0]:
                pending.extend(os.read(fd, 4096))
            return 0x80 if pending else 0
        return pending.pop(0) if p == 0xEB else 0xFF

    def io_out(p, val):
        if p == 0xEB:
            os.write(fd, bytes([val]))
    cpu.io_in, cpu.io_out = io_in, io_out
    dos = FakeDos(cpu)
    cpu.mem[0x4800:0x4800 + len(args) + 1] = args.encode() + b"\r"
    cpu.set_rp(4, 5, 0x4800)
    cpu.sp, cpu.pc = 0x7000, 0x3000
    rc = None
    try:
        for _ in range(400_000_000):
            cpu.step()
    except DosExit:
        rc = cpu.hl()
    print("\n".join(dos.messages))
    return rc


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
