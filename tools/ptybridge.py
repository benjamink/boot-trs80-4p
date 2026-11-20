#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Forward bytes between two ptys/serial ports, logging both directions as hex (to stderr or --log FILE).
   tools/ptybridge.py /dev/pts/8 /path/to/ptyB --log bridge.log"""
import argparse, os, select, sys, time, tty


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("--log")
    args = ap.parse_args(argv)
    fa, fb = (os.open(p, os.O_RDWR | os.O_NOCTTY) for p in (args.a, args.b))
    tty.setraw(fa); tty.setraw(fb)
    log = open(args.log, "w", buffering=1) if args.log else sys.stderr
    t0 = time.time()
    while True:
        r, _, _ = select.select([fa, fb], [], [])
        for f in r:
            try:
                d = os.read(f, 4096)
            except OSError:
                return
            if not d:
                return
            os.write(fb if f == fa else fa, d)
            log.write(f"{time.time() - t0:8.3f} {'4P->NIO' if f == fa else 'NIO->4P'} {len(d):3d} {d.hex(' ')}\n")


if __name__ == "__main__":
    main()
