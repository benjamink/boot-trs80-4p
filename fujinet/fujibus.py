# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""FujiBus packets inside SLIP frames: the wire format of fujinet-nio's RS-232 channel.

Written from fujinet-nio's docs/protocol_reference.md (GPL-3.0 project; this repo is meant to be
contributed upstream). Packet: 6-byte header (device, command, length u16 LE incl. header, checksum, first
descriptor byte), more descriptor bytes, parameters (little endian), payload. A response carries the status
as its single U8 parameter.
"""
from dataclasses import dataclass, field

SLIP_END, SLIP_ESC, SLIP_ESC_END, SLIP_ESC_ESC = 0xC0, 0xDB, 0xDC, 0xDD
HEADER = 6
_NUM_FIELDS = [0, 1, 2, 3, 4, 1, 2, 1]
_FIELD_SIZE = [0, 1, 1, 1, 1, 2, 2, 4]


class PacketError(Exception):
    pass


@dataclass
class Packet:
    device: int
    command: int
    params: list = field(default_factory=list)
    payload: bytes = b""


def checksum(data):
    """Sum with the carry folded back in after every byte (the packet is summed with its checksum byte zeroed)."""
    c = 0
    for b in data:
        c += b
        c = (c >> 8) + (c & 0xFF)
    return c & 0xFF


def _descriptor_for(params):
    sizes = {s for _, s in params}
    n = len(params)
    if n == 0:
        return 0
    if sizes == {1} and n <= 4:
        return n
    if sizes == {2} and n <= 2:
        return 4 + n
    if sizes == {4} and n == 1:
        return 7
    raise ValueError("unsupported parameter layout")


def build_packet(device, command, payload=b"", params=()):
    params = list(params)
    descr = _descriptor_for(params)
    body = b"".join(v.to_bytes(s, "little") for v, s in params) + bytes(payload)
    length = HEADER + len(body)
    raw = bytes([device, command, length & 255, length >> 8, 0, descr]) + body
    return raw[:4] + bytes([checksum(raw)]) + raw[5:]


def build_response(device, command, status, payload=b""):
    return build_packet(device, command, payload, params=[(status, 1)])


def parse_packet(raw):
    if len(raw) < HEADER:
        raise PacketError("shorter than a header")
    if (raw[2] | raw[3] << 8) != len(raw):
        raise PacketError("length field does not match the packet")
    if checksum(raw[:4] + b"\x00" + raw[5:]) != raw[4]:
        raise PacketError("bad checksum")
    pos, descrs = HEADER - 1, []
    while True:
        d = raw[pos]
        descrs.append(d)
        pos += 1
        if not d & 0x80:
            break
        if pos >= len(raw):
            raise PacketError("missing descriptor continuation")
    params = []
    for d in descrs:
        for _ in range(_NUM_FIELDS[d & 7]):
            size = _FIELD_SIZE[d & 7]
            if pos + size > len(raw):
                raise PacketError("parameters run past the packet")
            params.append(int.from_bytes(raw[pos:pos + size], "little"))
            pos += size
    return Packet(raw[0], raw[1], params, bytes(raw[pos:]))


def slip_encode(raw):
    out = bytearray([SLIP_END])
    for b in raw:
        out += {SLIP_END: b"\xDB\xDC", SLIP_ESC: b"\xDB\xDD"}.get(b, bytes([b]))
    out.append(SLIP_END)
    return bytes(out)


class SlipDecoder:
    """feed(bytes) -> list of complete decoded frames. Empty frames are ignored; a bad escape drops the frame."""
    def __init__(self):
        self.buf, self.esc, self.bad = bytearray(), False, False

    def feed(self, data):
        frames = []
        for b in data:
            if b == SLIP_END:
                if self.buf and not self.bad and not self.esc:
                    frames.append(bytes(self.buf))
                self.buf, self.esc, self.bad = bytearray(), False, False
            elif self.esc:
                self.esc = False
                if b == SLIP_ESC_END:
                    self.buf.append(SLIP_END)
                elif b == SLIP_ESC_ESC:
                    self.buf.append(SLIP_ESC)
                else:
                    self.bad = True
            elif b == SLIP_ESC:
                self.esc = True
            else:
                self.buf.append(b)
        return frames
