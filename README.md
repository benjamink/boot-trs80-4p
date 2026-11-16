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

## Sending files to the 4P once LS-DOS runs (SERIAL/CMD + trs80put.py)

`SERIAL/CMD` is a program on the boot floppy that turns the 4P into a file receiver. It is the resident
monitor with a small front end (sets the UART to 19200 baud, 8O1, then waits), and the files it receives
are written by LS-DOS itself.

1. Build the image and write only the two tracks that changed (about 1-2 minutes). This assumes the floppy
   still holds exactly `L631NEW.DSK` as written earlier:

       make
       python3 tools/make_boot_image.py --base images/lsdos631l-upstream/L631NEW.DSK --out images/boot.dsk
       # 4P: hold right-shift, press reset until "Ready"; then:
       ./trs80mon.py boot
       ./writedisk.py --image images/boot.dsk --base images/lsdos631l-upstream/L631NEW.DSK --drive 0

   Type `ERASE DRIVE 0` when asked. Then press reset without right-shift to boot LS-DOS.
2. At the LS-DOS prompt type `SERIAL`. The 4P prints `Serial link ready`.
3. On the PC: `./trs80put.py game.cmd notes.txt` (add `--exit` to return the 4P to the LS-DOS prompt).
   `PROG.CMD` becomes `PROG/CMD`; use `--as NAME/EXT` to choose a name, `--drive N` for another drive.
   An existing file of the same name is replaced.

While `SERIAL` runs, the 4P's interrupts are off (the clock and keyboard are idle); it ends with `--exit`
or reset. To change the disk later, keep the image file you last wrote and pass it as `--base`.
