# FujiNet RS-232: boot and run LS-DOS on the 4P with no floppy media

> Status: roadmap, not yet a task-by-task plan. Turn each phase into a TDD plan (superpowers:writing-plans) when starting it.
> Written 2026-11-16 to keep the owner's ideas from getting lost. Longer-term hardware idea: `2026-11-16-bus-card-longterm.md`.

## Goal

A TRS-80 Model 4P with **no diskettes at all** boots from a FujiNet device on its RS-232 port, running the
**fujinet-nio** firmware. The 4P receives a **CONFIG** program over serial; CONFIG mounts disk images (from the
FujiNet's SD card or network shares) and LS-DOS 6.3.1 then runs with those images as its drives. Physical floppy
drives, if present, stay usable as ordinary drives (reading/writing real diskettes).

Why: many 4P owners have no working diskettes and no way to make one. The ROM's serial loader is the one
media-free entry point, so everything starts there.

Analogy: the CoCo FujiNet loads HDB-DOS from a cartridge ROM and then talks DriveWire over serial. The 4P has no
such ROM; its ROM only has a serial **loader**, so the "driver" must be sent into RAM on every boot.

## What exists already (this repo, working on real hardware)

- ROM serial boot: handshake 0x55/0xFF at 19200 baud, 8 data bits, odd parity; load-module stream (`trs80/lmf.py`, `trs80boot.py`).
- Resident monitor (`z80/mon.asm`, 6000h) with framed commands PING / WRITE_MEM / READ_MEM / EXEC / IN / OUT; host library `trs80/monitor.py`.
- WD1773 floppy routines (`z80/fdc.asm`), floppy writer (`writedisk.py`), verified LS-DOS 6.3.1 boot from a floppy written over serial.
- LS-DOS file-system code (`trs80/lsdosfs.py`: read/list/add/delete files in DMK images).
- `SERIAL/CMD` + `trs80put.py`: copy files onto the floppy once LS-DOS runs (written, awaiting the owner's hardware test).
- Technical references on disk: `images/ref-m4tech/m4tech.txt` (Model 4 manual incl. LS-DOS SVC numbers, FCB layout, UART ports).

## Known facts and constraints

- 4P UART: ports E8 (reset), E9 (baud: 0xFF = 19200 both ways), EA (control: 0x67 = 8 bits, odd parity, 1 stop, DTR+RTS), EB (data). **19200 baud is the maximum**, about 1.9 KB/s, about 140 ms per 256-byte sector in practice.
- The ROM serial loader accepts only a load-module stream; the FujiNet must play the *host* (send 0x55 until "Found Baud Rate", then 0xFF, then the stream). Our host side is `trsboot`/`trs80boot.py`: use it as the reference implementation.
- The FujiNet RS-232 device has level shifting built in (owner). Cable crossover/null-modem details still to confirm (the FujiNet plays DTE for boot).
- LS-DOS's own boot code reads the boot track by talking to the floppy controller directly. So "boot LS-DOS from a virtual disk" cannot rely on a driver being swapped in underneath it.
- LS-DOS user memory starts at 3000h, system overlays live at 2600h-2FFFh; our monitor sits at 5F00h-70FFh, FDC/DOS helper routines at 8000h, parameter block at 9F00h.

## Open questions (answer these first; each is a research task, not an assumption)

1. **fujinet-nio protocol.** What does fujinet-nio speak over RS-232? DriveWire-compatible, FujiNet's own bus protocol, or something new? Is there any TRS-80 / DriveWire / "boot over RS-232" support in the repo? What does CONFIG look like on other platforms, and how is it delivered?
2. **Can the FujiNet act as the ROM loader's host?** It must detect the handshake and stream a load module at 19200 8O1, with odd parity.
3. **Floppy-less LS-DOS start-up.** Can LS-DOS 6.3.1 be brought up from RAM with a serial disk driver as drive 0, never touching the floppy controller? Candidate designs below.
4. **Licensing/availability** of anything reused (TRSDW has no stated licence and is only offered through a Google Drive folder; do not depend on it).
5. **FujiNet side:** who writes it? If we only write the 4P side, what is the minimum the firmware must provide (a block read/write service plus mount/unmount)?

## Design decision still to make: how LS-DOS gets a serial drive 0

- **A. Boot stub (preferred to try first).** CONFIG (loaded over serial) reads LS-DOS's boot sector and system files from the mounted image, places them in RAM exactly as LS-DOS's own boot sequence would, installs a serial disk driver, and jumps to the system. The 4P-side parser of the disk image can reuse the `lsdosfs.py` logic (re-implemented in Z80, or done host-side by the FujiNet and sent as a ready-made memory image).
- **B. Patched boot path.** Modify BOOT/SYS and/or SYS0 so every floppy access in the boot sequence goes through a serial driver. More invasive; needs a disassembly of the boot chain.
- **C. Interim, not self-contained:** boot from a tiny floppy and install a serial driver via LS-DOS's `SYSTEM` command (like TRSDW). Useful for developing the driver; does not meet the goal.

## Phases

### Phase 0 — finish what is in flight (owner hardware test)
- Owner writes `images/boot.dsk` (two tracks) and tests `SERIAL` + `trs80put.py` (see README). Confirms the LS-DOS SVC-based file writing on real hardware.
- Done when: a file sent from the PC appears in `DIR :0` on the 4P with the right contents.

### Phase 1 — research (no hardware)
- Read fujinet-nio: serial protocol, device model, mounting, CONFIG, build targets; record findings in the design doc's "Findings".
- Read the DriveWire protocol spec as a baseline; decide the block protocol (see Phase 2).
- Disassemble/trace the LS-DOS boot chain from the images we have (boot sector -> BOOT/SYS -> SYS0/SYS) to settle decision A vs B. The emulator in `tests/z80emu.py` and the DMK tools can run pieces of it.
- Done when: a written recommendation for the boot approach and the wire protocol, with the owner's sign-off.

### Phase 2 — block protocol and 4P-side driver, serial transport
- Define a small request/response block protocol: read sector, write sector, mount info, with checksums and retries (our monitor framing in `trs80/frames.py` is a starting point; or reuse the FujiNet's protocol if it fits).
- Layering on the 4P: **transport** (serial now, bus later) under **block protocol** under the **LS-DOS driver**. Keep the transport swappable; this is what lets the bus card (see the long-term doc) reuse everything above it.
- PC-side test server: a Python program that serves disk images over the protocol (stands in for the FujiNet during development, like a DriveWire server).
- Test with the Z80 interpreter plus a fake LS-DOS before touching hardware, as with `FakeDos`.
- Done when: a 4P with LS-DOS booted from a floppy can mount a PC-served image as an extra drive and `DIR` it (interim approach C, for development).

### Phase 3 — floppy-less boot
- Implement the chosen boot approach (A or B). Boot LS-DOS to the date prompt with no floppy in the machine; `DIR`, run programs.
- Done when: power on, send nothing but what the FujiNet sends, reach the LS-DOS prompt with the 4P having no disk media.

### Phase 4 — CONFIG and the FujiNet side
- CONFIG on the 4P: list images, mount/unmount to drive numbers, choose the boot image; the physical floppies remain drives 0-3 as today unless remapped.
- Integrate with fujinet-nio (device protocol, SD card, network shares). Decide who owns which code.

### Phase 5 — polish
- Speed: bigger transfers per request, read-ahead/cache on the FujiNet, avoid per-sector round trips. 19200 baud caps this; the bus card removes the cap.
- Modem mode on the same port after boot (also covered in the long-term doc).

## Risks

- Phase 3 may force a substantial patch of LS-DOS's boot chain (decision B), or prove infeasible with this ROM; fallback is interim approach C plus a one-time floppy, which does not meet the goal.
- 19200 baud makes a virtual drive slow (a full boot may take a minute or more).
- fujinet-nio may not target this machine; the work could mean contributing firmware, not just 4P code.
- LS-DOS licensing for distributing the images: we use `GmEsoft/LSDOS631L` (see its LICENSE); check what may be redistributed with a FujiNet image set.

## Deliverables per phase

Each phase ends with: tests (emulator-based where possible), README section, committed code, a ledger line, and the owner's hardware confirmation for anything touching the 4P.
