#!/usr/bin/env python3
"""Make a raw LS-DOS 6.3.1 data disk image holding the files you give, ready for fujinet-nio and FMOUNT.

  tools/make_data_image.py out.img TETRIS.CMD [more files...]      # TETRIS.CMD becomes TETRIS/CMD; --as NAME/EXT to rename one

The disk starts from images/lsdos631l-upstream/L631NEW.DSK with everything removed except BOOT/SYS and DIR/SYS, so there is room
(the 180 KB disk is otherwise full) and it is not bootable. On the 4P: FMOUNT :1 host:/images/out.img SS=256, then TETRIS :1.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from trs80 import lsdosfs  # noqa: E402
from trs80.dmk import parse_dmk  # noqa: E402

BASE = os.path.join(ROOT, "images", "lsdos631l-upstream", "L631NEW.DSK")
KEEP = {"BOOT/SYS", "DIR/SYS"}


def dos_name(path):
    base = os.path.basename(path).upper()
    stem, dot, ext = base.rpartition(".")
    return f"{stem}/{ext}" if dot else base


def build_disk(files):
    """files: list of (NAME/EXT, bytes). Returns the parsed disk (for checking) before it is flattened."""
    with open(BASE, "rb") as f:
        img = parse_dmk(f.read())
    for e in lsdosfs.list_files(img):
        name = f"{e.name}/{e.ext}" if e.ext else e.name
        if name not in KEEP:
            img = lsdosfs.delete_file(img, name)
    for name, data in files:
        img = lsdosfs.add_file(img, name, data)
    return img


def build(files):
    """Returns the raw 256-byte-sector image."""
    return lsdosfs.flat_image(build_disk(files))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    files = []
    for p in a.files:
        with open(p, "rb") as f:
            files.append((dos_name(p), f.read()))
    raw = build(files)
    with open(a.out, "wb") as f:
        f.write(raw)
    print(f"{a.out}: {len(raw)} bytes; files: " + ", ".join(n for n, _ in files))


if __name__ == "__main__":
    main()
