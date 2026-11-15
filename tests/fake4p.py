"""A simulated 4P monitor, speaking the frame protocol, for host-side tests.

It is the *transport* as the host sees it: host write() feeds the fake, host read()
returns whatever the fake has queued (b"" means "nothing arrived", i.e. a timeout).
"""
from trs80 import frames as F

REG_ORDER = "AFBCDEHL"


class FakeFourP:
    def __init__(self):
        self.mem = bytearray(65536)
        self.ports = {}
        self.exec_handlers = {}    # addr -> callable(fake) -> dict of registers
        self.exec_count = {}       # addr -> times executed
        self.requests = 0          # frames executed (not counting duplicates)
        self.mute = False          # never answer
        self._rx = b""
        self._tx = b""
        self._last_seq = None
        self._last_resp = b""
        self._drop = 0
        self._corrupt = 0
        self._garbage = b""

    # fault hooks
    def drop_next_response(self):
        self._drop += 1

    def corrupt_next_response(self):
        self._corrupt += 1

    def inject_garbage(self, data):
        self._garbage += data

    # transport interface (host side)
    def write(self, data):
        self._rx += data
        while True:
            p = F.parse_frame(self._rx, F.SYNC_REQ)
            if p is None:
                break
            self._rx = self._rx[p.consumed:]
            self._handle(p)

    def read(self, timeout):
        out, self._tx = self._tx, b""
        return out

    # 4P side
    def _handle(self, p):
        if not p.ok:
            self._queue(F.encode_response(F.ST_BAD_CHECKSUM, p.seq))
            return
        if p.seq == self._last_seq:
            self._queue(self._last_resp)       # duplicate: resend, do not re-execute
            return
        status, payload = self._execute(p.code, p.payload)
        resp = F.encode_response(status, p.seq, payload)
        self._last_seq, self._last_resp = p.seq, resp
        self._queue(resp)

    def _execute(self, cmd, pl):
        self.requests += 1
        if cmd == F.CMD_PING:
            return F.ST_OK, pl
        if cmd == F.CMD_WRITE_MEM:
            addr = pl[0] | pl[1] << 8
            self.mem[addr:addr + len(pl) - 2] = pl[2:]
            return F.ST_OK, b""
        if cmd == F.CMD_READ_MEM:
            addr, n = pl[0] | pl[1] << 8, pl[2]
            return F.ST_OK, bytes(self.mem[addr:addr + n])
        if cmd == F.CMD_EXEC:
            addr = pl[0] | pl[1] << 8
            self.exec_count[addr] = self.exec_count.get(addr, 0) + 1
            regs = self.exec_handlers.get(addr, lambda f: {})(self)
            return F.ST_OK, bytes(regs.get(r, 0) for r in REG_ORDER)
        if cmd == F.CMD_IN:
            return F.ST_OK, bytes([self.ports.get(pl[0], 0xFF)])
        if cmd == F.CMD_OUT:
            self.ports[pl[0]] = pl[1]
            return F.ST_OK, b""
        return F.ST_BAD_COMMAND, b""

    def _queue(self, resp):
        if self.mute:
            return
        if self._drop:
            self._drop -= 1
            return
        if self._corrupt:
            self._corrupt -= 1
            resp = resp[:-1] + bytes([resp[-1] ^ 0xFF])
        self._tx += self._garbage + resp
        self._garbage = b""
