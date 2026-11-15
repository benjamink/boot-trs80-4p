#!/usr/bin/env python3
"""trs80mon -- talk to the resident monitor on a TRS-80 Model 4P.

  trs80mon.py boot                 # ROM handshake, send build/mon.hex (run `make` first), ping
  trs80mon.py ping
  trs80mon.py peek ADDR N          # hex dump N bytes
  trs80mon.py poke ADDR HEXBYTES   # e.g. poke 0x8000 3E42C9
  trs80mon.py exec ADDR            # CALL ADDR, print registers on return
  trs80mon.py load FILE [--run]    # upload .hex or load-module (/CMD) file; --run starts its entry
Options: -p /dev/ttyUSB0
`boot` needs the 4P in ROM-loader mode: hold RIGHT-SHIFT, press RESET, keep holding until "Ready".
"""
import argparse, os, sys

from trs80 import frames, lmf
from trs80.monitor import Monitor, MonitorError
from trs80.serialio import (FORMATS, LoaderNotReady, SerialTransport, handshake, open_port,
                            read_all, set_format)

HERE = os.path.dirname(os.path.abspath(__file__))


def num(s):
    return int(s, 0)


def connect(port):
    fd = open_port(port, 19200)
    mon = Monitor(SerialTransport(fd))
    return fd, mon


def cmd_boot(a):
    path = os.path.join(HERE, "build", "mon.hex")
    if not os.path.exists(path):
        sys.exit("build/mon.hex not found: run `make` first")
    segs, entry = lmf.parse_hex(path)
    blob = lmf.build_lmf(segs, entry if entry is not None else min(segs), 16)
    fd = open_port(a.port, 19200)
    try:
        fmt = handshake(fd, 19200, list(FORMATS), timeout=a.timeout)
    except LoaderNotReady as e:
        sys.exit(str(e))
    set_format(fd, 19200, fmt if "O" in fmt else "8O1")
    import trs80boot
    trs80boot.send(fd, blob)
    mon = Monitor(SerialTransport(fd))
    read_all(fd, 0.2)
    mon.sync()
    print("monitor is running; ping ok")


def cmd_ping(a):
    _, mon = connect(a.port)
    mon.sync()
    print("ok")


def cmd_peek(a):
    _, mon = connect(a.port)
    mon.sync()
    data = mon.read_mem(a.addr, a.n)
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        print(f"{a.addr + i:04X}  {row.hex(' '):<47}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in row)}")


def cmd_poke(a):
    _, mon = connect(a.port)
    mon.sync()
    mon.write_mem(a.addr, bytes.fromhex(a.hexbytes))
    print("ok")


def cmd_exec(a):
    _, mon = connect(a.port)
    mon.sync()
    print(" ".join(f"{k}={v:02X}" for k, v in mon.exec(a.addr).items()))


def cmd_load(a):
    if a.file.lower().endswith((".hex", ".ihx")):
        segs, entry = lmf.parse_hex(a.file)
    else:
        with open(a.file, "rb") as f:
            segs, entry = lmf.parse_lmf(f.read())
    if entry is None:
        entry = min(segs)
    _, mon = connect(a.port)
    mon.sync()
    for addr, data in sorted(segs.items()):
        mon.write_mem(addr, data)
        print(f"loaded {len(data)} bytes at {addr:04X}")
    if a.run:
        mon.t.write(frames.encode_request(frames.CMD_EXEC, mon.seq, bytes([entry & 255, entry >> 8])))
        print(f"started at {entry:04X} (not waiting for it to return)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("boot"); b.add_argument("--timeout", type=float, default=None); b.set_defaults(fn=cmd_boot)
    sub.add_parser("ping").set_defaults(fn=cmd_ping)
    p = sub.add_parser("peek"); p.add_argument("addr", type=num); p.add_argument("n", type=num); p.set_defaults(fn=cmd_peek)
    p = sub.add_parser("poke"); p.add_argument("addr", type=num); p.add_argument("hexbytes"); p.set_defaults(fn=cmd_poke)
    p = sub.add_parser("exec"); p.add_argument("addr", type=num); p.set_defaults(fn=cmd_exec)
    p = sub.add_parser("load"); p.add_argument("file"); p.add_argument("--run", action="store_true"); p.set_defaults(fn=cmd_load)
    a = ap.parse_args()
    try:
        a.fn(a)
    except MonitorError as e:
        sys.exit(f"monitor error: {e}")


if __name__ == "__main__":
    main()
