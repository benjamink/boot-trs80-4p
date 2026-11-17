#!/usr/bin/env python3
"""Add CONFIG/CMD (the nio-config screens; drops LS-DOS BASIC to fit), SERIAL/CMD (the serial link, run from the LS-DOS prompt) and the FujiNet commands FMOUNT, FUMOUNT,
FDRIVE, FLS and FUJIDRV (the resident serial disk driver) to an LS-DOS disk image; HELP/CMD and DOS/HLP are dropped to make room.

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
BASIC_DROP = ("BASIC/CMD", "BASIC/OV1", "BASIC/OV2", "BREF/CMD")   # LS-DOS BASIC: dropped to fit CONFIG/CMD (about 22 granules)
CONFIG_BIN_DEFAULT = os.path.join(os.environ.get("NIO_WORKSPACE", ""), "repos", "nio-config", "trs80", "build", "config.bin")
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


def config_cmd(config_bin, build_dir=os.path.join(ROOT, "build")):
    """CONFIG/CMD: the nio-config program (trs80/build/config.bin, loads at 3000h) plus the config client at D000h."""
    with open(config_bin, "rb") as f:
        segs = {0x3000: f.read()}
    client, _ = parse_hex(os.path.join(build_dir, "nioclient_config.hex"))
    if 0x3000 + len(segs[0x3000]) > min(client):
        raise RuntimeError("CONFIG/CMD program overlaps the client at D000h")
    segs.update(client)
    return build_lmf(segs, 0x3000, block=240)


def make_boot_image(base, out, build_dir=os.path.join(ROOT, "build"), drop=DROP, config_bin=None):
    """Reads the DMK image `base`, adds SERIAL/CMD (and CONFIG/CMD from `config_bin`), writes `out`. Returns the new file's size."""
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
    if config_bin:
        try:
            new = lsdosfs.add_file(new, "CONFIG/CMD", config_cmd(config_bin, build_dir))
        except lsdosfs.DiskFullError as e:
            raise RuntimeError(f"CONFIG/CMD does not fit on the disk ({e}); drop more files with --drop or use --no-config") from e
    if not lsdosfs.is_bootable(new):
        raise RuntimeError("result is not bootable")
    with open(out, "wb") as f:
        f.write(new.to_bytes())
    return len(blob)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config-bin", default=CONFIG_BIN_DEFAULT, help="nio-config trs80/build/config.bin (make -C <nio-config>/trs80 build/config.bin)")
    ap.add_argument("--no-config", action="store_true", help="leave CONFIG/CMD out (keeps BASIC on the disk)")
    ap.add_argument("--drop", action="append", default=[], help="also remove this file (NAME/EXT)")
    ap.add_argument("--keep-help", action="store_true", help="keep HELP/CMD and DOS/HLP (the disk may then be too full)")
    a = ap.parse_args(argv)
    config_bin = None if a.no_config else a.config_bin
    if config_bin and not os.path.exists(config_bin):
        sys.exit(f"{config_bin} not found: build it (make -C <nio-config>/trs80 build/config.bin) or pass --no-config")
    drop = (() if a.keep_help else DROP) + (BASIC_DROP if config_bin else ()) + tuple(a.drop)
    n = make_boot_image(a.base, a.out, drop=drop, config_bin=config_bin)
    extra = ", CONFIG/CMD" if config_bin else ""
    print(f"wrote {a.out}: added {NAME} ({n} bytes), {', '.join(t.split('_')[0].upper() + '/CMD' for t in TOOLS)}{extra}; removed {', '.join(drop)} to make room")


if __name__ == "__main__":
    main()
