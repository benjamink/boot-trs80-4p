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

1. Build the image and write only the tracks that changed (the image also gains the FujiNet commands below and
   loses `HELP/CMD` and `DOS/HLP` to make room; `--keep-help` keeps them if there is room). This assumes the floppy
   still holds exactly `L631NEW.DSK` as written earlier:

       make
       python3 tools/make_boot_image.py --base images/lsdos631l-upstream/L631NEW.DSK --out images/boot.dsk
       # 4P: hold right-shift, press reset until "Ready"; then:
       ./trs80mon.py boot
       ./writedisk.py --image images/boot.dsk --base images/lsdos631l-upstream/L631NEW.DSK --drive 0

   Type `ERASE DRIVE 0` when asked. Then press reset without right-shift to boot LS-DOS.
2. At the LS-DOS prompt type `SERIAL`. The 4P prints `Serial link ready`.
3. On the PC: `./trs80put.py game.cmd notes.txt` (add `--text` for text files so CRLF/LF line endings become CR and `LIST` does not double-space; add `--exit` to return the 4P to the LS-DOS prompt).
   `PROG.CMD` becomes `PROG/CMD`; use `--as NAME/EXT` to choose a name, `--drive N` for another drive.
   An existing file of the same name is replaced.

While `SERIAL` runs, the 4P's interrupts are off (the clock and keyboard are idle); it ends with `--exit`
or reset. To change the disk later, keep the image file you last wrote and pass it as `--base`.

## FujiNet commands under LS-DOS (FMOUNT, FUMOUNT, FDRIVE, FLS)

For booting straight to LS-DOS rather than into CONFIG. They mirror the `F*` utilities in nio-core-apps and are
on the disk made by `tools/make_boot_image.py`. Each talks to a fujinet-nio on the 4P's serial port (19200
baud, 8O1) directly; interrupts are off while they run.

| Command | What it does |
|---|---|
| `FLS [uri]` | list a directory on the FujiNet's storage (default `sd0:/`; also `host:/`, `tnfs://server/dir`) |
| `FMOUNT :d uri [RO\|RW] [SS=bytes]` | mount an image on FujiNet slot d+1 (LS-DOS drive `:d`, 0-7) |
| `FUMOUNT :d` | release that drive's image |
| `FDRIVE` | list what is mounted, one line per drive |

Example: `FMOUNT :1 sd0:/disks/work.img SS=256`. Images must be raw 256-byte-sector files (LBA = cylinder*18 +
sector); NIO has no DMK/JV3 support yet. These commands manage what the FujiNet has mounted. Until the LS-DOS
serial disk driver exists (plan phase 2) LS-DOS cannot read a mounted drive: the commands are verified in the
Z80 interpreter and against a real fujinet-nio on a PC (`fujinet/cli_live.py`), not yet on the 4P itself.
The code lives in `fujinet/` (see its README). Unknown on hardware: whether LS-DOS passes the command line in its original case (URIs are case-sensitive).

## Testing without the 4P: MAME

MAME's `trs80m4p` runs the real 4P boot ROM and real LS-DOS, with an RS-232 port that `tools/mame4p.py` exposes as a pty
(set to 19200 baud, 8O1). It is how `SERIAL/CMD`, `trs80put.py` and the FujiNet commands were checked before the real
machine was available.

- ROMs: `images/roms/trs80m4p/` needs `8075332.u69`, `8049007.u103` and `trs80m4p_loader_hack.rom` (from the
  `trs80m3.zip` ROM set; never committed). The u69 dump matches the CRC MAME expects.
- Serial loader: `Mame4P(roms, mode="serial")` holds right-shift through reset, so `trs80mon.py -p <pty> boot` works as on the real machine.
- Disk boot: MAME's ROM samples the floppy-ready line before the drive has spun up, so `tools/mame4p.lua` keeps drive 0
  selected and resets once; LS-DOS then boots from the image (type the date and time at the prompts).
- Run: `MAME_TESTS=1 python3 -m unittest tests.test_mame_integration` (about 80 seconds): sends a file with `SERIAL` +
  `trs80put.py` and reads it back with `LIST`; runs `FLS`, `FMOUNT`, `FDRIVE`, `FUMOUNT` against the fake NIO.
- `tools/ptybridge.py PTY1 PTY2 --log FILE` forwards bytes between two ptys and logs them in hex, e.g. MAME's pty and a
  fujinet-nio's (see the research findings for running NIO on a PC).

What MAME is not: it is not proof of real-hardware timing, and MAME's UART differs from the real one in at least one way
(writing 0 to port E8h breaks its UART setup), which is why the init sequence copies the ROM's exactly.
