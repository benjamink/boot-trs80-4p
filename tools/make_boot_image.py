#!/usr/bin/env python3
"""Add SERIAL/CMD (the serial link, run from the LS-DOS prompt) and the FujiNet commands FMOUNT, FUMOUNT,
FDRIVE to an LS-DOS disk image.

  tools/make_boot_image.py --base images/lsdos631l-upstream/L631NEW.DSK --out images/boot.dsk

SERIAL/CMD is a TRSDOS load module: z80/serialcmd.asm at 5F00h (sets the UART up, prints a line)
followed by the resident monitor at 6000h.  Run `make` first.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80 import lsdosfs  # noqa: E402
from trs80.dmk import parse_dmk  # noqa: E402
from trs80.lmf import build_lmf, parse_hex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "SERIAL/CMD"
DROP = ("HELP/CMD", "DOS/HLP")                 # the help system: makes room, the disk is otherwise full
TOOLS = ("fmount", "fumount", "fdrive", "fls", "fujidrv_cmd")        # LS-DOS commands for the FujiNet: z80/<name>.asm, entry 3000h


def serial_cmd(build_dir=os.path.join(ROOT, "build")):
    segs = {}
    for hexname in ("serialcmd.hex", "mon.hex"):
        s, _ = parse_hex(os.path.join(build_dir, hexname))
        segs.update(s)
    return build_lmf(segs, 0x5F00, block=240)


def tool_cmd(tool, build_dir=os.path.join(ROOT, "build")):
    segs, _ = parse_hex(os.path.join(build_dir, tool + ".hex"))
    return build_lmf(segs, 0x3000, block=240)


def make_boot_image(base, out, build_dir=os.path.join(ROOT, "build"), drop=DROP):
    """Reads the DMK image `base`, adds SERIAL/CMD, writes `out`. Returns the new file's size."""
    with open(base, "rb") as f:
        img = parse_dmk(f.read())
    blob = serial_cmd(build_dir)
    new = img
    for name in drop:
        if any(f"{f.name}/{f.ext}" == name for f in lsdosfs.list_files(new)):
            new = lsdosfs.delete_file(new, name)
    new = lsdosfs.add_file(new, NAME, blob)
    for tool in TOOLS:
        new = lsdosfs.add_file(new, tool.split("_")[0].upper() + "/CMD", tool_cmd(tool, build_dir))
    if not lsdosfs.is_bootable(new):
        raise RuntimeError("result is not bootable")
    with open(out, "wb") as f:
        f.write(new.to_bytes())
    return len(blob)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-help", action="store_true", help="keep HELP/CMD and DOS/HLP (the disk may then be too full)")
    a = ap.parse_args(argv)
    n = make_boot_image(a.base, a.out, drop=() if a.keep_help else DROP)
    dropped = "" if a.keep_help else f"; removed {' and '.join(DROP)} to make room"
    print(f"wrote {a.out}: added {NAME} ({n} bytes) and {', '.join(t.split('_')[0].upper() + '/CMD' for t in TOOLS)}{dropped}")


if __name__ == "__main__":
    main()
