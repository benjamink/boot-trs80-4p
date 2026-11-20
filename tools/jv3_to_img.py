#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Convert a JV3 disk image to the raw 256-byte-sector image fujinet-nio can serve to FMOUNT (see trs80/jv3.py).

  tools/jv3_to_img.py Spro.dsk fujinet-data/images/spro.img
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80 import jv3  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jv3")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    flat = jv3.flat_image(open(a.jv3, "rb").read())
    open(a.out, "wb").write(flat)
    print(f"{a.out}: {len(flat)} bytes, {len(flat) // 256} sectors of 256 bytes")


if __name__ == "__main__":
    main()
