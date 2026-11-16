"""A Python stand-in for fujinet-nio's DiskDevice, spoken over FujiBus/SLIP, for testing the Z80 client."""
from fujinet import fujibus as fb
from fujinet import niodisk as nd

OK, DEVICE_NOT_FOUND, INVALID_REQUEST, DEVICE_BUSY, NOT_READY, IO_ERROR, TIMEOUT, INTERNAL, UNSUPPORTED = range(9)
CLOCK_DEVICE, CLOCK_GET_FORMAT = 0x45, 0x03
ERR_NOT_MOUNTED, ERR_OUT_OF_RANGE, ERR_READ_ONLY, ERR_FILE_NOT_FOUND = 10, 12, 11, 4


class FakeNio:
    def __init__(self):
        self.dirs = {}                        # uri -> text lines of a directory listing
        self.library = {}                     # uri -> image bytes that Mount can open
        self.uris = {}                        # slot -> (uri, readonly)
        self.slots = {}                       # slot -> [bytearray image, readonly]
        self.requests = []                    # decoded request packets, in arrival order
        self.clock = None                     # (year, month, day, hour, minute, second) the Clock device reports; None = no clock device
        self.mangle = []                      # queue of callables(response_wire) -> wire (fault injection); None = pass

    def mount(self, slot, image, readonly=False):
        self.slots[slot] = [bytearray(image), readonly]

    def _disk(self, p):
        pl = p.payload
        if p.command == nd.LIST_MOUNTS:
            return self._list(pl)
        slot = pl[1]
        if p.command == nd.MOUNT:
            uri = bytes(pl[8:8 + (pl[6] | pl[7] << 8)]).decode()
            if uri not in self.library:
                return INVALID_REQUEST, bytes([1, ERR_FILE_NOT_FOUND])
            self.mount(slot, self.library[uri], readonly=bool(pl[2] & 1))
            self.uris[slot] = (uri, bool(pl[2] & 1))
            return OK, nd.info_response(slot, 256, len(self.library[uri]) // 256, readonly=bool(pl[2] & 1))[:12]
        if p.command == nd.UNMOUNT:
            if slot not in self.slots:
                return NOT_READY, bytes([1, ERR_NOT_MOUNTED])
            del self.slots[slot]; self.uris.pop(slot, None)
            return OK, bytes([1, 0, 0, 0, slot])
        if slot not in self.slots:
            return NOT_READY, bytes([1, ERR_NOT_MOUNTED])
        img, ro = self.slots[slot]
        if p.command == nd.INFO:
            return OK, nd.info_response(slot, 256, len(img) // 256, readonly=ro)
        lba = int.from_bytes(pl[2:6], "little")
        if (lba + 1) * 256 > len(img):
            return INVALID_REQUEST, bytes([1, ERR_OUT_OF_RANGE])
        if p.command == nd.READ_SECTOR:
            return OK, nd.read_response(slot, lba, img[lba * 256:(lba + 1) * 256])
        if p.command == nd.WRITE_SECTOR:
            if ro:
                return INVALID_REQUEST, bytes([1, ERR_READ_ONLY])
            n = pl[6] | pl[7] << 8
            img[lba * 256:(lba + 1) * 256] = pl[8:8 + n]
            return OK, bytes([1, 0, 0, 0, slot]) + pl[2:6] + (256).to_bytes(2, "little")
        return UNSUPPORTED, b""

    def _files(self, pl):
        n = pl[1] | pl[2] << 8
        uri = bytes(pl[3:3 + n]).decode()
        start, room = pl[3 + n] | pl[4 + n] << 8, pl[5 + n] | pl[6 + n] << 8
        if uri not in self.dirs:
            return IO_ERROR, b""
        lines = [ln.encode() + b"\n" for ln in self.dirs[uri]][start:]
        out, k = b"", 0
        for ln in lines:
            if len(out) + len(ln) > room:
                break
            out += ln; k += 1
        return OK, bytes([1, 4 | (k < len(lines))]) + (0).to_bytes(2, "little") + start.to_bytes(2, "little") \
            + k.to_bytes(2, "little") + len(out).to_bytes(2, "little") + out

    def _list(self, pl):
        start, room = pl[6] | pl[7] << 8, pl[8] | pl[9] << 8
        lines = [("%d: %s %s\n" % (slot - 1, "RO" if ro else "AUTO", uri)).encode()
                 for slot, (uri, ro) in sorted(self.uris.items())][start:]
        out, n = b"", 0
        for ln in lines:
            if len(out) + len(ln) > room:
                break
            out += ln; n += 1
        more = n < len(lines)
        return OK, bytes([1, 2 | more]) + (0).to_bytes(2, "little") + start.to_bytes(2, "little") \
            + n.to_bytes(2, "little") + len(out).to_bytes(2, "little") + out

    def handle(self, raw):
        """One decoded request frame -> the wire bytes of the answer (possibly mangled/dropped)."""
        p = fb.parse_packet(raw)
        self.requests.append(p)
        if p.device == nd.DEVICE:
            status, payload = self._disk(p)
        elif p.device == CLOCK_DEVICE and p.command == CLOCK_GET_FORMAT and self.clock:
            y, mo, d, h, mi, sec = self.clock
            status, payload = OK, bytes([1, p.payload[1], y // 100, y % 100, mo, d, h, mi, sec])      # simple format: century first
        elif p.device == nd.FILE_DEVICE and p.command == nd.FILE_LIST_DIRECTORY:
            status, payload = self._files(p.payload)
        else:
            status, payload = DEVICE_NOT_FOUND, b""
        wire = fb.slip_encode(fb.build_response(p.device, p.command, status, payload))
        if self.mangle:
            f = self.mangle.pop(0)
            if f is not None:
                wire = f(wire)
        return wire
