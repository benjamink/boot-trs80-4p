#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Convert a DMK disk image to the raw 256-byte-sector image fujinet-nio serves to FMOUNT (LBA = cylinder * sectors per
cylinder + sector, sectors in id order, no headers).

  tools/dmk_to_img.py spro.dmk spro.img

LS-DOS / TRSDOS 6 disks only (the geometry is read from the boot sector and the GAT, as the FujiNet driver assumes).
Sectors with a bad CRC are reported and still copied. The reverse direction is tools/jv3_to_dmk.py plus writedisk.py.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80 import lsdosfs  # noqa: E402
from trs80.dmk import parse_dmk  # noqa: E402


def dmk_to_img(data):
    """Returns (raw image bytes, list of (cyl, side, sector) with a bad CRC)."""
    img = parse_dmk(data)
    bad = [(c, h, s.num) for c in range(img.tracks) for h in range(img.sides)
           for s in img.get(c, h).sectors if not (s.id_crc_ok and s.data_crc_ok)]
    sizes = {s.size for c in range(img.tracks) for h in range(img.sides) for s in img.get(c, h).sectors}
    if sizes - {256}:
        raise ValueError(f"sector sizes {sorted(sizes)}: only 256-byte sectors are supported")
    return lsdosfs.flat_image(img), bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dmk")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    with open(a.dmk, "rb") as f:
        raw, bad = dmk_to_img(f.read())
    with open(a.out, "wb") as f:
        f.write(raw)
    print(f"{a.out}: {len(raw)} bytes, {len(raw) // 256} sectors of 256 bytes")
    for c, h, s in bad:
        print(f"warning: cylinder {c} side {h} sector {s} has a CRC error in the DMK")


if __name__ == "__main__":
    main()
