#!/usr/bin/env python3
"""writedisk -- write a DMK disk image to a floppy in the TRS-80 4P, over serial.

Start the resident monitor first:  ./trs80mon.py boot   (right-shift + reset on the 4P).

  writedisk.py --image X.DSK --drive 0 --dry-run         # parse and plan only; never opens the port
  writedisk.py --image X.DSK --drive 0 --probe-only      # read-only drive check
  writedisk.py --image X.DSK --drive 0                   # ERASES the floppy; asks you to type ERASE DRIVE 0

Each track is formatted from the image's own layout (sector order and IDs), every sector is written
with Write Sector (so any data byte survives), then every sector is read back and compared.
There is deliberately no --yes flag.
"""
import argparse, sys

from trs80 import trackplan
from trs80.dmk import parse_dmk
from trs80.fdc import Fdc, FdcError

FILLER = 0xE5


class WriteVerifyError(Exception):
    def __init__(self, cyl, side, sector):
        super().__init__(f"verify failed at cylinder {cyl} side {side} sector {sector}")
        self.cyl, self.side, self.sector = cyl, side, sector


def confirm_erase(drive, info, input_fn, confirm_arg, interactive):
    """True only for the exact text 'ERASE DRIVE <n>' (from --confirm, or typed when interactive)."""
    want = f"ERASE DRIVE {drive}"
    if confirm_arg is not None:
        return confirm_arg == want
    if not interactive:
        return False
    return input_fn(f"This will ERASE the floppy in drive {drive} ({info.status_text}). Type '{want}' to continue: ") == want


def _write_track_once(fdc, drive, track):
    stream = trackplan.build_write_track(track, fill=FILLER)
    fdc.arm_write()
    try:
        err = fdc.write_track(drive, track.cyl, track.side, stream, track.sectors[0].density)
        if err:
            raise FdcError(f"write track C{track.cyl} H{track.side} failed (error {err})")
        for s in track.sectors:
            err = fdc.write_sector(drive, track.cyl, track.side, s.num, s.data, s.density, s.dam)
            if err:
                raise FdcError(f"write sector C{track.cyl} H{track.side} S{s.num} failed (error {err})")
    finally:
        fdc.disarm()


def _verify_track(fdc, drive, track):
    for num, size, data in trackplan.verify_plan(track):
        try:
            got = fdc.read_sector(drive, track.cyl, track.side, num, size, track.sectors[0].density)
        except FdcError as e:
            return num, f"could not be read ({e})"
        if got != data:
            return num, "read back different data"
    return None


def write_image(fdc, image, drive, progress=print, retries=2):
    if drive not in fdc.probed:
        raise RuntimeError("probe the drive before writing")
    for cyl in range(image.tracks):                    # refuse up front, before the disk is touched
        for side in range(image.sides):
            for s in image.get(cyl, side).sectors:
                if s.dam not in (0xFB, 0xF8):
                    raise FdcError(f"C{cyl} H{side} S{s.num}: the WD1773 can only write data marks FB or F8, not {s.dam:#04x}")
    skipped = []
    for cyl in range(image.tracks):
        for side in range(image.sides):
            track = image.get(cyl, side)
            if not track.present or not track.sectors:
                skipped.append(f"C{cyl} H{side}")
                continue
            for attempt in range(retries + 1):
                _write_track_once(fdc, drive, track)
                bad = _verify_track(fdc, drive, track)
                if bad is None:
                    break
                progress(f"  C{cyl} H{side}: sector {bad[0]} {bad[1]} (attempt {attempt + 1}/{retries + 1})")
            else:
                raise WriteVerifyError(cyl, side, bad[0])
            progress(f"cylinder {cyl} side {side}: {len(track.sectors)} sectors written and verified")
    if skipped:
        progress(f"skipped {len(skipped)} tracks with no sectors in the image: {', '.join(skipped)}")


def _default_open_fdc(port):
    from trs80.monitor import Monitor
    from trs80.serialio import SerialTransport, open_port
    mon = Monitor(SerialTransport(open_port(port, 19200)))
    mon.sync()
    fdc = Fdc(mon)
    fdc.upload()
    return fdc


def main(argv=None, *, input_fn=input, open_fdc=_default_open_fdc, out=print, isatty=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--drive", type=int, required=True, choices=range(4))
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("--dry-run", action="store_true", help="parse and plan only; never opens the serial port")
    ap.add_argument("--probe-only", action="store_true", help="read-only drive check")
    ap.add_argument("--confirm", metavar="TEXT", help="for scripts: must equal 'ERASE DRIVE <n>'")
    a = ap.parse_args(argv)
    if isatty is None:
        isatty = sys.stdin.isatty()

    with open(a.image, "rb") as f:
        image = parse_dmk(f.read())
    todo = [(c, s) for c in range(image.tracks) for s in range(image.sides)
            if image.get(c, s).present and image.get(c, s).sectors]
    last_cyl = max(c for c, _ in todo) if todo else -1
    out(f"image {a.image}: {len(todo)} tracks to write, cylinders 0-{last_cyl}")
    if a.dry_run:
        return 0

    fdc = open_fdc(a.port)
    info = fdc.probe(a.drive)
    out(f"drive {a.drive}: {info.status_text}")
    if not info.present:
        out("refusing: no ready disk in that drive")
        return 2
    if a.probe_only:
        return 0
    if 0 <= info.max_track < last_cyl:
        out(f"refusing: image needs cylinder {last_cyl} but the drive's highest readable track is {info.max_track}")
        return 2
    if not confirm_erase(a.drive, info, input_fn, a.confirm, isatty):
        out("not confirmed; nothing was written")
        return 2
    try:
        write_image(fdc, image, a.drive, progress=out)
    except KeyboardInterrupt:
        out(f"\ninterrupted: the floppy in drive {a.drive} is partly written and will not boot. "
            "Run this again to rewrite it from track 0.")
        return 130
    except (WriteVerifyError, FdcError) as e:
        out(f"FAILED: {e}. The floppy is partly written and will not boot; run again to rewrite from track 0.")
        return 1
    out("done: every sector was written and read back correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
