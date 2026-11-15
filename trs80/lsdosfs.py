"""Read-only LS-DOS / TRSDOS 6 file system access to a DmkImage.

Layout (worked out from the real LS-DOS 6.3.1 images, cross-checked by hand against their hex):
  boot sector (cyl 0, sector 0): byte 0 = 00, byte 1 = FE, byte 2 = directory cylinder.
  directory cylinder: sector 0 = GAT (granule allocation table; 0x60.. = lockout table),
      sector 1 = HIT (hash table), sectors 2.. = directory, 32-byte entries.
  directory entry: +0 attributes (0x10 in use, 0x40 system, 0x08 invisible, 0x80 extended entry,
      bits 0-2 protection level), +3 EOF byte offset (0 = whole last record), +4 record length,
      +5..12 name, +13..15 extension (space padded), +20..21 ERN (record count, little endian),
      +22.. five extents of (cylinder, byte): bits 5-7 = first granule in that cylinder,
      bits 0-4 = granules in the extent minus 1.  0xFF ends the list, 0xFE links to a further entry.
  size = ERN*256 if EOF offset is 0, else (ERN-1)*256 + offset.
Geometry is taken from the image: granules per cylinder from the GAT lockout table, sectors per
granule = sectors per cylinder / granules per cylinder. Sector numbers in the IDs are logical
(0-17 here); the interleave on the track does not matter.
"""
from dataclasses import dataclass

SECTOR = 256


@dataclass
class FileEntry:
    name: str
    ext: str
    size: int
    system: bool
    first_granule: int          # absolute: cylinder * granules_per_cylinder + granule within cylinder


class _Geometry:
    def __init__(self, img):
        boot = self.sector(img, 0, 0)
        if boot is None:
            raise ValueError("no boot sector")
        self.boot = boot
        self.dir_cyl = boot[2]
        gat = self.sector(img, self.dir_cyl, 0)
        if gat is None:
            raise ValueError(f"no GAT on directory cylinder {self.dir_cyl}")
        self.gat = gat
        self.img = img
        lock = gat[0x60]
        gpc = 0
        while gpc < 8 and not lock >> gpc & 1:
            gpc += 1
        if gpc == 0:
            raise ValueError("cannot determine granules per cylinder from the GAT lockout table")
        self.gpc = gpc
        self.spc = sum(len(img.get(self.dir_cyl, side).sectors) for side in range(img.sides))
        if self.spc % gpc:
            raise ValueError(f"{self.spc} sectors per cylinder is not divisible by {gpc} granules")
        self.spg = self.spc // gpc
        self.spt = len(img.get(self.dir_cyl, 0).sectors)

    @staticmethod
    def sector(img, cyl, num, side=0):
        for s in img.get(cyl, side).sectors:
            if s.num == num:
                return s.data
        return None

    def logical(self, cyl, k):
        """Data of the k-th sector (0-based) of a cylinder, spanning sides in order."""
        side, num = divmod(k, self.spt)
        data = self.sector(self.img, cyl, num, side)
        if data is None:
            raise ValueError(f"missing sector {num} on cylinder {cyl} side {side}")
        return data


def _entries(g):
    for k in range(2, g.spc):
        d = g.logical(g.dir_cyl, k)
        for off in range(0, SECTOR, 32):
            yield d[off:off + 32]


def _parse(e):
    name = bytes(e[5:13]).decode("latin-1").rstrip(" ")
    ext = bytes(e[13:16]).decode("latin-1").rstrip(" ")
    ern = e[20] | e[21] << 8
    size = ern * SECTOR if e[3] == 0 else (ern - 1) * SECTOR + e[3]
    return name, ext, size


def _live(e):
    return bool(e[0] & 0x10) and not e[0] & 0x80


def list_files(img):
    g = _Geometry(img)
    out = []
    for e in _entries(g):
        if not _live(e):
            continue
        name, ext, size = _parse(e)
        cyl, info = e[22], e[23]
        out.append(FileEntry(name, ext, size, bool(e[0] & 0x40), cyl * g.gpc + (info >> 5)))
    return out


def read_file(img, name):
    g = _Geometry(img)
    want = name.upper()
    for e in _entries(g):
        if not _live(e):
            continue
        n, ext, size = _parse(e)
        if f"{n}/{ext}" != want and (ext or f"{n}" != want):
            continue
        data = bytearray()
        for i in range(22, 32, 2):
            cyl, info = e[i], e[i + 1]
            if cyl == 0xFF:
                break
            if cyl == 0xFE:
                raise NotImplementedError(f"{want}: linked directory extents are not supported")
            first, count = info >> 5, (info & 0x1F) + 1
            for absg in range(cyl * g.gpc + first, cyl * g.gpc + first + count):   # runs cross cylinders
                c, gran = divmod(absg, g.gpc)
                for s in range(g.spg):
                    data += g.logical(c, gran * g.spg + s)
                    if len(data) >= size:
                        return bytes(data[:size])
        if len(data) < size:
            raise ValueError(f"{want}: extents cover {len(data)} bytes but the directory says {size}")
        return bytes(data[:size])
    raise FileNotFoundError(name)


def is_bootable(img):
    """Boot sector in place (00 FE <dircyl>) and SYS0/SYS listed in a readable directory."""
    try:
        g = _Geometry(img)
        if g.boot[0] != 0x00 or g.boot[1] != 0xFE:
            return False
        return any(f.name == "SYS0" and f.ext == "SYS" for f in list_files(img))
    except ValueError:
        return False
