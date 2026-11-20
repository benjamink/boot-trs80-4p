#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Convert a single-sided double-density JV3 disk image to a DMK image that writedisk.py can put on a real floppy.

  tools/jv3_to_dmk.py Spro.dsk build/spro.dmk
  ./writedisk.py --image build/spro.dmk --drive 0 --dry-run

Every sector keeps its track, id and position on the track, and the data address mark from the JV3 flags (a "deleted"
mark, as LS-DOS directory sectors have, is kept). A sector the JV3 marks as a CRC error is written with a good CRC (the
FDC's Write Sector cannot make a bad one); the tool says so. Only MFM, 256-byte, single-sided images are supported.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80 import jv3  # noqa: E402
from trs80.dmk import crc16  # noqa: E402

TRACK_LEN = 6400
_DAM = {0: 0xFB, 1: 0xF8}      # JV3 double-density data address marks (flag bits 6-5)


def _track(sectors):
    """One DMK track record: 128-byte IDAM pointer table + MFM track bytes. sectors: (cyl, id, dam, data) in track order."""
    body, ptrs = bytearray(b"\x4E" * 32), []
    for cyl, num, dam, data in sectors:
        body += b"\x00" * 12 + b"\xA1\xA1\xA1"
        ptrs.append((128 + len(body)) | 0x8000)
        idam = bytes([0xFE, cyl, 0, num, 1])
        body += idam + crc16(b"\xA1\xA1\xA1" + idam).to_bytes(2, "big") + b"\x4E" * 22
        body += b"\x00" * 12 + b"\xA1\xA1\xA1" + bytes([dam]) + data
        body += crc16(b"\xA1\xA1\xA1" + bytes([dam]) + data).to_bytes(2, "big") + b"\x4E" * 24
    if 128 + len(body) > TRACK_LEN:
        raise ValueError(f"track of {len(sectors)} sectors does not fit in {TRACK_LEN} bytes")
    table = bytearray(128)
    for i, p in enumerate(ptrs):
        struct.pack_into("<H", table, 2 * i, p)
    return bytes(table) + bytes(body) + b"\x4E" * (TRACK_LEN - 128 - len(body))


def jv3_to_dmk(data):
    """Returns (dmk bytes, number of sectors the JV3 flagged as CRC errors)."""
    ents = jv3._entries(data)
    by_track, bad = {}, 0
    for i, (t, s, f) in enumerate(ents):
        if f & 0x10:
            raise ValueError("double-sided JV3 images are not supported")
        if f & 0x03:
            raise ValueError(f"track {t} sector {s}: only 256-byte sectors are supported")
        if not f & 0x80:
            raise ValueError(f"track {t} sector {s}: single density is not supported")
        bad += bool(f & 0x08)
        src = jv3.DATA_START + i * 256
        if src + 256 > len(data):
            raise ValueError("truncated JV3 image")
        by_track.setdefault(t, []).append((t, s, _DAM[1 if (f >> 5) & 3 else 0], data[src:src + 256]))
    tracks = max(by_track) + 1
    header = bytes([0, tracks]) + struct.pack("<H", TRACK_LEN) + bytes([0x10]) + bytes(11)   # 0x10 = single sided
    recs = [_track(by_track[t]) if t in by_track else b"\x4E" * TRACK_LEN for t in range(tracks)]
    return header + b"".join(recs), bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jv3")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    dmk, bad = jv3_to_dmk(open(a.jv3, "rb").read())
    open(a.out, "wb").write(dmk)
    print(f"{a.out}: {len(dmk)} bytes")
    if bad:
        print(f"note: {bad} sector(s) were flagged as CRC errors in the JV3; they are written with good CRCs")


if __name__ == "__main__":
    main()
