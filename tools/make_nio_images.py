#!/usr/bin/env python3
"""Write the raw 256-byte-sector images a PC-hosted fujinet-nio serves to the 4P (see docs/fujinet-nio-testing.md).

  tools/make_nio_images.py RUN_DIR      # makes RUN_DIR/fujinet-data/images/boot.xfd and work.img

boot.xfd is images/boot.dsk (the 4P's boot disk, the name makes fujinet-nio read 184,320 bytes as 720 x 256-byte sectors);
work.img is the plain LS-DOS 6.3.1 disk, handy for FMOUNT. Run tools/make_boot_image.py first.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from trs80 import dmk, lsdosfs  # noqa: E402


def flat(path):
    with open(path, "rb") as f:
        return lsdosfs.flat_image(dmk.parse_dmk(f.read()))


def main(run_dir):
    out = os.path.join(os.path.expanduser(run_dir), "fujinet-data", "images")
    os.makedirs(out, exist_ok=True)
    for name, src in (("boot.xfd", "images/boot.dsk"), ("work.img", "images/lsdos631l-upstream/L631NEW.DSK")):
        data = flat(os.path.join(ROOT, src))
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        print(f"{os.path.join(out, name)}: {len(data)} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
