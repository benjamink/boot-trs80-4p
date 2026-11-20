#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Turn an Intel HEX file into the load module the 4P's ROM serial loader accepts.

  tools/make_loader_cmd.py build/nioboot.hex build/nioboot.cmd [--entry 0x5000]

The output is byte-identical to what `trs80boot.py FILE.hex --entry 0x5000` sends after the handshake, so
firmware (fujinet-nio's TRS-80 loader sender) can stream it as-is without an Intel HEX parser.
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from trs80.lmf import build_lmf, parse_hex  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hex")
    ap.add_argument("out")
    ap.add_argument("--entry", type=lambda x: int(x, 0), default=0x5000, help="entry point (default 0x5000)")
    ap.add_argument("--block", type=int, default=16, help="data bytes per record (default 16, as trs80boot.py)")
    a = ap.parse_args()
    segs, _ = parse_hex(a.hex)
    blob = build_lmf(segs, a.entry, a.block)
    with open(a.out, "wb") as f:
        f.write(blob)
    print(f"{a.out}: {len(blob)} bytes, entry {a.entry:#06x}")


if __name__ == "__main__":
    main()
