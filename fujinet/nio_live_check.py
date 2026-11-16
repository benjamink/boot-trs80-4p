#!/usr/bin/env python3
"""Run fujinet/z80/nioclient.asm in the Z80 interpreter against a REAL fujinet-nio over a serial port / pty.

  fujinet/nio_live_check.py /path/to/pty --image fujinet-data/images/ls631.img [--write-test]

Needs a fujinet-nio RS-232 build serving the image (see docs/superpowers/specs/*fujinet-nio-research-findings.md).
Mounts nothing itself: mount slot 1 first (e.g. ./scripts/fujinet disk mount --slot 1 --type raw --sector-size 256 host:/images/x.img).
"""
import argparse, os, re, select, sys, termios, tty

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.z80emu import Z80, load_hex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PB, BUF = 0x9F00, 0xC000
ENTRY = dict(info=0x8006, read=0x8009, write=0x800C)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--image", required=True, help="the same image NIO serves, to compare against")
    ap.add_argument("--slot", type=int, default=1)
    ap.add_argument("--write-test", action="store_true", help="also write a pattern to the LAST sector and restore it")
    a = ap.parse_args()
    img = open(a.image, "rb").read()
    fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    cpu = Z80()
    load_hex(cpu, os.path.join(ROOT, "build", "nioclient.hex"))
    pending = bytearray()

    def io_in(port):
        if port == 0xEA:
            if not pending and select.select([fd], [], [], 0)[0]:
                pending.extend(os.read(fd, 4096))
            return 0x80 if pending else 0
        if port == 0xEB:
            return pending.pop(0)
        return 0xFF

    def io_out(port, val):
        if port == 0xEB:
            os.write(fd, bytes([val]))
    cpu.io_in, cpu.io_out = io_in, io_out

    def call(name, lba=0, slot=a.slot, buf=BUF):
        cpu.mem[PB] = slot
        cpu.mem[PB + 1:PB + 5] = lba.to_bytes(4, "little")
        cpu.mem[PB + 5:PB + 7] = buf.to_bytes(2, "little")
        cpu.sp = 0x7000
        cpu.run_call(ENTRY[name], max_steps=200_000_000)
        return cpu.mem[PB + 8], cpu.mem[PB + 7], cpu.mem[PB + 11]

    err, st, de = call("info")
    size = cpu.mem[PB + 13] | cpu.mem[PB + 14] << 8
    count = int.from_bytes(cpu.mem[PB + 15:PB + 19], "little")
    print(f"info: error={err} sector_size={size} sector_count={count}")
    bad = 0
    n = count
    for lba in sorted({0, 1, 2, 19, 20, 21, n // 2, n - 2, n - 1}):
        err, st, de = call("read", lba)
        ok = err == 0 and bytes(cpu.mem[BUF:BUF + 256]) == img[lba * 256:(lba + 1) * 256]
        bad += not ok
        print(f"read lba {lba}: {'ok' if ok else f'FAIL error={err} status={st} disk_error={de}'}")
    err, st, de = call("read", n)
    print(f"read past the end: error={err} status={st} disk_error={de} (expect 6, 2, 12)")
    if a.write_test:
        last = n - 1
        saved = bytes(img[last * 256:(last + 1) * 256])
        pattern = bytes([0xC0, 0xDB, 0x00, 0xFF] * 64)
        cpu.mem[BUF:BUF + 256] = pattern
        e1 = call("write", last)[0]
        e2 = call("read", last, buf=BUF + 0x400)[0]
        same = bytes(cpu.mem[BUF + 0x400:BUF + 0x500]) == pattern
        cpu.mem[BUF + 0x800:BUF + 0x900] = saved
        e3 = call("write", last, buf=BUF + 0x800)[0]
        print(f"write test on lba {last}: write={e1} read={e2} identical={same} restore={e3}")
        bad += (e1 or e2 or e3 or not same)
    print("RESULT:", "all good" if not bad else f"{bad} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
