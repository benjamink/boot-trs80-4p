"""Host driver for z80/fdc.asm, run on the 4P through the resident monitor."""
import os
from dataclasses import dataclass

from trs80.lmf import parse_hex

PB = 0x9F00
ENTRY = dict(init=0x8000, restore=0x8003, seek=0x8006, read_addr=0x8009,
             read_sector=0x800C, arm_write=0x800F, write_track=0x8012,
             write_sector=0x8015, disarm=0x8018)
STREAM_BUF = 0xA000          # write-track stream (up to 6.4 KB)
SECTOR_BUF = 0xC000
ERR_NOT_ARMED, ERR_TIMEOUT = 1, 2
ST_NOT_READY, ST_RNF, ST_CRC, ST_LOST, ST_TR00 = 0x80, 0x10, 0x08, 0x04, 0x04
DEFAULT_HEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "fdc.hex")


class FdcError(Exception):
    pass


@dataclass
class DriveInfo:
    drive: int
    present: bool
    max_track: int
    sides: int
    status_text: str


def latch(drive, side=0, density="MFM"):
    if not 0 <= drive <= 3:
        raise ValueError("drive must be 0-3")
    return (1 << drive) | (0x10 if side else 0) | (0x80 if density == "MFM" else 0)


class Fdc:
    def __init__(self, mon, hex_path=DEFAULT_HEX):
        self.mon, self.hex_path = mon, hex_path
        self.last_status = 0
        self._homed = set()
        self.probed = set()          # drives whose probe found a ready, formatted disk

    def upload(self):
        segs, _ = parse_hex(self.hex_path)
        for addr, data in segs.items():
            self.mon.write_mem(addr, data)
        self.mon.write_mem(PB, bytes(16))
        self.mon.exec(ENTRY["init"])
        self._homed.clear()

    def _call(self, name, lat=0, track=0, sector=0, buf=SECTOR_BUF, spin=False):
        self.mon.write_mem(PB, bytes([lat, track, sector, buf & 255, buf >> 8]))
        self.mon.write_mem(PB + 8, bytes([1 if spin else 0]))
        self.mon.exec(ENTRY[name])
        status, err = self.mon.read_mem(PB + 5, 2)
        self.last_status = status
        return status, err

    def _home(self, drive, lat, spin=True):
        status, err = self._call("restore", lat, spin=spin)
        if err or status & ST_NOT_READY:
            raise FdcError(f"drive {drive}: restore failed (status {status:#04x}, err {err})")
        self._homed.add(drive)

    def probe(self, drive):
        """Read-only: restore, seek outward, read address marks. Never arms writes."""
        lat0 = latch(drive)
        status, err = self._call("restore", lat0, spin=True)
        if err == ERR_TIMEOUT:
            return DriveInfo(drive, False, -1, 0, "controller timeout (no drive?)")
        if status & ST_NOT_READY:
            return DriveInfo(drive, False, -1, 0, "not ready (no disk or drive absent)")
        if not status & ST_TR00:
            return DriveInfo(drive, False, -1, 0, f"restore did not reach track 0 (status {status:#04x})")
        self._homed.add(drive)
        self.probed.add(drive)
        text, density = "", None
        for d in ("MFM", "FM"):
            _, err = self._call("read_addr", latch(drive, 0, d), buf=SECTOR_BUF)
            if not err and not self.last_status & (ST_RNF | ST_CRC):
                density = d
                break
        if density is None:
            return DriveInfo(drive, True, -1, 0, "ready but no readable address mark (unformatted?)")
        max_track = -1
        for t in (79, 39):
            self._call("restore", latch(drive, 0, density))      # register and head must agree before a seek
            self._call("seek", latch(drive, 0, density), track=t)
            _, err = self._call("read_addr", latch(drive, 0, density))
            got = self.mon.read_mem(SECTOR_BUF, 1)[0]
            if not err and not self.last_status & (ST_RNF | ST_CRC) and got == t:
                max_track = t
                break
        self._call("restore", latch(drive, 0, density))
        _, err = self._call("read_addr", latch(drive, 1, density))
        sides = 2 if not err and not self.last_status & (ST_RNF | ST_CRC) else 1
        text = f"ready, {density}, {sides} side(s), highest readable track {max_track}"
        return DriveInfo(drive, True, max_track, sides, text)

    def arm_write(self):
        self.mon.exec(ENTRY["arm_write"])

    def disarm(self):
        self.mon.exec(ENTRY["disarm"])

    def write_sector(self, drive, cyl, side, sector, data, density="MFM"):
        """Needs arm_write first (stays armed until disarm). Returns 0 ok, 1 not armed, 2 timeout."""
        if self.mon.read_mem(PB + 9, 1)[0] != 0xA5:
            return ERR_NOT_ARMED
        lat = latch(drive, side, density)
        self.mon.write_mem(SECTOR_BUF, data)
        if drive not in self._homed:
            self._home(drive, lat)
        self._call("seek", lat, track=cyl)
        _, err = self._call("write_sector", lat, sector=sector, buf=SECTOR_BUF)
        return err

    def write_track(self, drive, cyl, side, stream, density="MFM"):
        """Returns the routine's error code (0 ok, 1 refused: not armed, 2 timeout). Arming is one-shot."""
        if self.mon.read_mem(PB + 7, 1)[0] != 0xA5:      # refuse before touching the drive (Z80 re-checks)
            return ERR_NOT_ARMED
        lat = latch(drive, side, density)
        self.mon.write_mem(STREAM_BUF, stream)
        if drive not in self._homed:
            self._home(drive, lat)
        self._call("seek", lat, track=cyl)
        _, err = self._call("write_track", lat, buf=STREAM_BUF)
        return err

    def read_sector(self, drive, cyl, side, sector, size, density):
        lat = latch(drive, side, density)
        if drive not in self._homed:
            self._home(drive, lat)
        status, err = self._call("seek", lat, track=cyl)
        if err or status & (ST_NOT_READY | ST_RNF):
            raise FdcError(f"seek to {cyl} failed (status {status:#04x}, err {err})")
        status, err = self._call("read_sector", lat, sector=sector)
        if err or status & (ST_NOT_READY | ST_RNF | ST_CRC | ST_LOST):
            raise FdcError(f"read C{cyl} H{side} S{sector} failed (status {status:#04x}, err {err})")
        return self.mon.read_mem(SECTOR_BUF, size)
