"""LS-DOS / TRSDOS 6 file system access to a DmkImage: read, list, delete and add files.

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
  GAT: byte per cylinder, bit g set = granule g of that cylinder is allocated (the lockout table at
      0x60 marks granules that do not exist).  HIT: one hash byte per directory slot, 0 = free slot;
      the hash of the 11 name+ext bytes is c = rol8(c ^ byte) per byte (0 becomes 1); entry number i
      (sector i//8 of the directory, slot i%8) lives at HIT[(i%8)*32 + i//8].
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


def flat_image(img):
    """The disk as plain 256-byte sectors in cylinder order (LBA = cylinder * sectors-per-cylinder + sector), the layout a
    FujiNet raw image has and the FujiNet driver addresses. Single-sided images only."""
    g = _Geometry(img)
    out = bytearray()
    for cyl in range(img.tracks):
        for k in range(g.spc):
            out += g.logical(cyl, k)
    return bytes(out)


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


class DiskFullError(Exception):
    pass


class FileExistsError_(Exception):
    pass


def _copy(img):
    from trs80.dmk import parse_dmk
    return parse_dmk(img.to_bytes())


def _hash(name11):
    c = 0
    for b in name11:
        c ^= b
        c = (c << 1 | c >> 7) & 0xFF
    return c or 1


def _hit_index(i):
    return (i % 8) * 32 + i // 8


def split_name(name):
    """'NAME/EXT' -> (8-byte name, 3-byte ext), space padded and upper-cased; ValueError if not a valid LS-DOS name."""
    base, _, ext = name.upper().partition("/")
    ok = lambda t, n: len(t) <= n and all(c.isalnum() and c.isascii() for c in t)
    if not base or not ok(base, 8) or not ok(ext, 3) or not base[0].isalpha():
        raise ValueError(f"invalid LS-DOS file name {name!r} (NAME up to 8 characters, /EXT up to 3, letters and digits only)")
    return base.ljust(8).encode(), ext.ljust(3).encode()


def _put(g, cyl, k, data):
    side, num = divmod(k, g.spt)
    g.img.set_sector_data(cyl, side, num, bytes(data))


def _slot(g, i):
    """(logical sector k, offset) of directory entry i."""
    return 2 + i // 8, (i % 8) * 32


def _find(g, name):
    base, ext = split_name(name)
    for i, e in enumerate(_entries(g)):
        if _live(e) and bytes(e[5:16]) == base + ext:
            return i, e
    return None, None


def _extents(e):
    for i in range(22, 32, 2):
        cyl, info = e[i], e[i + 1]
        if cyl == 0xFF:
            return
        if cyl == 0xFE:
            raise NotImplementedError("linked directory extents are not supported")
        yield cyl, info >> 5, (info & 0x1F) + 1


def free_granules(img):
    g = _Geometry(img)
    return sum(1 for c in range(img.tracks) for b in range(g.gpc) if not g.gat[c] >> b & 1)


def _save_gat(g, gat):
    _put(g, g.dir_cyl, 0, gat)


def delete_file(img, name):
    """Returns a modified copy without the file; its granules are freed. FileNotFoundError if absent."""
    out = _copy(img)
    g = _Geometry(out)
    i, e = _find(g, name)
    if e is None:
        raise FileNotFoundError(name)
    gat = bytearray(g.gat)
    for cyl, first, count in _extents(e):
        for absg in range(cyl * g.gpc + first, cyl * g.gpc + first + count):
            c, b = divmod(absg, g.gpc)
            gat[c] &= ~(1 << b) & 0xFF
    _save_gat(g, gat)
    k, off = _slot(g, i)
    sec = bytearray(g.logical(g.dir_cyl, k))
    sec[off] &= ~0x10 & 0xFF
    _put(g, g.dir_cyl, k, sec)
    hit = bytearray(g.logical(g.dir_cyl, 1))
    hit[_hit_index(i)] = 0
    _put(g, g.dir_cyl, 1, hit)
    return out


def add_file(img, name, data):
    """Returns a modified copy with the file added (ordinary, unprotected, blank passwords)."""
    base, ext = split_name(name)
    out = _copy(img)
    g = _Geometry(out)
    if _find(g, name)[1] is not None:
        raise FileExistsError_(name)
    gran_bytes = g.spg * SECTOR
    need = -(-len(data) // gran_bytes)
    gat = bytearray(g.gat)
    free = [c * g.gpc + b for c in range(out.tracks) for b in range(g.gpc) if not gat[c] >> b & 1]
    if len(free) < need:
        raise DiskFullError(f"{name}: needs {need} granules, only {len(free)} free")
    take = free[:need]
    runs = []                                            # (first absolute granule, count)
    for a in take:
        if runs and runs[-1][0] + runs[-1][1] == a and runs[-1][1] < 32:
            runs[-1][1] += 1
        else:
            runs.append([a, 1])
    if len(runs) > 5:
        raise DiskFullError(f"{name}: free space is too fragmented ({len(runs)} extents, 5 fit in one directory entry)")
    slot = None
    hit = bytearray(g.logical(g.dir_cyl, 1))
    for i, e in enumerate(_entries(g)):
        if not e[0] & 0x10 and not e[0] & 0x80 and hit[_hit_index(i)] == 0:
            slot = i
            break
    if slot is None:
        raise DiskFullError("directory is full")
    e = bytearray(32)
    e[0] = 0x10
    e[3] = len(data) % SECTOR
    e[5:13], e[13:16] = base, ext
    e[16:20] = bytes([0x96, 0x42, 0x96, 0x42])           # blank update / access passwords
    ern = -(-len(data) // SECTOR)
    e[20], e[21] = ern & 255, ern >> 8
    for j, (first, count) in enumerate(runs):
        c, b = divmod(first, g.gpc)
        e[22 + 2 * j], e[23 + 2 * j] = c, b << 5 | (count - 1)
    for j in range(len(runs), 5):
        e[22 + 2 * j], e[23 + 2 * j] = 0xFF, 0xFF
    padded = bytes(data) + bytes(need * gran_bytes - len(data))
    for n, a in enumerate(take):
        c, b = divmod(a, g.gpc)
        gat[c] |= 1 << b
        for s in range(g.spg):
            off = (n * g.spg + s) * SECTOR
            _put(g, c, b * g.spg + s, padded[off:off + SECTOR])
    _save_gat(g, gat)
    k, off = _slot(g, slot)
    sec = bytearray(g.logical(g.dir_cyl, k))
    sec[off:off + 32] = e
    _put(g, g.dir_cyl, k, sec)
    hit[_hit_index(slot)] = _hash(base + ext)
    _put(g, g.dir_cyl, 1, hit)
    return out


def check_hit(img):
    """Directory entries whose hash-table byte is wrong; [] when the table is consistent."""
    g = _Geometry(img)
    hit = g.logical(g.dir_cyl, 1)
    bad = []
    for i, e in enumerate(_entries(g)):
        if _live(e) and hit[_hit_index(i)] != _hash(bytes(e[5:16])):
            bad.append(i)
    return bad
