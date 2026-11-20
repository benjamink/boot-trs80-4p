# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Host transport backed by the monitor running in the Z80 interpreter ("time" = instructions).
After each host write the CPU runs until it is idle in rx_wait with nothing left to read.
Extra devices (e.g. a fake FDC) attach with attach(ports, io_in, io_out)."""
import re

from tests.z80emu import Z80, load_hex


def _read(path):
    with open(path) as f:
        return f.read()


class EmuTransport:
    """Host-side transport backed by the emulated 4P. 'Time' is instruction count:
    after each host write the CPU runs until it is idle in rx_wait with nothing to read."""
    def __init__(self, hexpath, sympath):
        self.cpu = Z80()
        load_hex(self.cpu, hexpath)
        self.cpu.pc = 0x6000
        syms = dict(re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", open(sympath).read() if False else _read(sympath), re.M))
        self.idle_pc = int(syms["rx_wait"], 16)
        self.rx, self.tx = [], bytearray()
        self.devices = []
        self.cpu.io_in = self._in
        self.cpu.io_out = self._out
        self.ports = {0x77: 0x5A}
        self.port_writes = []
        self.drop_next_response = False
        self.truncate_next_write = None
        self.corrupt_next_write = False

    def attach(self, ports, io_in, io_out):
        self.devices.append((set(ports), io_in, io_out))

    def _in(self, port):
        for ports, i, _ in self.devices:
            if port in ports:
                return i(port)
        if port == 0xEA:
            return 0x80 if self.rx else 0x00
        if port == 0xEB:
            return self.rx.pop(0)
        return self.ports.get(port, 0xFF)

    def _out(self, port, val):
        for ports, _, o in self.devices:
            if port in ports:
                o(port, val)
                return
        if port == 0xEB:
            self.tx.append(val)
        else:
            self.port_writes.append((port, val))

    def write(self, data):
        data = bytes(data)
        if self.truncate_next_write is not None:
            data, self.truncate_next_write = data[:self.truncate_next_write], None
        if self.corrupt_next_write:
            data, self.corrupt_next_write = data[:4] + bytes([data[4] ^ 0xFF]) + data[5:], False   # first payload byte
        self.rx.extend(data)
        self.cpu.run_until_idle(self.idle_pc, lambda: not self.rx)

    def read(self, timeout):
        out, self.tx = bytes(self.tx), bytearray()
        if self.drop_next_response and out:
            self.drop_next_response = False
            return b""
        return out
