"""A crude WD1773 + drive-select latch model on ports F0-F4 for testing z80/fdc.asm.
DRQ is raised on every second status read so the routines' polling loops are exercised."""


class FakeWD1773:
    PORTS = (0xF0, 0xF1, 0xF2, 0xF3, 0xF4)

    def __init__(self):
        self.track = 0              # the controller's track REGISTER
        self.phys = 0               # where the head really is
        self.sector = 0
        self.data = 0
        self.latch = None
        self.log = []               # (kind, port, value)
        self.disk = {}              # (track, side, sector) -> bytes
        self.rdq = bytearray()
        self.wbuf = bytearray()
        self.write_limit = 6250
        self.stuck = False          # busy forever, never any DRQ (no disk / no index pulses)
        self.mode = None            # None | "typeI" | "read" | "write"
        self.final = 0
        self.reads = 0
        self.typeI_reads = 0
        self.commands = []
        self.max_cyl = 39           # head bumps the stop beyond this
        self.sides = 1
        self.ready = True

    @property
    def side(self):
        return 1 if (self.latch or 0) & 0x10 else 0

    def io_out(self, port, val):
        self.log.append(("out", port, val))
        if port == 0xF4:
            self.latch = val
        elif port == 0xF1:
            self.track = val
        elif port == 0xF2:
            self.sector = val
        elif port == 0xF3:
            if self.mode in ("write", "wsec"):
                self.wbuf.append(val)
            else:
                self.data = val
        elif port == 0xF0:
            self._command(val)

    def io_in(self, port):
        self.log.append(("in", port, None))
        if port == 0xF3:
            return self.rdq.pop(0) if self.rdq else 0
        if port == 0xF1:
            return self.track
        if port == 0xF0:
            return self._status()
        return 0xFF

    def _command(self, c):
        self.commands.append(c)
        self.reads = 0
        if c == 0xD0:                                   # force interrupt
            self.mode, self.stuck = None, False
            self.final = 0
        elif c & 0xF0 == 0x00:                          # restore
            self.track = self.phys = 0
            self.mode, self.typeI_reads, self.final = "typeI", 0, 0x04 | self._nr()
        elif c & 0xF0 == 0x10:                          # seek (data register = destination)
            self.phys = max(0, min(self.max_cyl, self.phys + self.data - self.track))
            self.track = self.data
            self.mode, self.typeI_reads, self.final = "typeI", 0, (0x04 if self.phys == 0 else 0) | self._nr()
        elif c == 0xC4:                                 # read address
            if not self.ready or self.side >= self.sides:
                self.rdq, self.mode, self.final = bytearray(), "read", 0x10 | self._nr()
            else:
                self.rdq = bytearray([self.phys, self.side, 1, 1, 0xAA, 0xBB])
                self.mode, self.final = "read", 0
        elif c == 0x84:                                 # read sector
            d = self.disk.get((self.track, self.side, self.sector))
            if d is None:
                self.rdq, self.mode, self.final = bytearray(), "read", 0x10      # RNF
            else:
                self.rdq, self.mode, self.final = bytearray(d), "read", 0
        elif c == 0xA4:                                 # write sector (normal data mark)
            self.wbuf = bytearray()
            self.mode, self.final, self.sec_target = "wsec", 0, (self.phys, self.side, self.sector)
        elif c == 0xF4:                                 # write track
            self.wbuf = bytearray()
            self.mode, self.final = "write", 0

    def _nr(self):
        return 0 if self.ready else 0x80

    def _status(self):
        self.reads += 1
        if self.stuck:
            return 0x01
        if self.mode == "typeI":
            self.typeI_reads += 1
            if self.typeI_reads <= 3:
                return 0x01
            self.mode = None
            return self.final
        if self.mode == "read":
            if not self.rdq:
                self.mode = None
                return self.final
            return 0x03 if self.reads % 2 == 0 else 0x01
        if self.mode == "wsec":
            if len(self.wbuf) >= 256:
                self.disk[self.sec_target] = bytes(self.wbuf)
                self.mode = None
                return self.final
            return 0x03 if self.reads % 2 == 0 else 0x01
        if self.mode == "write":
            if len(self.wbuf) >= self.write_limit:
                self.mode = None
                return self.final
            return 0x03 if self.reads % 2 == 0 else 0x01
        return self.final
