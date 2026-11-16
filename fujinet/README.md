# fujinet/ — FujiNet (fujinet-nio) support for the TRS-80 Model 4P

Kept apart from the 4P bring-up tooling in the parent repo because this is the part meant to be contributed to the
fujinet-nio projects (GPL-3.0, like them).

- `fujibus.py`, `niodisk.py` — reference codec for FujiBus/SLIP and the DiskDevice/FileDevice payloads. The Z80 code is
  tested against it. It overlaps NIO's own `py/fujinet_tools/`; merge there when upstreaming.
- `z80/nioclib.asm` — the client library (SLIP + FujiBus over the 4P's UART; disk read/write/info/mount/unmount/list,
  directory listing). `z80/nioclient.asm` is its entry table at 8000h.
- `z80/fcli.asm` + `fmount.asm`, `fumount.asm`, `fdrive.asm`, `fls.asm` — the LS-DOS commands (see the top-level README).
- `cli_live.py`, `nio_live_check.py` — run the Z80 code in the interpreter against a real fujinet-nio over a pty/port.

Tests are still in `../tests/` (`test_nioclient_emulated.py`, `test_cli_emulated.py`, `test_fujibus.py`, `fakenio.py`)
because they share the Z80 interpreter and the fake LS-DOS with the bring-up tests. `make` builds everything.
