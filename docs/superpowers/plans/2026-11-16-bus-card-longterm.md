# Long-term: a bus card for fast storage, with a serial pig-tail for boot and modem use

> Status: idea / roadmap. Nothing here is designed or built. Written 2026-11-16 so the thought is not lost.
> Prerequisite: the RS-232-only path in `2026-11-16-fujinet-rs232-ls-dos.md` (especially its block-protocol layering).

## Idea

A card on the 4P's **I/O bus** (rear edge connector) with an ESP32 (and possibly an RP2350 as the bus interface,
as newer FujiNet designs do) provides disk storage at bus speed. A short **serial pig-tail** from the card to the 4P's
RS-232 port does two jobs:

1. **Boot:** the 4P ROM's serial loader pulls stage 1 from the card over the pig-tail. Stage 1 enables the bus
   and installs the card's driver. No diskette media needed.
2. **Modem:** after boot, the same port is a normal serial line, and the FujiNet acts as a network modem
   (Hayes-style AT commands to telnet/BBS) for terminal programs.

## Why a bus card at all

- RS-232 on the 4P tops out at **19200 baud (~1.9 KB/s, ~140 ms per 256-byte sector)**; a port-mapped card can move a
  sector in microseconds to a few milliseconds, so LS-DOS would feel like it has a hard disk.
- The ROM only offers a serial loader, and the bus cannot supply a boot ROM (below), so serial stays as the boot path.

## What the Model 4P bus offers (from `images/ref-m4tech/m4tech.txt`, section 3.1.14 "I/O Bus Port")

- Z80 **I/O-port** signals: A0-A7, data bus, IN/OUT, `IOBUSWAIT*`, `EXTIOSEL*`, an interrupt line.
- **No memory-space signals are documented**, so a card on the bus cannot act as a boot ROM or replace the ROM.
- The CPU must enable the bus by writing **bit 4 of port 0ECh**; the ROM does not do this at reset as far as we can tell, so stage 1 must.
- Wait states: hold `IOBUSWAIT*` no more than about 500 us at a 25% duty cycle (DRAM refresh is inhibited during waits).
- Z80 interrupt mode 1 is supported for bus interrupts (RAM jump vector).
- To confirm: connector type and pinout, signal levels, power available, mechanical fit.

## Existing work to study before designing anything

- **FreHD** (hard drive emulator for the Model III/4 bus) and **TRS-IO / TRS-IO++** (ESP32-based, Model I/III/4 family): check their licences, schematics, port maps, whether they support the 4P, and whether any of them boots a 4P without a floppy. (From memory only; none of this has been verified.)
- **fujinet-nio** and the newer FujiNet bus-interface architecture (RP2350 as bus front end): what is reusable.

## Design questions

1. **Cable direction/modes.** For boot the FujiNet is the host (DTE-like); for modem mode it is the modem (DCE). The pig-tail needs a software or jumper selectable crossover.
2. **Mode detection.** How does the device decide between "ROM loader handshake" and "terminal wants a modem"? Watching for the loader handshake at boot (0x55 bytes at 19200 8O1, then 0xFF) is the natural trigger; also an explicit AT command.
3. **Bus timing** on a 4 MHz Z80 with wait states: single-byte port reads/writes versus block moves (e.g., INIR/OTIR). Interrupt use for completion.
4. **Same software, different transport.** The 4P-side block protocol and LS-DOS driver from the RS-232 plan must work over both; only the transport layer changes.
5. **Floppy-less LS-DOS start-up** is the same open question as in the RS-232 plan; the card only makes loading the system files faster.
6. **Hardware effort:** PCB, 5 V/3.3 V buffering, power, enclosure; prototype first on an off-the-shelf microcontroller board with level shifters.
7. **Who is the audience?** Other 4P owners (small, many without diskettes) argue for a simple, buildable design and for upstreaming.

## Phases

- **B0 — research:** pin out the bus connector, read FreHD/TRS-IO sources and licences, check the 4P ROM for any HD-boot or bus probe behaviour (disassemble from the ROM dump if available), write findings here.
- **B1 — breadboard prototype:** a microcontroller dev board on the bus, answering one port with a loopback register. Prove the 0ECh enable, `EXTIOSEL*` and `IOBUSWAIT*` timing with logic-analyser captures.
- **B2 — sector device:** port-mapped block device (read/write sector) served from the RS-232 plan's PC-side test server; measure throughput versus the 19200 baud path.
- **B3 — boot integration:** stage 1 over the pig-tail installs the bus driver, then the same floppy-less boot as the RS-232 plan.
- **B4 — modem mode:** UART pass-through to network sockets with AT commands; mode switching and cable crossover.
- **B5 — board design:** schematic, PCB, firmware on ESP32/RP2350, documentation.

## Risks

- The 4P bus may lack signals or power a card needs; the ROM may not tolerate a bus device being present at reset.
- Real-time constraints (wait-state limit) may favour a small FPGA/CPLD or RP2350 PIO front end over pure ESP32 GPIO.
- Scope: hardware plus firmware plus a 4P driver; sensible only after the RS-232-only path works.
