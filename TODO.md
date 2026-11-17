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
