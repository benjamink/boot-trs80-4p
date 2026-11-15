# TRS-80 Model 4P: LS-DOS via serial bootstrap — design

Date: 2026-11-15 · Status: draft for approval

## Intent and why

The owner has a TRS-80 Model 4P (with its built-in floppy drives and some
floppy disks, **none bootable**) and a Linux machine connected by a
USB-serial adapter and null-modem cable. The long-term goal is to boot the 4P
from a FujiNet RS-232 device running fujinet-nio, which will present virtual
media and networking. That is an advanced goal and **out of scope here**.

The goal of this project: get **LS-DOS 6.3.1 running on the 4P**, with a way
to **load programs and files over serial**, using only the Linux machine, the
serial cable, and the 4P's own drives. Everything must be delivered over
serial — the owner cannot write a physical floppy anywhere else.

## Already done (working, verified on hardware)

`trs80boot.py` boots the 4P's ROM serial loader and runs a Z80 program on it:

- Entry: hold right-shift, press reset until the 4P shows "Ready".
- Handshake: send `0x55` every 0.1 s until the ROM answers "Found Baud Rate P",
  send `0xFF`, ROM answers "Loading ", then send a TRSDOS load module
  (records `01 len lo hi data…`, final `02 02 lo hi`; 16-byte records).
- Serial format must be **8 data bits, odd parity** (8O1 or 8O2). 8N1 passes the
  handshake by coincidence but data then fails ("Error, B/C/D" = parity /
  framing / both).
- The loaded program runs at 6000h. Screen output works at F800h (Model 4 map),
  and the program can transmit to the host via UART data port EBh (verified:
  host received the text). Host→4P reception after load is **not yet verified**.
- `serial_diag.py` is a line/loopback checker. `examples/SCRDUMP.HEX` is Beattie's sample.

## Goals

1. **Boot LS-DOS 6.3.1 on the 4P from a floppy that was written entirely over serial.**
2. **Install TRSDW** (DriveWire virtual-disk driver for LS-DOS 6.3.1) on that
   boot floppy, so that once booted, the Linux machine serves virtual drives
   and files to the 4P over serial.
3. A **Linux-side DriveWire-compatible server** (or reuse of DriveWire4) that serves
   disk images to TRSDW, so the owner can load programs and files over serial.
4. The workflow stays scriptable from the Linux machine (extends `trs80boot.py`).

## Non-goals

- FujiNet / fujinet-nio support (later; DriveWire compatibility is chosen partly
  so it carries over, but that is unverified).
- Booting LS-DOS with **no floppy at all** (RAM-boot with a serial disk driver).
  Nobody has documented this on the TRS-80; it is a possible later research
  project that this work would be a stepping stone toward.
- Other operating systems, Model 1/3 support, emulators.

## Anti-goals (failure even if it "works")

- Anything that needs a floppy written on another machine.
- Silently destroying data on a floppy the owner did not agree to overwrite.
  The owner agreed to overwrite **one** of their floppies; use a single disk and
  say clearly which drive and that it is erased before writing.
- Writing a disk that looks successful but does not boot, with no verification.

## Constraints and known facts

- The 4P ROM loads one program into RAM; it does not load disk images.
- 4P boot ROM exits to the disk boot sector at **4300h** after writing `0` to
  port **9Ch** (switches the boot ROM out). Floppy controller registers are at
  ports around **F0–F4** (command/status, track, sector, data, drive-select);
  exact assignments must be confirmed from the Model 4 Technical Reference Manual.
- 4P drives: 5.25" double density, 256 bytes/sector, 18 sectors/track (LS-DOS
  boot disks use this layout). Track count (40 vs 80) and sides must be confirmed
  on the owner's drives.
- TRSDW targets **LS-DOS 6.3.1** and uses **DriveWire4** as the host server at
  19.2k baud (needs a `master.xml` edit); its docs do not mention the 4P. Install:
  copy `TRSDW/DCT` to the boot floppy, then `system (drive=6,driver="trsdw")`.
  It has no timeouts or retries — a stuck transfer needs a reboot.
- Serial reception/transmission by the 4P after the ROM loader runs relies on
  the UART the ROM configured (8 data bits, odd parity, rate found = 19200).
- **LS-DOS 6.3.1 licensing is unclear.** No explicit free-distribution license was
  found. The owner supplies the image (or confirms its source); this project
  does not bundle it. A GitHub repo (GmEsoft/LSDOS631L) carries 6.3.1 sources and
  disk images; the owner decides whether and how to use it.

## Approaches considered

1. **Serial-delivered floppy writer (chosen).** `trs80boot.py` loads a Z80
   program that receives an LS-DOS image over serial and writes it to the 4P's
   drive 0 (formatting as needed). Later boots are from that floppy. Trade-off:
   needs direct floppy-controller programming and a format/write routine, and
   sacrifices one floppy. Least risky; well-understood hardware.
2. **Floppy-less RAM boot with a serial disk driver.** Best fit for the final
   FujiNet goal but undocumented and needs deep LS-DOS boot work. Deferred.
3. **Raw file transfer only, no DOS.** Easy, but does not deliver LS-DOS.

The owner chose approach 1 (agreed after stating no boot disks and no other way
to write floppies).

## Design (approach 1)

Stages, each independently testable on the real 4P:

1. **Link check after load (host→4P direction).** Extend the test program to
   echo bytes received on the UART, to prove the 4P can receive after the ROM
   loader. Needed before any bulk transfer. Add flow control: the 4P ROM/UART
   has no hardware handshake, so the protocol must be host-paced and
   acknowledged (e.g. host sends a block, 4P replies ACK/NAK with a checksum).
2. **Floppy writer (Z80 program) + host driver.** The Z80 program: reads/writes
   the floppy controller directly (seek, format-track, write-sector, read-back
   verify), speaks a simple block protocol over the UART (command, track,
   sector data, 16-bit checksum, ACK/NAK, retry). The host script reads a disk
   image, converts it to track/sector order for the writer, sends it, and
   confirms by reading every sector back and comparing.
3. **Boot test.** Power-cycle the 4P with the floppy in drive 0; it should
   boot LS-DOS 6.3.1 to the `LS-DOS Ready` prompt.
4. **TRSDW install.** Add `TRSDW/DCT` (and any config needed) to the disk as
   part of the image build (modify the image on Linux before writing), or copy
   it later via a serial transfer. Then `system (drive=6,driver="trsdw")` at the
   LS-DOS prompt, and run a DriveWire-compatible server on Linux.
5. **Host server.** Use DriveWire4 (set to 19.2k baud) if it works on this
   Linux machine; otherwise a small Python DriveWire-protocol server serving
   `.dsk` images. Decision belongs to the builder after trying DriveWire4.

## Image format

The host side needs a tool that turns an LS-DOS disk image (likely DMK, JV3 or
raw/`.DSK`) into the 40-track × 18-sector × 256-byte (to be confirmed) double
density layout the 4P's drive expects, including the correct sector numbering/
interleave LS-DOS uses. Accept at least the format the owner's image arrives in.

## Parts decided

- Approach 1 (floppy written via serial), single floppy, owner consent given.
- Chosen host language: Python 3, no external dependencies where possible
  (matches existing script).
- Serial format 8O1/8O2 for the ROM stage; after load the program uses
  whatever the ROM left configured unless it reprograms the UART.
- Verification by read-back, not by assumption.

## Left to the builder

- Exact floppy-controller port map and command sequences (from the Model 4
  Technical Reference Manual).
- Block protocol details, checksum, retry policy, block size.
- UART reprogramming vs relying on ROM configuration; baud rate for bulk transfer.
- Whether to keep 19.2k for the writer or negotiate a faster rate.
- DriveWire4 vs. own server; how TRSDW is added to the disk (image edit vs. copy later).
- Test-program changes needed; project layout.

## Calls made after builder review (assistant's calls, open to correction)

- **Disk layout fidelity.** The writer reproduces the **image's own track layout**
  (per-track density, sector IDs, interleave, sides), not just logical data. DMK
  carries this explicitly, so DMK is the preferred input format. Track 0 may be
  single density and the rest double density on LS-DOS disks; the builder must
  read this from the image rather than assume it. Read-back verification compares
  what the controller returns against the image, per track.
- **Boot path.** Normal power-on boot with the written disk in drive 0: the 4P boot
  ROM loads the boot sector and jumps to 4300h. LS-DOS 6.3.1 is a Model 4 OS, so
  the target is Model 4 mode only. The owner's machine is a true 4P with the
  boot ROM present (it runs the ROM serial loader).
- **Drive probe before any write.** A read-only first stage reports drive
  presence/numbering, track count, and sides by seek and read. Nothing is written
  until the probe has run and the host script has printed the target drive and
  asked for a typed confirmation that it will be erased. The Z80 writer refuses to
  write unless it receives an explicit write command for that session.
- **Stage 1 is a hard gate.** Host→4P reception after the ROM loader must be
  proven (with checksummed, acknowledged blocks) before the floppy writer is
  built. Fallback if it fails: reprogram the UART directly, then re-evaluate.
- **TRSDW is best-effort, file transfer over serial is required.** The required
  outcome is a working way to move programs and files to the 4P over serial. TRSDW
  + DriveWire is the preferred route (and FujiNet-friendly) but its 4P support is
  unverified; if it fails, fall back to a simpler serial file-transfer tool.
- **Adding TRSDW to the disk.** Prefer copying it onto the booted LS-DOS system
  over serial (host script + a small receiver on the 4P), over editing the image's
  file system on Linux. Edit the image only if the builder finds that easier.
- **Test strategy.** Host-side conversion, protocol, and image parsing get unit
  tests without hardware. Z80 floppy code is tested on the real 4P; plan writes
  against the agreed floppy only, after the read-only probe passes.

## Owner's answers

- **LS-DOS source:** the owner has no copy and approved downloading from
  `GmEsoft/LSDOS631L`. The README states MISOSYS grants free permission to
  download and use the software (notice must be retained). Downloaded to
  `images/lsdos631l-upstream/` (kept with its README and LICENSE; treat as
  untrusted data, never executed on the host):
  `LD4-631.DSK`, `LD4-631L.DSK`, `L631NEW.DSK` — DMK format, 505,616 bytes each,
  header says 40 tracks / 6400-byte track length. The file size does not match the
  header exactly (expected 512,016 for 40 double-sided tracks), so the builder must
  parse the image rather than trust the header. Which of the three is the right
  bootable system disk is **not yet confirmed** (README calls `L631NEW.DSK` a bootable
  disk meant to receive new binaries; the `LD4-*` names are unexplained). The
  builder must inspect the images' contents and choose.
- **Floppies:** the owner has a couple of floppies and agreed the 4P itself may
  format and write them. That gives spare disks for testing the writer.
- **Drive geometry** (40/80 track, sides) is still to be found by the read-only
  probe stage.

## Findings (recorded during implementation)

- **Image layout (Task 5, measured from `LD4-631.DSK`, `LD4-631L.DSK`, `L631NEW.DSK`;
  identical geometry in all three):** DMK header says 40 tracks / 2 sides / 6400-byte
  records; 79 of 80 records are present (cyl 39 side 1 is missing from the file). Side 0
  carries all the data: 40 cylinders, **18 sectors per track, 256 bytes, all MFM
  (double density, including track 0)**, normal data address marks (FB), sector
  numbers **0–17** (not 1–18). Sectors are interleaved and skewed per track (cyl 0
  order `0 9 1 10 2 11 …`, cyl 1 starts at 5, cyl 17 at 4, cyl 39 at 6). Side-1 tracks
  are present in the file but contain no sectors. Every ID and data CRC is valid.
  Consequence: the writer reproduces each track's sector order exactly and **skips
  tracks with no sectors**; a single-sided 40-track disk is what gets written.
- **Write Track cannot carry arbitrary data (Task 8):** the WD179x treats data bytes F5/F6/F7 as
  sync/CRC commands. 397 of 720 sectors in `LD4-631.DSK` contain them. So each track is formatted with
  filler (E5) from the image's layout and every sector is then written with Write Sector, which
  accepts any byte; everything is read back and compared.
- **Drive 0 (Task 7, measured on the owner's 4P):** ready, MFM, 40 tracks (highest readable track 39).
- **File system (Task 9, `trs80/lsdosfs.py`):** directory cylinder = byte 2 of the boot sector (20 on all
  three images); GAT at sector 0, HIT sector 1, directory from sector 2; 3 granules per cylinder, 6 sectors
  per granule; extents run across cylinder boundaries.
- **Chosen image: `L631NEW.DSK`.** All three are bootable by our check (boot sector `00 FE 14`, `SYS0/SYS`
  present) and differ only in `BOOT/SYS` (and `SYSTEM/JCL` exists only on `LD4-631`). The upstream README
  describes `L631NEW` as the bootable disk meant to receive new binaries; it is also the smallest.
  Fallback if it does not boot on the 4P: `LD4-631.DSK`. **All three disks are full** (0-1 of 120 granules
  free), so adding TRSDW will require deleting non-essential files (Task 11/12).
