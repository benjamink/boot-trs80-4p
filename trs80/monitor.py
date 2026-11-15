"""Host-side client for the resident Z80 monitor (see trs80.frames for the wire format).

Transport interface: write(data: bytes) -> None; read(timeout: float) -> bytes
(returns whatever is available, b"" when the timeout expires with nothing).
"""
from trs80 import frames as F

REG_ORDER = "AFBCDEHL"
WRITE_CHUNK = F.MAX_PAYLOAD - 2   # 2 bytes of address
READ_CHUNK = F.MAX_PAYLOAD


class MonitorError(Exception):
    pass


class Monitor:
    def __init__(self, transport, timeout=0.5, retries=5):
        self.t = transport
        self.timeout = timeout
        self.retries = retries
        self.seq = 0

    def _request(self, cmd, payload=b""):
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFF
        frame = F.encode_request(cmd, seq, payload)
        for _ in range(self.retries):
            self.t.write(frame)             # a retry resends the same seq
            buf = b""
            while True:
                p = F.parse_frame(buf, F.SYNC_RSP)
                if p:
                    buf = buf[p.consumed:]
                    if not p.ok or p.code == F.ST_BAD_CHECKSUM:
                        break               # damaged either way: resend
                    if p.seq != seq:
                        continue            # late answer to an earlier request
                    if p.code == F.ST_BAD_COMMAND:
                        raise MonitorError(f"4P rejected command {cmd}")
                    return p.payload
                chunk = self.t.read(self.timeout)
                if not chunk:
                    break                   # timed out: resend
                buf += chunk
        raise MonitorError(f"no valid answer to command {cmd} after {self.retries} tries")

    def ping(self, payload=b""):
        return self._request(F.CMD_PING, payload)

    def write_mem(self, addr, data):
        for i in range(0, len(data), WRITE_CHUNK):
            a = addr + i
            self._request(F.CMD_WRITE_MEM, bytes([a & 0xFF, a >> 8]) + data[i:i + WRITE_CHUNK])

    def read_mem(self, addr, n):
        out = b""
        while len(out) < n:
            a, k = addr + len(out), min(READ_CHUNK, n - len(out))
            got = self._request(F.CMD_READ_MEM, bytes([a & 0xFF, a >> 8, k]))
            if len(got) != k:
                raise MonitorError(f"short read at {a:#06x}: wanted {k}, got {len(got)}")
            out += got
        return out

    def exec(self, addr):
        got = self._request(F.CMD_EXEC, bytes([addr & 0xFF, addr >> 8]))
        return dict(zip(REG_ORDER, got))

    def port_in(self, port):
        return self._request(F.CMD_IN, bytes([port]))[0]

    def port_out(self, port, value):
        self._request(F.CMD_OUT, bytes([port, value]))
