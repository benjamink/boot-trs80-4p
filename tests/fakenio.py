"""A Python stand-in for fujinet-nio's DiskDevice, spoken over FujiBus/SLIP, for testing the Z80 client."""
from trs80 import fujibus as fb
from trs80 import niodisk as nd

OK, DEVICE_NOT_FOUND, INVALID_REQUEST, DEVICE_BUSY, NOT_READY, IO_ERROR, TIMEOUT, INTERNAL, UNSUPPORTED = range(9)
ERR_NOT_MOUNTED, ERR_OUT_OF_RANGE, ERR_READ_ONLY = 10, 12, 11


class FakeNio:
    def __init__(self):
        self.slots = {}                       # slot -> [bytearray image, readonly]
        self.requests = []                    # decoded request packets, in arrival order
        self.mangle = []                      # queue of callables(response_wire) -> wire (fault injection); None = pass

    def mount(self, slot, image, readonly=False):
        self.slots[slot] = [bytearray(image), readonly]

    def _disk(self, p):
        pl = p.payload
        slot = pl[1]
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

    def handle(self, raw):
        """One decoded request frame -> the wire bytes of the answer (possibly mangled/dropped)."""
        p = fb.parse_packet(raw)
        self.requests.append(p)
        status, payload = self._disk(p) if p.device == nd.DEVICE else (DEVICE_NOT_FOUND, b"")
        wire = fb.slip_encode(fb.build_response(p.device, p.command, status, payload))
        if self.mangle:
            f = self.mangle.pop(0)
            if f is not None:
                wire = f(wire)
        return wire
