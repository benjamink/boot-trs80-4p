# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Builds the byte stream for the WD179x "Write Track" command from a parsed DMK track.

Data-register codes (WD1793 data sheet, Type III Write Track):
  MFM: F5 = A1 sync (missing clock, presets CRC), F6 = C2 sync, F7 = write 2 CRC bytes,
       F8-FB / FC / FE = written as ordinary bytes (the preceding F5 F5 F5 makes them marks).
  FM:  F8-FB (data mark), FC (index mark), FE (ID mark) are written with their special
       clocks; F7 = CRC; F5/F6 are not used.
Gap sizes are the standard IBM System 34 (MFM) / 3740 (FM) values; they match the gaps seen
in the LS-DOS 6.3.1 DMK images (32x4E pre-gap, 12x00 sync, 22x4E gap 2, 24-byte gap 3).
Each sector keeps its exact ID (cyl, side, number, size), data mark and order from the image.
"""

TRACK_CAPACITY = 6250   # raw bytes per track at 250 kbps, 300 rpm (double density)
PAD_LEN = 6400          # streams are padded to this; the command ends at the index pulse

_CODES = {128: 0, 256: 1, 512: 2, 1024: 3}


def _size_code(size):
    try:
        return _CODES[size]
    except KeyError:
        raise ValueError(f"unsupported sector size {size}")


def build_write_track(track, pad_to=PAD_LEN, fill=None):
    """fill=None puts each sector's data in the stream (only safe if it has no F5/F6/F7 bytes);
    fill=<byte> formats every sector with that byte -- the data is then written with Write Sector."""
    if not track.sectors:
        raise ValueError("track has no sectors")
    densities = {s.density for s in track.sectors}
    if len(densities) != 1:
        raise ValueError(f"mixed densities on one track: {sorted(densities)}")
    mfm = densities == {"MFM"}
    gap, zeros = (b"\x4E", 12) if mfm else (b"\xFF", 6)
    out = bytearray()
    if mfm:
        out += b"\x4E" * 32
    else:
        out += b"\xFF" * 40 + b"\x00" * 6 + b"\xFC" + b"\xFF" * 26
    sync = b"\xF5\xF5\xF5" if mfm else b""
    for s in track.sectors:
        if s.dam not in (0xF8, 0xF9, 0xFA, 0xFB):
            raise ValueError(f"sector {s.num}: bad data address mark {s.dam:#04x}")
        if len(s.data) != s.size:
            raise ValueError(f"sector {s.num}: data length {len(s.data)} != size {s.size}")
        out += b"\x00" * zeros + sync + bytes([0xFE, s.cyl, s.side, s.num, _size_code(s.size), 0xF7])
        out += gap * (22 if mfm else 11)
        body = s.data if fill is None else bytes([fill]) * s.size
        out += b"\x00" * zeros + sync + bytes([s.dam]) + body + b"\xF7"
        out += gap * (24 if mfm else 27)
    if len(out) > TRACK_CAPACITY:
        raise ValueError(f"track needs {len(out)} bytes but only {TRACK_CAPACITY} fit")
    out += gap * (pad_to - len(out))
    return bytes(out)


def verify_plan(track):
    """(sector number, size, data) for every sector, in track order, to compare after writing."""
    return [(s.num, s.size, s.data) for s in track.sectors]
