# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Python-level stand-in for trs80.fdc.Fdc with a simulated disk, for testing writedisk."""
from trs80.fdc import DriveInfo, FdcError


class FakeFdc:
    def __init__(self, present=True, max_track=39, sides=1):
        self.info = DriveInfo(0, present, max_track if present else -1, sides if present else 0, "fake")
        self.probed = set()
        self.armed = False
        self.disk = {}                # (cyl, side, sector) -> bytes
        self.tracks_written = []      # (cyl, side)
        self.events = []
        self.corrupt = {}             # (cyl, side, sector) -> remaining bad reads
        self.interrupt_on_track = None
        self.write_errors = 0
        self.dams = {}

    def probe(self, drive):
        self.events.append("probe")
        if self.info.present:
            self.probed.add(drive)
        return self.info

    def arm_write(self):
        self.events.append("arm")
        self.armed = True

    def disarm(self):
        self.events.append("disarm")
        self.armed = False

    def write_track(self, drive, cyl, side, stream, density="MFM"):
        if not self.armed:
            return 1
        self.events.append(("track", cyl, side))
        if self.interrupt_on_track == (cyl, side):
            raise KeyboardInterrupt
        self.tracks_written.append((cyl, side))
        self.last_stream = stream
        return 0

    def write_sector(self, drive, cyl, side, sector, data, density="MFM", dam=0xFB):
        if not self.armed:
            return 1
        self.dams[(cyl, side, sector)] = dam
        self.disk[(cyl, side, sector)] = bytes(data)
        return self.write_errors and 2 or 0

    def read_sector(self, drive, cyl, side, sector, size, density):
        key = (cyl, side, sector)
        if key not in self.disk:
            raise FdcError("RNF")
        data = self.disk[key]
        if self.corrupt.get(key, 0) > 0:
            self.corrupt[key] -= 1
            return bytes([data[0] ^ 1]) + data[1:]
        return data
