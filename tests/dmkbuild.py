# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Builds synthetic DMK images for tests. Independent of trs80.dmk except for the CRC
(which test_dmk checks against the standard CCITT test vector)."""
import struct

from trs80.dmk import crc16


def make_track(sectors, mfm=True, track_len=6400, doubled=False):
    """sectors: list of dict(cyl, side, num, size_code=1, data=bytes, dam=0xFB, bad_crc=False).
    Returns one DMK track record (128-byte pointer table + track bytes)."""
    body, ptrs = bytearray(), []

    def emit(bs):
        if doubled and not mfm:
            bs = bytes(b for x in bs for b in (x, x))
        body.extend(bs)

    emit((b"\x4E" if mfm else b"\xFF") * (32 if mfm else 16))
    for s in sectors:
        code = s.get("size_code", 1)
        emit(b"\x00" * (12 if mfm else 6))
        if mfm:
            emit(b"\xA1\xA1\xA1")
        ptrs.append((128 + len(body)) | (0x8000 if mfm else 0))
        idam = bytes([0xFE, s["cyl"], s["side"], s["num"], code])
        pre = b"\xA1\xA1\xA1" if mfm else b""
        emit(idam + crc16(pre + idam).to_bytes(2, "big"))
        emit((b"\x4E" if mfm else b"\xFF") * (22 if mfm else 11))
        emit(b"\x00" * (12 if mfm else 6))
        if mfm:
            emit(b"\xA1\xA1\xA1")
        dam = s.get("dam", 0xFB)
        data = s["data"]
        assert len(data) == 128 << code
        crc = crc16(pre + bytes([dam]) + data)
        if s.get("bad_crc"):
            crc ^= 0xFFFF
        emit(bytes([dam]) + data + crc.to_bytes(2, "big"))
        emit((b"\x4E" if mfm else b"\xFF") * (24 if mfm else 27))
    hdr = bytearray(128)
    for i, p in enumerate(ptrs):
        hdr[2 * i:2 * i + 2] = struct.pack("<H", p)
    rec = bytes(hdr) + bytes(body)
    assert len(rec) <= track_len, (len(rec), track_len)
    return rec + (b"\x4E" if mfm else b"\xFF") * (track_len - len(rec))


def make_dmk(track_records, tracks, sides=2, track_len=6400, flags=0):
    """track_records in file order (cyl0 side0, cyl0 side1, cyl1 side0, ...)."""
    if sides == 1:
        flags |= 0x10
    hdr = bytes([0, tracks]) + struct.pack("<H", track_len) + bytes([flags]) + bytes(11)
    return hdr + b"".join(track_records)


def sector(cyl, side, num, fill=None, size_code=1, **kw):
    n = 128 << size_code
    data = bytes((num + i) & 0xFF for i in range(n)) if fill is None else bytes([fill]) * n
    return dict(cyl=cyl, side=side, num=num, size_code=size_code, data=data, **kw)
