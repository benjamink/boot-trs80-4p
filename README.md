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
   loses `HELP/CMD` and `DOS/HLP` to make room; `--keep-help` keeps them if there is room). It also gains `CONFIG/CMD`
   (the nio-config screens: Hosts, Browse, Slots, Setup; see nio-config `docs/trs80-config.md`), which needs LS-DOS BASIC
   (`BASIC/CMD`, `BASIC/OV1`, `BASIC/OV2`, `BREF/CMD`) removed; `--no-config` leaves CONFIG out and keeps BASIC.
   Build CONFIG first with z88dk: `make -C $NIO_WORKSPACE/repos/nio-config trs80`. This assumes the floppy
   still holds exactly `L631NEW.DSK` as written earlier:

       make -C $NIO_WORKSPACE/repos/nio-config trs80
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
or reset.

**Not yet verified on the real 4P** (only in the Z80 interpreter and MAME): `SERIAL/CMD`, `trs80put.py`, and the boot image's file additions.

`--base OLD.DSK` rewrites only the tracks that differ from `OLD.DSK`, which is only valid while the floppy still holds exactly that image. Files sent with `trs80put.py`
change the floppy behind its back, so `writedisk.py` now reads back every track it would keep and refuses (before asking to erase) if any differs from the base or
cannot be read; run it without `--base` then. Each `trs80put` call gives LS-DOS up to 30 s to finish (floppy spin-up, directory and allocation updates).

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
sector); NIO has no DMK/JV3 support yet. These commands manage what the FujiNet has mounted. `FUJIDRV :d` installs the
serial disk driver on a drive (above HIGH$, from `FUJIDRV/CMD`); then `FMOUNT :d uri SS=256` makes the image readable there. Verified on a real 4P with a real
fujinet-nio on a PC (see the floppy-less boot section), and in the Z80 interpreter and MAME.
The code lives in `fujinet/` (see its README). Unknown on hardware: whether LS-DOS passes the command line in its original case (URIs are case-sensitive).

## Booting with no floppy (fujinet/z80/nioboot.asm) - works in MAME and on a real 4P with a PC-hosted fujinet-nio

`nioboot` is a loader for the ROM's serial loader (hold Right Shift at reset, send it with `trs80boot.py build/nioboot.hex --entry 0x5000`).
It reads the LS-DOS boot sector from FujiNet slot 1 (a raw 256-byte-sector image, 18 per cylinder; `trs80.lsdosfs.flat_image` makes one
from a DMK) instead of a floppy, patches the boot sector's one floppy-controller routine to fetch sectors from the FujiNet, and once
BOOT/SYS's drive table is loaded points drive 0 at the resident driver (`fujidrv.asm`, at E000h). If the FujiNet stops answering, the driver gives one full attempt
(3 tries, about 13 s with interrupts off), then fails the next 7 calls at once with "device not available" and looks again on the 8th. LS-DOS then loads and runs entirely
from the FujiNet. In MAME with no disk at all it reaches the date prompt in about 10 seconds, and `DIR :0` works.

Checked on a real 4P (no diskette in the drive) against the real fujinet-nio POSIX build on a PC (`fujibus-rs232`, `/dev/ttyUSB0`, 19200 baud, `parity: odd` in `fujinet.yaml`): boots to `LS-DOS Ready`, `DIR :0`, `FLS`, `FUJIDRV :1`, `FMOUNT :1 host:/images/work.img SS=256`, `FDRIVE` and `DIR :1` all work. Notes from that session:
- Send the loader with `--byte-delay 0.002` (`trs80boot.py build/nioboot.hex --entry 0x5000 --byte-delay 0.002 -y`): without it the ROM loader sometimes failed ("Error", or no start).
- `build/nioboot-config.hex` is nioboot assembled with `AUTO_CMD="CONFIG"`: as sector 2 of the boot area passes through, it plants the command LS-DOS's `AUTO` stores there (offset 20h), so LS-DOS starts CONFIG at the end of start-up (Q returns to the prompt). The disk itself carries no AUTO command. `./boot-fuji.sh` sends it when the boot disk has CONFIG (`--no-autostart` for the plain loader).
- nioboot waits (screen: `Waiting for FujiNet...`) until a FujiNet answers, so fujinet-nio can be started after the loader has run.
- The boot disk must be mounted before the 4P asks: `boot: mode: config` with `config_uri: host:/images/boot.xfd`. A raw `.img` fails with `GeometryRequired` because the boot mount has no sector-size hint; a 184,320-byte `.xfd` is recognised as 720 x 256-byte sectors. (A gap to raise upstream.) Make the image with `trs80.lsdosfs.flat_image`.
- LS-DOS probes every enabled floppy drive at the end of start-up and an empty real drive hangs it, so nioboot disables drives 1-7 in the drive table; FUJIDRV re-enables the one it installs.

HIGH$ protection: LS-DOS sets HIGH$ (kept at 040Eh in 6.3.1) after this loader has handed over, so the driver lowers it to DFFFh on every call. Checked in MAME: HIGH$ reads FFFF without this and DFFF with it.

Date and time: if the FujiNet has a clock device (device 0x45), LS-DOS no longer asks for them. When the last boot sector is in, the loader fetches the
clock and stores the date at 0033h-0035h and sets the flag at 04C3h that makes SYS0 skip the prompts. SYS0 then overwrites the time with its default, so
the driver fetches the clock again on the first call after LS-DOS has finished initialising (HIGH$ jumps back up) and stores the time. Checked in MAME
(date on the boot screen, `TIME` shows the fetched time) and on the real 4P against the real fujinet-nio (date and time prompts skipped; the clock device answers
with the layout assumed here). With no clock device the prompts appear as before. The time is the FujiNet's configured timezone (`clock.timezone` in
`fujinet.yaml`, `UTC` by default), so set it to your local zone. The FujiNet exchanges stop LS-DOS's own clock for about 0.3 s per sector, so the time drifts a little under disk activity.

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

## Licence

GPL-3.0-or-later (see `LICENSE`), so the FujiNet work can go upstream to fujinet-nio, which is GPL-3.0. The LS-DOS images under `images/` are not covered by it:
they keep their own terms (`images/lsdos631l-upstream/LICENSE`), and the 4P ROMs are not part of this repo.

## CONFIG demo

`NIO_WORKSPACE=... python3 tools/demo_config.py` opens a MAME window with CONFIG running against the fake
fujinet-nio (`tests/fakenio.py`); nothing real is mounted.
