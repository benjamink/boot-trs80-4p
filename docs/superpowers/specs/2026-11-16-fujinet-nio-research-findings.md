# fujinet-nio research findings (first pass, 2026-11-16)

Purpose: answer the open questions in `docs/superpowers/plans/2026-11-16-fujinet-rs232-ls-dos.md`.
Method: read the public repos (shallow clones, read-only, nothing built or run). Clones were in the session scratchpad,
not in this repo. Revisions: all `main` as of 2026-11-16; re-check before relying on any detail.
Everything below is from the repos' own docs and code comments unless marked **(unverified)**.

## The ecosystem (GitHub org `fujinet-nio`)

| Repo | What it is |
|---|---|
| `fujinet-nio` | The firmware/device side: modern C++ re-implementation of FujiNet I/O services. ESP32 builds *and* a POSIX build. |
| `fujinet-nio-lib` | Client C library (cc65, Open Watcom, gcc, amiga-gcc, ...). **No Z80/TRS-80 target.** |
| `fujinet-nio-driver` | OS disk drivers: MS-DOS `FUJINET.SYS`, Amiga `fujinet-disk.device`. The closest precedent for an LS-DOS driver. |
| `nio-config` | The CONFIG application (targets: msdos, bbc, linux, atari, c64, amiga). |
| `nio-core-apps` | `F*` command-line utilities (fmount, fls, fdrive ...) and **boot disks**. |
| `fujinet-nio-workspace` | Build orchestration across the repos. |
| `fujinet-nio-hardware` | Hardware projects (not yet read). |

**Licence: all of these are GPL-3.0.** Anything we copy or derive from becomes GPL. Writing our own Z80 client from the
protocol documents is cleaner; decide before copying code. (This repo has no licence file yet.)

## Wire protocol

- Stack: `SLIP frame (C0 ... C0)` -> `FujiBus packet` -> device command. SLIP escapes: C0 = DB DC, DB = DB DD.
- FujiBus header, 6 bytes: device, command, length (u16 LE, includes header), checksum, first descriptor byte. Then
  descriptor bytes, parameters (little-endian, widths from the descriptor), payload. Authoritative doc: `docs/protocol_reference.md`.
- Checksum: fold-carry sum over the whole packet with the checksum byte zeroed (`sum += b; sum = (sum>>8) + (sum&0xFF)`).
- `docs/driver_architecture.md` states the intended client layering, which is *exactly* the layering in our plan:
  `OS disk driver -> DiskDevice client codec -> FujiBus packets -> channel framing (SLIP for RS-232) -> physical channel`.
  New fast channels are meant to be packet-native instead of SLIP.

## Disk service (what CONFIG and the LS-DOS driver would use)

`docs/disk_device_protocol.md`. Wire device id `0xFC`. Commands: Mount 01, Unmount 02, **ReadSector 03, WriteSector 04**,
Info 05, ClearChanged 06, Create 07, RestoreBoot 0A, BeginHostSession 0B, Reinitialize 0C, ListMounts 0D, Flush 0E; also
`ReadSectors`/`WriteSectors` (multi-sector, in `src/lib/disk_device.cpp`; documentation is thin).
- Slots are 1-based. Images are addressed by URI: `sd0:/disks/x.img`, `tnfs://host:port/...`, `host:/...`; URI parsing is done in NIO, not on the 8-bit host.
- Sector addressing is by **LBA**; Info returns sector size and count. 256-byte sectors are fine.
- `boot.mode = config` makes NIO pre-mount `boot.config_uri` on slot D1; `RestoreBoot` and `BeginHostSession` (call at driver init)
  reset the mount state to a fresh boot. This is the mechanism for "CONFIG, then boot the chosen image".
- Config catalog and runtime mounts are separate (`docs/slot_state.md`); `ListMounts` gives the runtime view. File/host browsing is the
  FileDevice (`0xFE`, `docs/file_device_protocol.md`) and a slot-catalogue service (`docs/slot_catalog_service_protocol.md`) **(not yet read)**.

### Gap: no TRS-80 image formats
Supported image types are raw, SSD, DSD, D64, ADFS, DiskCopy 4.2, Atari ATR/XEX, etc. `.dsk` is deliberately **not** recognised by
extension, and the source comment names TRS-80 as one of the ambiguous `.dsk` users. DMK, JV1 and JV3 (the TRS-80 formats) are not
supported. Workable now: serve LS-DOS images as **raw flat 256-byte-sector files** (`LBA = cylinder*18 + sector` for our single-sided
40x18 images) mounted with a `sector_size_hint` of 256. Our images are DMK; a DMK->raw converter is trivial (`trs80/dmk.py` already
parses them). Adding native DMK support would be a firmware contribution.

## RS-232 channel (answers "can we develop without FujiNet hardware?")

- NIO has an RS-232 channel profile: ESP32 boards `rs232-esp32-*` (`boards/*.json`), and a **POSIX build `fujibus-rs232`**
  (CMake preset `fujibus-rs232-debug`) that opens a serial port such as `/dev/ttyUSB0` and speaks FujiBus over SLIP.
  Per the docs this runs fujinet-nio on a Linux PC with a USB serial adapter, i.e. **on this machine with the Keyspan adapter and
  the 4P** **(unverified: not built here)**.
- UART settings come from `fujinet.yaml` (`baud_rate`, `data_bits`, `parity`, `stop_bits`, `flow_control`, TX pacing). Odd parity and 19200 are
  expressible; the ESP32 default RS232 pacing is 16-byte chunks with 2 ms gaps **(check that this does not hurt at 19200)**. `UartChannel::set_baud_rate` exists.
- Packet-link variant (`docs/packet_link.md`): a different framing (sync `F5 4E`, CRC-32, generations) for a microcontroller bridging a host
  bus to NIO. Relevant to the *bus-card* idea (the RP2350-style bridges in `bridges/`), not to the RS-232-only path.

## Existing precedents we can learn from

- **MS-DOS `FUJINET.SYS`** (in `fujinet-nio-driver/msdos`): a real OS block-device driver speaking DiskDevice over RS-232 (115200 baud there). The best
  model for the LS-DOS driver's structure: request queueing, media change, geometry, error mapping.
- **Amiga `fujinet-disk.device`**: second implementation of the same layering.
- **Atari/C64 boot disks** (`nio-core-apps/boot-disk`, `nio-config`): CONFIG is *the first thing the machine loads*; on the Atari it is
  the default boot disk. Our 4P equivalent is the CONFIG program sent through the ROM loader.
- **ModemDevice** (`docs/modem_device_protocol.md`): Hayes-style AT emulation (`ATB19200`, `AT+BAUDLOCK`) exists in NIO; relevant to the "serial as modem" idea.

## Answers to the plan's open questions

1. **fujinet-nio protocol over RS-232:** FujiBus-over-SLIP, DiskDevice for sectors. Not DriveWire. (DriveWire is mentioned only in the client lib's platform
   notes; I found no DriveWire implementation in the firmware.) We would write the 4P-side client.
2. **Can NIO act as the ROM loader's host?** **No existing support.** Nothing in NIO knows the 4P handshake (host sends 0x55 until the ROM
   answers "Found Baud Rate", then 0xFF, then the load module at 19200 8O1; see `trs80boot.py`). It would need a new boot-service/transport mode in NIO (a contribution), or a
   small PC/bridge to do the first stage. This is now the main gap on the firmware side.
3. **Floppy-less LS-DOS start-up:** unchanged; nothing in these repos helps. It is our own problem (see the plan's A/B/C options).
4. **Licensing:** GPL-3.0 across the NIO repos (see above).
5. **What the firmware must provide:** mount/read/write by LBA already exists. Missing: a way to deliver the 4P loader stage and (optionally) DMK images.

## Speed estimate for the RS-232-only path

19200 baud with 8O1 is 11 bits per byte, about 1750 bytes/s. A 256-byte ReadSector exchange is about 20 request bytes plus about 280 response
bytes (SLIP/FujiBus/DiskDevice overhead included), about 0.17-0.2 s per sector. Booting LS-DOS (~100-150 KB of system files, roughly 400-600 sectors) is about
1.5-2.5 minutes before any caching; `ReadSectors` batching reduces round trips but not bytes. The MS-DOS driver's 115200 is six times faster; the 4P UART cannot go
beyond 19200. This supports the bus-card roadmap for speed.

## Proposed next steps

1. Decide GPL stance for the 4P-side client (own implementation from the spec vs. derived code).
2. Read `file_device_protocol.md`, `slot_catalog_service_protocol.md`, `fuji_device_protocol.md`, `nio-config` source: what CONFIG on a 4P needs to list hosts/images and mount.
3. With consent, build `fujibus-rs232-debug` in a scratch directory and run it against `/dev/ttyUSB0`, with a Python test client from this repo speaking FujiBus. That proves the PC-as-FujiNet development loop.
4. Write the Z80 client (SLIP + FujiBus + DiskDevice Info/ReadSector) and test it in the emulator against NIO's `disk_device_test_vectors.md` vectors.
5. Raise with the fujinet-nio maintainers (issue/discussion): "boot-over-serial host service for TRS-80 ROM loader" and DMK/JV3 image types, before writing firmware changes.
