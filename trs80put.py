#!/usr/bin/env python3
"""trs80put -- copy files from this PC onto the LS-DOS floppy in the TRS-80 4P, over the serial cable.

On the 4P (booted from the disk made by tools/make_boot_image.py), at the LS-DOS prompt, type:
    SERIAL
It prints "Serial link ready". Then here:
    trs80put.py game.cmd notes.txt              # -> GAME/CMD and NOTES/TXT on drive 0
    trs80put.py hello.bas --as HELLO/BAS --drive 1
    trs80put.py notes.txt --text                # convert CRLF/LF line endings to CR (LS-DOS text), else LIST shows blank lines
    trs80put.py game.cmd --exit                 # afterwards return the 4P to the LS-DOS prompt
An existing file of the same name is replaced (it says so). Each file is written by LS-DOS itself.
"""
import argparse, os, sys

from trs80 import lsdosfs
from trs80.dosfile import DEFAULT_HEX, DosError, DosLink
from trs80.monitor import Monitor, MonitorError


def _default_open_monitor(port):
    from trs80.serialio import SerialTransport, open_port
    mon = Monitor(SerialTransport(open_port(port, 19200)))
    mon.sync()
    return mon


def dos_name(path):
    base, ext = os.path.splitext(os.path.basename(path))
    return f"{base}/{ext[1:]}" if ext else base


def to_cr(data):
    """Text for LS-DOS: lines end with CR alone. CRLF and bare LF both become CR."""
    return data.replace(b"\r\n", b"\r").replace(b"\n", b"\r")


def main(argv=None, *, open_monitor=_default_open_monitor, out=print, hex_path=DEFAULT_HEX):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--as", dest="as_name", metavar="NAME/EXT", help="LS-DOS name (only with one file)")
    ap.add_argument("--drive", type=int, default=0, choices=range(8))
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("--text", action="store_true", help="text files: convert CRLF/LF line endings to CR (otherwise LIST double-spaces)")
    ap.add_argument("--exit", action="store_true", help="return the 4P to the LS-DOS prompt afterwards")
    a = ap.parse_args(argv)
    if a.as_name and len(a.files) != 1:
        ap.error("--as needs exactly one file")
    jobs = []
    for path in a.files:
        name = a.as_name or dos_name(path)
        try:
            lsdosfs.split_name(name)
        except ValueError as e:
            out(f"{path}: {e}")
            return 1
        with open(path, "rb") as f:
            jobs.append((path, name.upper(), to_cr(f.read()) if a.text else f.read()))
    try:
        mon = open_monitor(a.port)
        link = DosLink(mon, hex_path=hex_path)
        link.upload()
        for path, name, data in jobs:
            replaced = link.put(name, data, drive=a.drive)
            out(f"{path} -> {name}:{a.drive}  {len(data)} bytes" + ("  (text, line endings converted)" if a.text else "") + (f"  (replaced existing {name})" if replaced else ""))
    except DosError as e:
        out(f"FAILED: {e}")
        return 1
    except MonitorError as e:
        out(f"FAILED: no answer from the 4P ({e}). Is SERIAL running at the LS-DOS prompt?")
        return 1
    if a.exit:
        link.exit()
        out("4P returned to LS-DOS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
