# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Monitor protocol framing (pure functions; no I/O).

Request:  A5 cmd seq len payload[len] ck_lo ck_hi
Response: 5A status seq len payload[len] ck_lo ck_hi
ck = (sum of bytes from cmd/status through the payload) mod 65536.
"""
from dataclasses import dataclass

SYNC_REQ = 0xA5
SYNC_RSP = 0x5A

CMD_PING = 1       # payload echoed back
CMD_WRITE_MEM = 2  # addr_lo, addr_hi, data...
CMD_READ_MEM = 3   # addr_lo, addr_hi, n
CMD_EXEC = 4       # addr_lo, addr_hi; response payload = A,F,B,C,D,E,H,L after the routine returns
CMD_IN = 5         # port -> value
CMD_OUT = 6        # port, value

ST_OK = 0
ST_BAD_CHECKSUM = 1
ST_BAD_COMMAND = 2

MAX_PAYLOAD = 250


@dataclass
class Parsed:
    code: int      # cmd (request) or status (response)
    seq: int
    payload: bytes
    consumed: int  # bytes to drop from the buffer, including any leading garbage
    ok: bool       # checksum good


def checksum(data):
    return sum(data) & 0xFFFF


def _encode(sync, code, seq, payload):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} > {MAX_PAYLOAD}")
    body = bytes([code, seq & 0xFF, len(payload)]) + bytes(payload)
    ck = checksum(body)
    return bytes([sync]) + body + bytes([ck & 0xFF, ck >> 8])


def encode_request(cmd, seq, payload=b""):
    return _encode(SYNC_REQ, cmd, seq, payload)


def encode_response(status, seq, payload=b""):
    return _encode(SYNC_RSP, status, seq, payload)


def parse_frame(buf, sync):
    """Find the first frame in `buf` (skipping bytes before `sync`).
    Returns None if the frame is incomplete; ok=False on a bad checksum."""
    start = buf.find(bytes([sync]))
    if start < 0 or len(buf) - start < 4:
        return None
    code, seq, ln = buf[start + 1], buf[start + 2], buf[start + 3]
    end = start + 4 + ln + 2
    if len(buf) < end:
        return None
    body = buf[start + 1:start + 4 + ln]
    want = buf[end - 2] | (buf[end - 1] << 8)
    return Parsed(code, seq, bytes(buf[start + 4:start + 4 + ln]), end, checksum(body) == want)
