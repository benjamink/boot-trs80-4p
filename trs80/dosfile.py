"""Write files onto the LS-DOS floppy in the 4P while SERIAL/CMD (the resident monitor) is running.

The helpers in z80/dosio.asm call LS-DOS itself (@INIT, @WRITE, @CLOSE ...), so the file ends up
in the directory exactly as if a DOS program had written it.  Each call returns A,F as the
LS-DOS call left them: Z set = success, otherwise A is the LS-DOS error number.
"""
import os

from trs80 import lsdosfs
from trs80.lmf import parse_hex

DEFAULT_HEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "dosio.hex")
ENTRY = dict(open=0x8000, kill=0x8003, write=0x8006, close=0x8009, exit=0x800C)
FCB, IOBUF, PB_EOF = 0xA000, 0xA100, 0x9F02
Z_FLAG = 0x40
ERR_FILE_NOT_FOUND = 24


class DosError(Exception):
    def __init__(self, what, code):
        super().__init__(f"{what} failed: LS-DOS error {code} ({code:#04x})")
        self.what, self.code = what, code


class DosLink:
    def __init__(self, mon, hex_path=DEFAULT_HEX):
        self.mon, self.hex_path = mon, hex_path

    def upload(self):
        segs, _ = parse_hex(self.hex_path)
        for addr, data in segs.items():
            self.mon.write_mem(addr, data)

    def _call(self, name):
        r = self.mon.exec(ENTRY[name])
        return bool(r["F"] & Z_FLAG), r["A"]

    def _spec(self, name, drive):
        base, ext = lsdosfs.split_name(name)
        spec = base.decode().rstrip() + ("/" + ext.decode().rstrip() if ext.strip() else "") + f":{drive}"
        self.mon.write_mem(FCB, spec.encode() + b"\r" + bytes(47 - len(spec)))

    def put(self, name, data, drive=0, progress=None):
        """Create (replacing any old copy) NAME/EXT on the drive with exactly these bytes.
        Returns True if an existing file was replaced."""
        lsdosfs.split_name(name)                       # validate before touching anything
        self._spec(name, drive)
        ok, a = self._call("kill")
        replaced = ok
        if not ok and a != ERR_FILE_NOT_FOUND:
            raise DosError(f"removing the old {name}", a)
        self._spec(name, drive)
        ok, a = self._call("open")
        if not ok:
            raise DosError(f"creating {name}", a)
        try:
            for off in range(0, len(data), 256):
                self.mon.write_mem(IOBUF, data[off:off + 256].ljust(256, b"\0"))
                ok, a = self._call("write")
                if not ok:
                    raise DosError(f"writing {name} at byte {off}", a)
                if progress:
                    progress(min(off + 256, len(data)), len(data))
            self.mon.write_mem(PB_EOF, bytes([len(data) % 256]))
        finally:
            ok, a = self._call("close")
        if not ok:
            raise DosError(f"closing {name}", a)
        return replaced

    def exit(self):
        """Return to the LS-DOS prompt. The monitor never answers, so a missing reply is expected."""
        from trs80.monitor import MonitorError
        try:
            self.mon.exec(ENTRY["exit"])
        except MonitorError:
            pass
