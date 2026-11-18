"""DMK disk image parser/serializer (David Keil's format, as used by the TRS-80 emulators).

Layout: 16-byte header (byte1 = tracks, bytes2-3 = track record length, byte4 flags:
0x10 single sided, 0x40 single-density-only, 0x80 ignore density), then one record per
track (cyl0 side0, cyl0 side1, cyl1 side0, ...). Each record = 64 little-endian IDAM
pointers (bit 15 = double density) + raw track bytes. FM bytes are stored doubled unless
the header says single-density-only. Pointers address the 0xFE of each ID field.
"""
import struct
from dataclasses import dataclass, field

HEADER_LEN = 16
TABLE_LEN = 128


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT (poly 0x1021, init 0xFFFF) as used by the WD179x."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Sector:
    cyl: int            # from the ID field
    side: int
    num: int
    size: int           # bytes
    dam: int            # 0xFB normal, 0xF8 deleted (0xF9/0xFA also possible)
    data: bytes
    density: str        # "FM" or "MFM"
    id_crc_ok: bool
    data_crc_ok: bool
    data_off: int = 0   # offset of the first data byte inside the track record
    step: int = 1       # 2 when FM bytes are stored doubled
    mfm: bool = True


@dataclass
class Track:
    cyl: int            # physical position in the image
    side: int
    present: bool
    sectors: list = field(default_factory=list)
    raw: bytearray = field(default_factory=bytearray)


class DmkImage:
    def __init__(self, header, tracks, sides, track_len, track_list):
        self.header = bytearray(header)
        self.tracks = tracks
        self.sides = sides
        self.track_len = track_len
        self._tracks = track_list

    def get(self, cyl, side):
        if side >= self.sides or cyl >= self.tracks:
            return Track(cyl, side, False)
        return self._tracks[cyl * self.sides + side]

    def set_sector_data(self, cyl, side, num, data):
        t = self.get(cyl, side)
        for s in t.sectors:
            if s.num == num:
                break
        else:
            raise KeyError(f"no sector {num} on cyl {cyl} side {side}")
        if len(data) != s.size:
            raise ValueError(f"sector {num} holds {s.size} bytes, got {len(data)}")
        pre = b"\xA1\xA1\xA1" if s.mfm else b""
        crc = crc16(pre + bytes([s.dam]) + data).to_bytes(2, "big")
        for k, b in enumerate(data + crc):
            for j in range(s.step):
                t.raw[s.data_off + k * s.step + j] = b
        s.data, s.data_crc_ok = bytes(data), True

    def to_bytes(self):
        return bytes(self.header) + b"".join(bytes(t.raw) for t in self._tracks if t.present)


def _parse_track(rec, cyl, side, flags):
    sectors = []
    for i in range(64):
        ptr = struct.unpack_from("<H", rec, 2 * i)[0]
        if ptr == 0:
            break
        off = ptr & 0x3FFF
        mfm = bool(ptr & 0x8000) or bool(flags & 0x80)
        step = 1 if (mfm or flags & (0x40 | 0x80)) else 2
        end = len(rec)

        def at(pos, n):
            idx = [pos + k * step for k in range(n)]
            return bytes(rec[j] for j in idx) if idx and idx[-1] < end else None

        idf = at(off, 7)
        if idf is None or idf[0] != 0xFE:
            continue
        pre = b"\xA1\xA1\xA1" if mfm else b""
        id_ok = crc16(pre + idf[:5]) == int.from_bytes(idf[5:7], "big")
        c, h, num, code = idf[1], idf[2], idf[3], idf[4]
        size = 128 << code if code < 4 else 0
        pos, dam = off + 7 * step, None
        for k in range(64):
            b = at(pos + k * step, 1)
            if b is None:
                break
            if b[0] in (0xF8, 0xF9, 0xFA, 0xFB):
                dam, pos = b[0], pos + k * step
                break
        data, data_ok, data_off = b"", False, 0
        if dam is not None and size:
            data_off = pos + step
            blob = at(data_off, size + 2)
            if blob is not None:
                data = blob[:size]
                data_ok = crc16(pre + bytes([dam]) + data) == int.from_bytes(blob[size:], "big")
        sectors.append(Sector(c, h, num, size, dam if dam is not None else 0, data,
                              "MFM" if mfm else "FM", id_ok, data_ok, data_off, step, mfm))
    return Track(cyl, side, True, sectors, bytearray(rec))


def parse_dmk(data):
    if len(data) < HEADER_LEN:
        raise ValueError("DMK header truncated")
    tracks, track_len, flags = data[1], struct.unpack_from("<H", data, 2)[0], data[4]
    if data[0] not in (0, 0xFF) or not 1 <= tracks <= 90 or not TABLE_LEN < track_len <= 0x2940 or flags & 0x2F or any(data[11:16]):
        raise ValueError(f"not a DMK image (header says tracks={tracks} track_len={track_len}); a raw .img or a JV3 .dsk must be "
                         "converted first, e.g. tools/jv3_to_dmk.py")
    sides = 1 if flags & 0x10 else 2
    track_list = []
    for k in range(tracks * sides):
        cyl, side = divmod(k, sides)
        off = HEADER_LEN + k * track_len
        rec = data[off:off + track_len]
        if len(rec) < track_len:                      # missing or partial trailing track
            track_list.append(Track(cyl, side, False))
        else:
            track_list.append(_parse_track(rec, cyl, side, flags))
    return DmkImage(data[:HEADER_LEN], tracks, sides, track_len, track_list)
