"""A stand-in for the few LS-DOS 6 supervisor calls dosio.asm / serialcmd.asm use (RST 28h, SVC in A).
It follows the TRSDOS 6 Technical Reference: @INIT/@OPEN take HL = I/O buffer, DE = FCB with the
filespec ended by 0Dh; the buffer address lands in FCB+3/4 and @WRITE writes from there; @CLOSE
stores the EOF offset found in FCB+8.  Z set = success, else A = error number."""
Z = 0x40
SVC_DSPLY, SVC_EXIT, SVC_REMOV, SVC_INIT, SVC_OPEN, SVC_CLOSE, SVC_WRITE = 10, 22, 57, 58, 59, 60, 75


class DosExit(Exception):
    pass


class FakeDos:
    def __init__(self, cpu):
        self.cpu = cpu
        self.files = {}                 # "NAME/EXT" -> bytes (final, after close)
        self.pending = {}               # fcb address -> [name, bytearray]
        self.messages, self.calls, self.specs = [], [], []     # specs: raw filespecs given to @INIT/@OPEN
        self.fail = {}                  # svc number -> error number to return
        self.interrupts_on_at_svc = []
        orig = cpu.step

        def step():
            if cpu.pc == 0x28:
                self._svc()
            else:
                orig()
        cpu.step = step

    def _spec(self, addr):
        m, out = self.cpu.mem, bytearray()
        while m[addr] not in (0x0D, 0x03) and len(out) < 40:
            out.append(m[addr]); addr += 1
        raw = bytes(out).decode("latin-1")
        self.specs.append(raw)
        return raw.split(":")[0]

    def _ret(self, ok, err=0):
        cpu = self.cpu
        cpu.R[7] = 0 if ok else err
        cpu.F = (cpu.F | Z) if ok else (cpu.F & ~Z & 0xFF)
        cpu.pc = cpu.pop()

    def _svc(self):
        cpu, m = self.cpu, self.cpu.mem
        n, de, hl = cpu.R[7], cpu.rp(2, 3), cpu.hl()
        self.calls.append(n)
        self.interrupts_on_at_svc.append(getattr(cpu, "iff", None))
        if n in self.fail:
            return self._ret(False, self.fail[n])
        if n == SVC_DSPLY:
            s = bytearray()
            while m[hl] not in (0x0D, 0x03):
                s.append(m[hl]); hl += 1
            self.messages.append(bytes(s).decode("latin-1"))
            return self._ret(True)
        if n == SVC_EXIT:
            raise DosExit()
        if n in (SVC_INIT, SVC_OPEN):
            name = self._spec(de)
            if name not in self.files:
                if n == SVC_OPEN:
                    return self._ret(False, 24)
                self.files[name] = b""
                cpu.F |= 0x01                                   # CF = new file created
            m[de + 3], m[de + 4] = hl & 255, hl >> 8
            m[de] |= 0x80
            self.pending[de] = [name, bytearray(self.files[name]), 0]      # name, contents, next record number
            return self._ret(True)
        if de not in self.pending or not m[de] & 0x80:
            return self._ret(False, 38)                         # file not open
        rec = self.pending[de]
        name, data = rec[0], rec[1]
        if n == SVC_WRITE:
            buf = m[de + 3] | m[de + 4] << 8
            data[rec[2] * 256:(rec[2] + 1) * 256] = bytes(m[buf:buf + 256])     # overwrites from record 0
            rec[2] += 1
            return self._ret(True)
        if n == SVC_CLOSE:
            eof = m[de + 8]
            size = rec[2] * 256 if eof == 0 else (rec[2] - 1) * 256 + eof
            self.files[name] = bytes(data[:size])
            m[de] &= 0x7F
            del self.pending[de]
            return self._ret(True)
        if n == SVC_REMOV:
            del self.files[name]
            m[de] &= 0x7F
            del self.pending[de]
            return self._ret(True)
        raise NotImplementedError(f"SVC {n}")
