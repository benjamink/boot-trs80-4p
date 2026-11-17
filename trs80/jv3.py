"""JV3 disk images (Jeff Vavasour's format, as used by xtrs and many TRS-80 archives) -> the flat 256-byte-sector image the
FujiNet driver serves (LBA = cylinder * sectors-per-cylinder + sector).

JV3 layout: 2901 sector headers of 3 bytes (track, sector id, flags; FF FF = unused), one write-protect byte, then the data of
the headers' sectors one after the other in header order. Flags: bit 7 double density, bits 6-5 data address mark, bit 4 side,
bit 3 CRC error, bits 1-0 size code (0 = 256 bytes in the IBM layout). Only single-sided 256-byte sectors are supported (LS-DOS).
fujinet-nio does not read JV3 yet, so it serves such a file as if it were raw and LS-DOS reads garbage.
"""
HEADERS = 2901
DATA_START = HEADERS * 3 + 1


def _entries(data):
    if len(data) < DATA_START:
        raise ValueError("too short to be a JV3 image")
    out = []
    for i in range(HEADERS):
        t, s, f = data[i * 3:i * 3 + 3]
        if t == 0xFF and s == 0xFF:
            continue
        out.append((t, s, f))
    if not out:
        raise ValueError("no sectors in the JV3 header")
    return out


def looks_like_jv3(first_sector):
    """True if the first 256 bytes of a file look like the start of a JV3 header (tracks and sector ids counting up from 0)."""
    b = bytes(first_sector[:9])
    return len(b) == 9 and b[0] == 0 and b[1] == 0 and b[3] == 0 and b[4] == 1 and b[6] == 0 and b[7] == 2 and b[2] >= 0x80 and b[5] >= 0x80 and b[8] >= 0x80


def flat_image(data):
    ents = _entries(data)
    for t, s, f in ents:
        if f & 0x10:
            raise ValueError("double-sided JV3 images are not supported")
        if f & 0x03:
            raise ValueError(f"track {t} sector {s}: sector size code {f & 3} (only 256-byte sectors are supported)")
    spc = max(s for _, s, _ in ents) + 1
    cyls = max(t for t, _, _ in ents) + 1
    if len(data) < DATA_START + 256 * len(ents):
        raise ValueError("truncated JV3 image")
    out = bytearray(cyls * spc * 256)
    for i, (t, s, f) in enumerate(ents):
        src = DATA_START + i * 256
        out[(t * spc + s) * 256:(t * spc + s + 1) * 256] = data[src:src + 256]
    return bytes(out)
