# TRS-80 Model 4P over serial

Tools for a Model 4P connected to Linux by a null-modem cable (8 data bits, **odd parity**, 19200 baud).

| Tool | Purpose |
|---|---|
| `trs80boot.py` | send a load module through the 4P's ROM serial loader (`--test` for a proof-of-life) |
| `trs80mon.py` | boot the resident monitor, then `ping/peek/poke/exec/load` |
| `writedisk.py` | write a DMK disk image (LS-DOS) to a floppy in the 4P's own drive |
| `tools/monstress.py` | hardware gate for the monitor |

## Writing LS-DOS 6.3.1 to a floppy (ERASES the floppy)

1. Image: `images/lsdos631l-upstream/L631NEW.DSK` (from GmEsoft/LSDOS631L; MISOSYS grants free use,
   notice retained). Check without touching hardware:
   `./writedisk.py --image images/lsdos631l-upstream/L631NEW.DSK --drive 0 --dry-run`
2. Put a **scratch** floppy in drive 0 (everything on it will be destroyed).
3. On the 4P: hold RIGHT-SHIFT, press RESET, keep holding until "Ready". On Linux: `./trs80mon.py boot`.
4. `./writedisk.py --image images/lsdos631l-upstream/L631NEW.DSK --drive 0`
   It probes the drive, then asks you to type `ERASE DRIVE 0`. Each track is formatted, every sector
   written, then read back and compared. Success ends with
   `done: every sector was written and read back correctly`.
   Ctrl-C or an error leaves a partly written disk that will not boot; just run it again.
5. Boot: press RESET on the 4P **without** right-shift, with the floppy in drive 0. LS-DOS should show its
   `LS-DOS Ready` prompt; `DIR :0` lists the files.

`./writedisk.py ... --probe-only` is a read-only check of the drive (present, tracks, sides).
There is deliberately no `--yes` flag.
