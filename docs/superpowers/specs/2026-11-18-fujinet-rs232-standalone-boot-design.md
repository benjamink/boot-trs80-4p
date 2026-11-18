# Standalone boot from the FujiNet RS-232 board (fujinet-nio firmware)

2026-11-18. Status: awaiting approval.

## Intent

Today the 4P boots floppy-less from a laptop: `boot-fuji.sh` sends `nioboot` through the 4P's ROM serial loader
(Right-Shift + Reset), then runs the POSIX fujinet-nio, which serves the boot disk and everything after it (FLS, FMOUNT,
CONFIG, clock). The owner wants the real FujiNet RS-232 board (ESP32-S3, plugged into this laptop on `/dev/ttyACM0`)
to do all of that on its own, so the laptop is no longer in the loop. The 4P should behave exactly as it does against
the laptop build.

## Goals

- Flash fujinet-nio onto the ESP32-S3 RS-232 board; the board answers FujiBus over its RS-232 port at 19200 8O1.
- The firmware itself sends the ROM-loader load module (`nioboot`) when the 4P is sitting at the loader.
- Reset the 4P (Right-Shift held) at any time, including mid-session, and it reloads with no laptop.
- Boot disk (`boot.xfd`, LS-DOS + FujiNet driver + CONFIG) is served from the board's flash filesystem.
- Everything the laptop session does works: `DIR :0`, `FLS`, `FUJIDRV`, `FMOUNT`, `FDRIVE`, `CONFIG`, correct time zone.

## Non-goals / anti-goals

- No TRS-80 support elsewhere in the firmware (JV3/DMK images, other loaders). Those stay in `TODO.md`.
- No change to behavior on any other platform or board: the sender is off unless configured.
- Not a success if the stray probe bytes can corrupt a running LS-DOS session; that must be tested, not assumed.
- No upstream PR in this round (work on a branch in the owner's fork, `benjamink/fujinet-nio`).

## Constraints

- The ROM loader needs 8 data bits, odd parity, 19200 baud; handshake is 0x55 repeated until the ROM answers
  "Found Baud Rate", then 0xFF, then "Loading ", then the load module. Byte pacing 2 ms (without it about a third of
  loads failed on the laptop). `UartChannel` already supports `parity: odd` and TX pacing.
- Board: `rs232-esp32-s3-wroom-1-n16r8`, build `fujibus-gpio-rs232-uart-log-s3-wroom-1-n16r8` (already set in
  `platformio.local.ini`), flashed over the USB-JTAG port (`/dev/ttyACM0`). The user is in the `uucp` group.
- Flash storage partition is about 4 MiB; a 180 KB boot disk plus the loader fit easily.
- `FujiBusTransport` owns reading the channel; the sender must share the line with it, not fight it.

## Approaches considered

1. **Boot window**: probe for ~60 s after power-up. Simple, never disturbs a running 4P, but needs the 4P reset inside
   the window or a board power-cycle.
2. **Probe while idle (chosen by the owner)**: probe whenever no valid FujiBus frame has been seen for ~10 s; stop at
   the first valid frame. Reset any time and it reloads, like `boot-fuji.sh`. Risk: stray 0x55 bytes reaching a
   running LS-DOS; to be tested on the real 4P. Fallback if it misbehaves: option 1.
3. **Button trigger**: cleanest on the wire, but adds a manual step and the board's buttons are unconfirmed.

## Design (the owner's decisions, then my calls)

Owner's decisions: the firmware sends the loader (not the laptop), and the trigger is "probe while idle".

My calls (correctable):

- **Loader format in flash:** ship `nioboot` as a ready-made load module (`nioboot.cmd`, what `trs80boot.py` sends
  as-is), so the firmware only streams bytes and needs no Intel HEX parser. This repo's `Makefile` produces it from
  `build/nioboot.hex` (or `nioboot-config.hex` for the CONFIG autostart variant, matching `boot-fuji.sh`).
- **Where the files go:** `distfiles/esp32-data/boot/trs80/` (`nioboot.cmd`, `boot.xfd`), packed with
  `boot_images = trs80` like the Amiga image. Generated files are not committed (the directory README says so).
- **Config:** new yaml block, default off, e.g. `trs80_loader: {enabled, path, idle_seconds}` with the board's
  default profile enabling it. `boot.config_uri` points at `flash:/boot/trs80/boot.xfd`.
- **Code:** a small state machine ticked from `FujinetCore::tick()` (non-blocking; the 2 ms byte pacing is done with
  timestamps, not sleeps): Idle -> Probing (0x55 about every 100 ms) -> Syncing (0xFF) -> Sending -> back to Idle.
  "Valid frame seen" comes from `FujiBusTransport` via the existing `IBusLineCoordinator` hook if it fits; otherwise
  a counter on the transport. While probing/sending it reads ROM replies from the channel itself; otherwise it leaves
  the channel alone. A failed or "Error" reply means go back to probing.
- **Testing without the 4P first:** unit/POSIX test of the state machine against a fake ROM; then optionally MAME
  (`trs80m4p`, used earlier in this repo) over the POSIX build; then the real 4P.
- **Doc/tooling in this repo:** a Make target or script that builds the flash assets, and an update to
  `docs/fujinet-nio-testing.md` or a new short doc for the flashing procedure.

## Left to the builder

- Exact hook for "valid frame seen" and for sharing the channel; exact class/file layout in fujinet-nio.
- Probe interval and idle timeout tuning (starting at 100 ms / 10 s), and how long to wait for the ROM's answer.
- Whether the sender should also run on the POSIX build (useful for testing; harmless if off by default).

## Success check (real 4P)

1. Flash the board, connect it to the 4P, power both. Right-Shift + Reset: loader is sent by the board, LS-DOS boots to
   `LS-DOS Ready` (or CONFIG), with the laptop not involved (the serial port from the laptop is not open).
2. `DIR :0`, `FLS host:/` (or the flash equivalent), `FUJIDRV :1`, `FMOUNT`, time zone correct.
3. Leave LS-DOS idle at the prompt for over a minute (probes active), then `DIR :0` and `FMOUNT`: no errors.
4. Reset the 4P again with Right-Shift: it reloads and boots again by itself.
