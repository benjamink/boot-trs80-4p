# LS-DOS Serial Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From this Linux machine, over the serial cable only, write a bootable LS-DOS 6.3.1 floppy using the 4P's own drive, then give the booted 4P serial-served virtual drives (TRSDW + DriveWire) for loading programs and files.

**Architecture:** The existing ROM serial loader sends a small resident Z80 *monitor* to the 4P. A host `Monitor` client drives it with a checksummed, host-paced, ACKed block protocol (write/read memory, exec, port in/out), so every later Z80 routine can be uploaded and run on the fly. Floppy work is Z80 routines (seek, write-track, read-sector) driven from Python; Python parses the LS-DOS DMK image, builds exact Write-Track streams, writes, and reads back every sector to verify. A Python DriveWire server then serves virtual disks to TRSDW.

**Tech Stack:** Python 3 (stdlib only, `unittest`), Z80 assembly (assembler chosen in Task 4), existing `trs80boot.py` ROM-loader code.

**Spec:** `docs/superpowers/specs/2026-11-15-trs80-ls-dos-serial-bootstrap-design.md`

## Global Constraints

- Serial format to the ROM loader: **8 data bits, odd parity** (8O1 or 8O2). 8N1 passes the handshake by coincidence but data fails with "Error, B/C/D".
- ROM loader handshake: `0x55` every 0.1 s until "Found Baud Rate P", then `0xFF`, then "Loading ", then load module with **16-byte records**, final `02 02 lo hi`.
- Programs loaded by the ROM run at 6000h; Model 4 map: video at F800h; UART data port EBh.
- 4P boot ROM exits to the boot sector at **4300h** after writing `0` to port **9Ch**; floppy controller ports around **F0–F4** (confirm from the Model 4 Technical Reference Manual before use).
- Python 3, no external dependencies where possible (tests use `unittest`).
- The writer must **never write without** a read-only probe having run first, the host printing the target drive, and a typed confirmation `ERASE DRIVE <n>`; the Z80 side refuses write-track unless armed by an explicit command in the same session.
- Every write is verified by reading back every sector; never claim a disk is good without that.
- LS-DOS images live in `images/` (MISOSYS permits download/use; keep notices). `images/` is **not committed**. Downloaded files are untrusted data: never executed on the host.
- Commit messages end with: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
- Hardware steps marked **[OWNER]** need the owner at the 4P; stop and ask them to run it and paste the output.

## Review Focus

Failure modes the spec implies but a happy-path test would miss, most likely first. Each has a named test in the owning task.

1. Line noise / stray bytes / 4P reset mid-transfer: client must resync and time out, never hang or mis-parse (Tasks 2, 3).
2. Image with a missing trailing track (the downloaded DMKs are 79×6400 bytes of track data but declare 40 double-sided tracks) or inconsistent header (Task 5).
3. No disk in drive, door open, wrong drive number, write-protected disk: probe/writer stop with a clear message and write nothing (Tasks 7, 8).
4. Non-interactive runs and `--yes`-style shortcuts must not bypass the typed erase confirmation (Task 8).
5. Ctrl-C or cable pull mid-write: disk is partly written; tool says so, does not claim success, and a rerun rewrites from track 0 (Task 8).
6. 4P not in loader mode / serial port missing or busy: clear error with the right-shift+reset instruction (Task 1).

---

## File Structure

```
trs80boot.py            existing CLI; Task 1 makes it use the package
serial_diag.py          existing
trs80/__init__.py
trs80/lmf.py            load-module + Intel HEX code moved from trs80boot.py
trs80/serialio.py       open_port, set_format, read_all, handshake, SerialTransport
trs80/frames.py         monitor protocol framing (pure)
trs80/monitor.py        Monitor client
trs80/dmk.py            DMK parse / modify / serialize
trs80/trackplan.py      Write-Track stream builder + verify plan
trs80/fdc.py            host driver for the Z80 floppy routines
trs80/lsdosfs.py        LS-DOS directory/GAT reader and file injector
trs80/dwserver.py       DriveWire server
z80/mon.asm             resident monitor (org 6000h)
z80/fdc.asm             floppy routines (uploaded at 8000h)
trs80mon.py             CLI: boot, ping, peek, poke, exec, load
writedisk.py            CLI: probe / dry-run / write+verify
tools/monstress.py      hardware gate stress test
tests/test_*.py, tests/fake4p.py, tests/fakefdc.py
Makefile                assembles z80/*.asm -> build/*.hex
README.md
```

---

### Task 1: Repo, package, characterization tests

**Files:**
- Create: `.gitignore` (`images/`, `build/`, `__pycache__/`), `trs80/__init__.py`, `trs80/lmf.py`, `trs80/serialio.py`, `tests/test_lmf.py`
- Modify: `trs80boot.py` (import from package; keep every CLI flag and behavior)

**Interfaces:**
- Produces (`trs80/lmf.py`): `lmf_data_block(addr:int, data:bytes) -> bytes`, `lmf_entry(addr:int) -> bytes`, `build_lmf(segments:dict[int,bytes], entry:int, block:int=16) -> bytes`, `parse_hex(path:str) -> tuple[dict[int,bytes], int|None]`
- Produces (`trs80/serialio.py`): `FORMATS`, `open_port(dev:str, baud:int) -> int`, `set_format(fd:int, baud:int, fmt:str) -> None`, `read_all(fd:int, wait:float=0.0) -> bytes`, `handshake(fd:int, baud:int, formats:list[str], timeout:float|None=None) -> str` (raises `LoaderNotReady` after `timeout` with message naming right-shift+reset), `class SerialTransport(fd)` with `write(data:bytes)` and `read(timeout:float) -> bytes`.

- [ ] **Step 1: `git init`; write `.gitignore`; commit the existing files as the baseline.**
- [ ] **Step 2: Write tests in `tests/test_lmf.py`:** `test_build_lmf_16_byte_records` (140-byte program → every `01` record has len ≤ 18 and ends with `02 02 00 60`), `test_parse_hex_scrdump` (`examples/SCRDUMP.HEX` → one segment at 0x6000 of 156 bytes, entry 0x604B), `test_parse_hex_bad_checksum_exits`, `test_test_program_matches_known_bytes` (fixed hex of the current `--test` load module, so refactors can't change it).
- [ ] **Step 3: Run `python3 -m unittest discover -s tests`; expect failures (modules missing).**
- [ ] **Step 4: Move code into the modules, update `trs80boot.py` imports; add the `timeout` to `handshake` and `LoaderNotReady`.** Test `test_handshake_times_out` uses a pty pair with no responder and `timeout=0.5`.
- [ ] **Step 5: Run all tests; expect PASS. Run `./trs80boot.py --help` and `python3 -I -c "import ast;ast.parse(open('trs80boot.py').read())"`.**
- [ ] **Step 6: Commit** `refactor: move loader code into trs80 package`.

---

### Task 2: Monitor frame protocol (pure)

**Files:** Create `trs80/frames.py`, `tests/test_frames.py`

**Interfaces:**
- Produces: constants `SYNC_REQ=0xA5`, `SYNC_RSP=0x5A`, `CMD_PING=1`, `CMD_WRITE_MEM=2` (payload addr_lo,addr_hi,data…), `CMD_READ_MEM=3` (addr_lo,addr_hi,n), `CMD_EXEC=4` (addr_lo,addr_hi; response payload = A,F,B,C,D,E,H,L after the routine returns), `CMD_IN=5` (port), `CMD_OUT=6` (port,value), `ST_OK=0`, `ST_BAD_CHECKSUM=1`, `ST_BAD_COMMAND=2`, `MAX_PAYLOAD=250`.
- `checksum(data:bytes) -> int` = sum mod 65536 of bytes from the cmd/status byte through the payload.
- `encode_request(cmd:int, seq:int, payload:bytes=b"") -> bytes` = `A5 cmd seq len payload ck_lo ck_hi`; `encode_response(status:int, seq:int, payload:bytes=b"") -> bytes` = `5A status seq len payload ck_lo ck_hi`. Raise `ValueError` if payload > `MAX_PAYLOAD`.
- `@dataclass Parsed(code:int, seq:int, payload:bytes, consumed:int, ok:bool)`; `parse_frame(buf:bytes, sync:int) -> Parsed|None` — skips bytes before `sync`, returns `None` if the frame is incomplete, `ok=False` on bad checksum (`consumed` always advances past the bad frame).
- Monitor behavior this implies (implemented in Task 4): mid-frame idle >~50 ms aborts the partial frame and returns to hunting for `A5`; a repeated `seq` returns the stored previous response without re-executing.

- [ ] **Step 1: Tests:** `test_roundtrip_all_commands`, `test_checksum_known_value` (e.g. PING seq 1 payload `01 02` → bytes `A5 01 01 02 01 02 07 00`), `test_bad_checksum_flagged_and_consumed`, `test_garbage_prefix_skipped`, `test_incomplete_returns_none`, `test_payload_too_long_raises`, `test_two_frames_back_to_back`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement the functions above. Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: monitor frame protocol`.

---

### Task 3: Monitor client + fake 4P

**Files:** Create `trs80/monitor.py`, `tests/fake4p.py`, `tests/test_monitor.py`

**Interfaces:**
- Consumes: `trs80.frames`; transport with `write(data:bytes)->None` and `read(timeout:float)->bytes` (b"" on timeout).
- Produces: `class MonitorError(Exception)`; `class Monitor(transport, timeout:float=0.5, retries:int=5)` with `ping(payload:bytes=b"") -> bytes`, `write_mem(addr:int, data:bytes) -> None` (chunks of ≤248), `read_mem(addr:int, n:int) -> bytes` (chunks of ≤250), `exec(addr:int) -> dict[str,int]` (keys `A F B C D E H L`), `port_in(port:int) -> int`, `port_out(port:int, value:int) -> None`. Sequence numbers wrap at 256; retry resends the **same** seq.
- Produces (`tests/fake4p.py`): `FakeFourP` implementing the transport on the 4P side with 64 KiB memory, the duplicate-seq rule, `exec_handlers:dict[int,callable]`, `exec_count:dict[int,int]`, and fault hooks `drop_next_response()`, `corrupt_next_response()`, `inject_garbage(bytes)`.

- [ ] **Step 1: Tests:** `test_ping_echo`, `test_write_read_64k_roundtrip`, `test_retry_on_dropped_response`, `test_retry_on_corrupt_response`, `test_duplicate_seq_not_reexecuted` (EXEC with dropped response runs the handler once), `test_resync_after_garbage_between_frames`, `test_timeout_raises_monitor_error` (fake never answers), `test_exec_returns_registers`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement `Monitor` and `FakeFourP`. Step 4: Run; expect PASS. Step 5: Commit** `feat: monitor client with fake 4P`.

---

### Task 4: Z80 monitor + hardware gate [OWNER]

**Files:** Create `z80/mon.asm`, `Makefile`, `trs80mon.py`, `tools/monstress.py`; Modify `trs80/serialio.py` (add `SerialTransport` if not complete)

**Interfaces:**
- Consumes: Task 2 protocol, Task 3 `Monitor`.
- Produces: `build/mon.hex` (org 6000h, ≤0x400 bytes, stack 7000h downward, free user RAM 8000h–EFFFh, entry 6000h); `trs80mon.py` subcommands `boot` (handshake, send `build/mon.hex`, then ping), `ping`, `peek ADDR N`, `poke ADDR HEX`, `exec ADDR`, `load FILE.hex|FILE.cmd` (upload and exec entry), all with `-p PORT`.

- [ ] **Step 1: Pick the assembler.** Run `which sjasmplus z80asm zmac`. If none exists, ask the owner before installing one (suggest `sjasmplus` via AUR); the fallback is extending the in-repo `Asm` class. Record the choice in `README.md`. `Makefile` target `build/%.hex: z80/%.asm` must produce Intel HEX; `trs80boot.py ... --entry 0x6000` loads it (HEX without a type-03 record uses `--entry`).
- [ ] **Step 2: Find the UART programming in the Model 4 Technical Reference Manual** (`https://electrickery.hosting.philpem.me.uk/comp/trs80-4p/doc/Model_4_Technical_Reference_Manual_1985_Tandy.pdf`): confirm ports E8–EB, the status-bit meanings (receive-ready, transmit-empty, error flags) and that the monitor must **not** reset the UART (the ROM already set 19200, odd parity). Write the findings as comments at the top of `z80/mon.asm`.
- [ ] **Step 3: Implement `z80/mon.asm`** per Task 2 behavior (idle timeout, stored last response for duplicate seq, status 1 on bad checksum, status 2 on unknown command, EXEC via CALL then send A,F,B,C,D,E,H,L). `make` must build it.
- [ ] **Step 4: Write `tools/monstress.py`:** 500 random-length pings, a 16 KiB write/read verify at 8000h, 50 `port_in(0xEA)` reads, and an EXEC of a hand-poked `LD A,42h / RET`; print counts of retries and failures; exit non-zero on any failed operation.
- [ ] **Step 5: [OWNER] Boot and gate.** Owner: right-shift+reset until "Ready", then `./trs80mon.py boot`. Expect a ping reply; then `python3 tools/monstress.py`. **Pass: zero failed operations** (a few retries are acceptable; report the counts). If reception fails, stop: reprogram the UART directly per the spec's fallback and re-run; do not start Task 7 until this passes.
- [ ] **Step 6: Commit** `feat: resident Z80 monitor and serial gate`.

---

### Task 5: DMK parser/serializer

**Files:** Create `trs80/dmk.py`, `tests/test_dmk.py`

**Interfaces:**
- Produces: `@dataclass Sector(cyl:int, side:int, num:int, size:int, dam:int, data:bytes, density:str, id_crc_ok:bool, data_crc_ok:bool)` (`density` is `"FM"` or `"MFM"`, from the IDAM pointer bit 15); `@dataclass Track(cyl:int, side:int, present:bool, sectors:list[Sector])`; `class DmkImage` with `tracks:int`, `sides:int`, `track_len:int`, `get(cyl:int, side:int) -> Track`, `set_sector_data(cyl:int, side:int, num:int, data:bytes) -> None` (recomputes the data CRC, CRC-16/CCITT over DAM+data), `to_bytes() -> bytes`; `parse_dmk(data:bytes) -> DmkImage`.

- [ ] **Step 1: Tests on synthetic images built in the test:** `test_parse_single_track_mfm`, `test_fm_track_density`, `test_missing_trailing_track_marked_not_present` (header says 40 tracks, file holds 79 track images), `test_bad_data_crc_flagged`, `test_set_sector_data_recomputes_crc_and_roundtrips`, `test_truncated_header_raises`, `test_to_bytes_roundtrip_identity`.
- [ ] **Step 2: Test on the real images (skip if absent):** `test_real_images_parse` loops over `images/lsdos631l-upstream/*.DSK`, asserts every present sector has both CRCs ok, and prints a layout report (track 0 density, sectors per track, sector size, DAM values) to the test log.
- [ ] **Step 3: Run; expect FAIL. Step 4: Implement. Step 5: Run; expect PASS.**
- [ ] **Step 6: Record the observed real layout** (track 0 density, sector numbering/interleave, which tracks use deleted DAMs) in a "Findings" section appended to the design doc. **Step 7: Commit** `feat: DMK parser`.

---

### Task 6: Write-Track stream builder

**Files:** Create `trs80/trackplan.py`, `tests/test_trackplan.py`

**Interfaces:**
- Consumes: `trs80.dmk.Track`.
- Produces: `build_write_track(track:Track) -> bytes` — the byte stream for the WD179x Write Track command, using F5 (A1 sync), F6 (C2 sync), F7 (write CRC) codes for MFM and raw marks/F7 for FM; reproduces each sector's exact ID (cyl, side, num, size code), DAM value (FB or F8), and order from the image. `verify_plan(track:Track) -> list[tuple[int,int,bytes]]` — `(sector_num, size, data)` to read back. Raises `ValueError` if the stream would exceed the track-image length.

- [ ] **Step 1: Tests:** `test_mfm_18x256_structure` (before each IDAM exactly `F5 F5 F5 FE`, before each data `F5 F5 F5 FB`, one `F7` after each ID field and each data field, 18 sectors in the image's order), `test_fm_track_uses_no_f5_and_has_fc_index`, `test_deleted_dam_f8_preserved`, `test_non_default_interleave_preserved`, `test_oversize_track_raises`, `test_verify_plan_matches_image_data`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement using the WD1793 data sheet's format tables (gap sizes from the data sheet, recorded as constants with a comment citing the table). Step 4: Run; expect PASS. Step 5: Commit** `feat: write-track stream builder`.

---

### Task 7: FDC routines, host driver, read-only probe [OWNER]

**Files:** Create `z80/fdc.asm`, `trs80/fdc.py`, `tests/fakefdc.py`, `tests/test_fdc.py`; Modify `Makefile`

**Interfaces:**
- Consumes: `Monitor`, `trackplan`.
- Produces (Z80, uploaded at 8000h, fixed jump table at 8000h: `JP restore`, `JP seek`, `JP read_addr`, `JP read_sector`, `JP write_track`, `JP arm_write`): `restore` A=drive select → A=FDC status; `seek` A=track → A=status; `read_addr` HL=6-byte buffer → A=status; `read_sector` A=sector, HL=256…1024-byte buffer → A=status; `write_track` HL=buffer, BC=length → A=status, **returns immediately with an error code and writes nothing unless `arm_write` was called earlier in the same session**.
- Produces (Python): `@dataclass DriveInfo(drive:int, present:bool, max_track:int, sides:int, status_text:str)`; `class Fdc(mon:Monitor, hex_path:str="build/fdc.hex")` with `upload() -> None`, `probe(drive:int) -> DriveInfo` (**read-only**: restore, seek outward, read-address on both sides; never calls `arm_write`), `arm_write() -> None`, `write_track(drive:int, cyl:int, side:int, stream:bytes) -> int`, `read_sector(drive:int, cyl:int, side:int, sector:int, size:int, density:str) -> bytes` (raises `FdcError` on non-zero status).

- [ ] **Step 1: Read the Model 4 Technical Reference Manual's floppy section;** record the real port map, drive-select/side/density bits, and DRQ/INTRQ handling as comments in `z80/fdc.asm`. Confirm the port assumptions (F0–F4) or correct them here in the plan notes.
- [ ] **Step 2: Tests with `FakeFdc`** (a simulated drive implementing the same Python-facing calls): `test_probe_reports_geometry`, `test_probe_no_disk_reports_not_present_and_never_writes`, `test_probe_never_calls_arm_write`, `test_write_track_refused_when_not_armed`, `test_read_sector_error_raises_fdcerror`.
- [ ] **Step 3: Run; expect FAIL. Step 4: Implement `fdc.py` and `z80/fdc.asm`; `make`.**
- [ ] **Step 5: [OWNER] Probe.** Owner puts a scratch floppy in drive 0, boots the monitor, runs `./writedisk.py --probe-only` (CLI added in Task 8; for this step use `python3 -c` with `Fdc.probe(0)` printed). **Pass: prints present, track count, sides.** Owner states the drive label to cross-check.
- [ ] **Step 6: Commit** `feat: floppy routines and read-only probe`.

---

### Task 8: Writer CLI with safety

**Files:** Create `writedisk.py`, `tests/test_writedisk.py`

**Interfaces:**
- Consumes: `DmkImage`, `build_write_track`, `verify_plan`, `Fdc`, `Monitor`.
- Produces: `confirm_erase(drive:int, info:DriveInfo, input_fn, confirm_arg:str|None, interactive:bool) -> bool` (accepts only the exact text `ERASE DRIVE <n>`; non-interactive requires `confirm_arg` to equal it); `write_image(fdc:Fdc, image:DmkImage, drive:int, progress=print, retries:int=2) -> None` (for each present track: build stream, write, read back every sector, compare; retry the track up to `retries`, then raise `WriteVerifyError(cyl, side, sector)`); CLI flags `--image`, `--drive`, `-p/--port`, `--dry-run` (parse, plan, print; never opens the port), `--probe-only`, `--confirm TEXT`. No `--yes`.

- [ ] **Step 1: Tests with `FakeFdc`:** `test_dry_run_never_touches_serial_or_fdc`, `test_write_requires_probe_first`, `test_confirm_rejects_wrong_text`, `test_noninteractive_without_confirm_arg_refuses`, `test_noninteractive_with_exact_confirm_proceeds`, `test_verify_mismatch_retries_then_raises`, `test_keyboard_interrupt_reports_partial_disk_and_exit_code` (message says the disk is partly written, won't boot, rerun to rewrite from track 0; exit code non-zero), `test_image_track_not_present_is_skipped_and_reported`, `test_drive_not_present_refuses`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement. Step 4: Run; expect PASS. Step 5: Commit** `feat: safe floppy writer`.

---

### Task 9: LS-DOS filesystem reader

**Files:** Create `trs80/lsdosfs.py`, `tests/test_lsdosfs.py`

**Interfaces:**
- Consumes: `DmkImage`.
- Produces: `@dataclass FileEntry(name:str, ext:str, size:int, system:bool, first_granule:int)`; `list_files(img:DmkImage) -> list[FileEntry]`; `read_file(img:DmkImage, name:str) -> bytes`; `is_bootable(img:DmkImage) -> bool` (boot sector present and `SYS0/SYS` listed). Directory cylinder and granule geometry are read from the image, not assumed.

- [ ] **Step 1: Tests (real images, skip if absent):** `test_lists_known_system_files` (expect `SYS0/SYS`, `SYS1/SYS`, `BASIC`-independent core names; print the listing to the log), `test_read_file_matches_directory_size`, `test_is_bootable_distinguishes_images`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement from the LS-DOS 6.3.1 technical documentation and the GmEsoft sources' `DOSDEFS/ASM`. Step 4: Run; expect PASS.**
- [ ] **Step 5: Choose the image to write:** run `list_files`/`is_bootable` over `LD4-631.DSK`, `LD4-631L.DSK`, `L631NEW.DSK`; record the chosen image and why in the design doc's "Findings". **Step 6: Commit** `feat: LS-DOS directory reader`.

---

### Task 10: Write LS-DOS to a scratch floppy and boot it [OWNER]

**Files:** Modify `README.md` (exact procedure)

- [ ] **Step 1: Dry run:** `./writedisk.py --image images/lsdos631l-upstream/<chosen>.DSK --drive 0 --dry-run`; expect track count, per-track density/sector summary, no serial access.
- [ ] **Step 2: [OWNER] Write.** Owner inserts scratch floppy #1, boots the monitor (`./trs80mon.py boot`), runs `./writedisk.py --image ... --drive 0`, types `ERASE DRIVE 0`. **Pass: every track verified, summary "all sectors verified".**
- [ ] **Step 3: [OWNER] Boot.** Owner presses reset with the floppy in drive 0 (no right-shift). **Pass: LS-DOS prompt appears** and `DIR :0` lists files. Record exactly what the 4P shows. If it fails: capture the screen text, re-read `list_files` against what was written, check track 0 density/sector order against the image, and fix before moving on.
- [ ] **Step 4: Commit** `docs: write-and-boot procedure`.

---

### Task 11: File injector (add TRSDW to the image)

**Files:** Modify `trs80/lsdosfs.py`, `tests/test_lsdosfs.py`

**Interfaces:**
- Produces: `add_file(img:DmkImage, name:str, data:bytes) -> DmkImage` (returns a modified copy: allocates granules in the GAT, adds a directory entry, writes data sectors via `set_sector_data`); raises `DiskFullError`, `FileExistsError_` (name chosen by the builder consistently), `ValueError` on invalid LS-DOS names.

- [ ] **Step 1: Tests:** `test_added_file_reads_back_identical`, `test_other_files_unchanged_byte_for_byte`, `test_gat_allocated_granule_count_matches_file_size`, `test_duplicate_name_rejected`, `test_disk_full_raises`, `test_image_still_parses_with_valid_crcs`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement. Step 4: Run; expect PASS. Step 5: Commit** `feat: LS-DOS file injector`.

---

### Task 12: Obtain TRSDW and build the combined image

**Files:** Create `tools/make_boot_image.py`, `tests/test_make_boot_image.py`; downloads into `images/trsdw-upstream/` (its own new directory, untrusted, not executed)

- [ ] **Step 1: Find the real download link** on `https://sites.google.com/site/maboytim/home/trsdw` (the page text names `TRSDW/DCT`, `TRSDW/ASM`, `TRSDW.BAS` and a blank `header_cyl=202_dir=1.dsk` but gave no link; read the page HTML for hrefs). If the link can't be found or the license/permission isn't stated, stop and ask the owner.
- [ ] **Step 2: Read `TRSDW/ASM`:** record the DriveWire opcodes it uses, serial settings, and what it expects of the host in the design doc's "Findings" (this feeds Task 13).
- [ ] **Step 3: Test `test_combined_image_contains_trsdw_dct`** (uses a stand-in file if the real one is absent): `make_boot_image(base:str, dct:str, out:str)` adds `TRSDW/DCT` with `add_file` and the result lists it and still `is_bootable`.
- [ ] **Step 4: Implement `tools/make_boot_image.py`. Step 5: Run tests; expect PASS. Step 6: Commit** `feat: build boot image with TRSDW driver`.

---

### Task 13: DriveWire server

**Files:** Create `trs80/dwserver.py`, `tests/test_dwserver.py`, `trs80dw.py` (CLI: `--port`, `--baud 19200`, `--disk N=PATH`)

**Interfaces:**
- Consumes: opcodes and framing found in Task 12 Step 2.
- Produces: `class DriveWireServer(transport, disks:dict[int,str])` with `serve_once() -> None` (handle one request), `serve_forever() -> None`; supports at least the init, read (with checksum response), write, reset/nop and time requests TRSDW uses; unknown opcodes are logged and ignored, never crash the server. Disk images are read/written in place only at sector offsets inside the file (never extended past the header-declared size).

- [ ] **Step 1: Tests with a simulated TRSDW client byte stream:** `test_init_request_answered`, `test_read_sector_returns_256_bytes_and_checksum`, `test_write_sector_persists_to_image`, `test_read_past_end_returns_error_not_crash`, `test_unknown_opcode_ignored_and_server_continues`, `test_garbage_bytes_do_not_desync_next_request`, `test_two_drives_independent`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement. Step 4: Run; expect PASS. Step 5: Commit** `feat: DriveWire server`.

---

### Task 14: End-to-end on the 4P [OWNER] and README

**Files:** Modify `README.md`

- [ ] **Step 1: [OWNER] Write the combined image** (`tools/make_boot_image.py` output) to scratch floppy #2 exactly as in Task 10, then boot it to the LS-DOS prompt.
- [ ] **Step 2: [OWNER] Install and connect:** on the 4P type `system (drive=6,driver="trsdw")`; on Linux run `./trs80dw.py --port /dev/ttyUSB0 --baud 19200 --disk 6=<virtual disk>`. Then on the 4P `DIR :6`. **Pass: a directory listing appears; copying a small file to `:6` and back succeeds.** If the driver hangs (TRSDW has no timeouts), reboot and capture the server log.
- [ ] **Step 3: If TRSDW fails on the 4P,** record exactly how, and stop: the spec's fallback (a simpler serial file-transfer tool) becomes a separate small plan.
- [ ] **Step 4: Write `README.md`:** hardware (null modem), boot the monitor, write a disk, boot it, TRSDW, troubleshooting (right-shift timing, parity, B/C/D/E errors), and the safety rules. **Step 5: Commit** `docs: README and end-to-end procedure`.

---

## Self-review notes

- Spec coverage: gate/stage 1 → Tasks 2–4; probe before write → 7–8; writer + verification → 6–8; boot test → 10; TRSDW install → 11–12; host server → 13; end-to-end → 14; image fidelity and 79-track image → 5–6; licensing/untrusted downloads → Global Constraints, Task 12.
- Type consistency: `DmkImage`, `Track`, `Sector`, `Monitor`, `Fdc`, `DriveInfo`, `FdcError`, `WriteVerifyError` are defined once and reused unchanged.
- Known unknowns left to hardware/docs, each with a stop condition: UART status bits and FDC port map (Tasks 4, 7), real image track-0 density (Task 5), which image is bootable (Task 9), TRSDW link/license and DriveWire opcodes (Task 12).
