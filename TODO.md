# TODO

## TRS-80 disk image formats (.dsk JV3 and .dmk) in fujinet-nio

fujinet-nio serves a mounted image file as raw bytes (LBA * sector size). TRS-80 images are usually JV3 (`.dsk`) or DMK (`.dmk`),
so `FMOUNT :1 tnfs://.../Spro.dsk` mounts without error and then `DIR :1` hangs, because LS-DOS reads header bytes where it
expects the directory (found 2026-11-17 with `tnfs://fujinet.skdev.org/tandy/trs80-4/Spro.dsk`, a JV3 file).

- [ ] Read-only JV3 support: detect by content (`.dsk` is ambiguous; a raw image or an Apple/CoCo image can have the same name),
      build the sector map from the 2901 headers, answer reads by cylinder and sector. Reference: `trs80/jv3.py`, `tests/test_jv3.py`.
- [ ] Read-only DMK support (reference for the layout: `trs80/dmk.py` and `trs80.lsdosfs.flat_image`).
- [ ] Writes for both formats, including updating the JV3 headers where needed.
- [ ] Double-sided images, sector sizes other than 256, and a CRC-error flag: report or refuse clearly instead of serving wrong data.
- [ ] A sector-size hint for the boot mount (`boot.config_uri`), so a raw `.img` can be the boot disk; today it needs the `.xfd` name.
- [ ] Open an upstream issue in fujinet-nio first (TRS-80 platform, the formats above, the boot-mount hint), then a branch there.
      Read fujinet-nio's disk service code to scope it; the first step is checking how tied the read path is to a flat layout.
- [ ] Meanwhile: `tools/jv3_to_img.py` converts JV3 to a raw image; a DMK-to-raw tool is not written yet.

## Resident driver is too big for programs that want the top of memory (SuperScripsit)

Found 2026-11-17 on the real 4P and reproduced in MAME (`SCRIPSIT :1` from `scripsit-v1.00.09.img`, a raw 720 x 256 image):
it prints "Not enough memory is available to use SuperScripsit". `SCR17/CTL` asks @HIGH$ (SVC 100) and fails (error A2h) if the answer is
below EFFFh. Stock LS-DOS 6.3.1 reports FFFFh. Our boot driver sits at E000h (HIGH$ = DFFFh), and `FUJIDRV :1` then installs a second
copy just below it (HIGH$ = D736h), so the program refuses to start. With the constant patched down to C000h the check passes, but the
program then takes the whole machine down (it uses memory we hold), so lowering the check is not a fix.

- [ ] One resident copy for all drives: `FUJIDRV` should point the drive's DCT at the driver already resident (floppy-less boot) and
      derive the slot from the drive number, instead of copying the 2.2 KB driver again for every drive. Frees 2.2 KB per extra drive.
- [ ] Get HIGH$ to EFFFh or higher: the resident part must fit in 1 KB at F000h-F3FFh (F400h and up is keyboard/video), or the
      programs that check HIGH$ will not run. Measure what the minimum core (read, write, SLIP, FujiBus, UART) costs; clock, boot and
      CONFIG-only code is not resident already.
- [ ] Unexplained: the real 4P showed a screen of garbage above the message; MAME shows only the message. Check what the splash
      leaves in video memory on real hardware once the memory question is settled.
