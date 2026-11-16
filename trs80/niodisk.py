"""DiskDevice (wire device 0xFC) payloads, per fujinet-nio docs/disk_device_protocol.md. All little endian."""
from dataclasses import dataclass

DEVICE = 0xFC
MOUNT, UNMOUNT, READ_SECTOR, WRITE_SECTOR, INFO = 0x01, 0x02, 0x03, 0x04, 0x05
VERSION = 1


def mount_request(slot, uri, readonly=False, type_=0, sector_size_hint=0):
    u = uri.encode()
    # version, slot, flags(bit0 = readonly), type, sector_size_hint (u16), uri (u16 length + bytes)
    return bytes([VERSION, slot, 1 if readonly else 0, type_]) + sector_size_hint.to_bytes(2, "little") + len(u).to_bytes(2, "little") + u


def read_sector_request(slot, lba, max_bytes):
    return bytes([VERSION, slot]) + lba.to_bytes(4, "little") + max_bytes.to_bytes(2, "little")


def write_sector_request(slot, lba, data):
    return bytes([VERSION, slot]) + lba.to_bytes(4, "little") + len(data).to_bytes(2, "little") + bytes(data)


def info_request(slot):
    return bytes([VERSION, slot])


@dataclass
class ReadResponse:
    slot: int
    lba: int
    data: bytes
    truncated: bool


def read_response(slot, lba, data, truncated=False):
    return (bytes([VERSION, 1 if truncated else 0, 0, 0, slot]) + lba.to_bytes(4, "little")
            + len(data).to_bytes(2, "little") + bytes(data))


def parse_read_response(p):
    n = p[9] | p[10] << 8
    return ReadResponse(p[4], int.from_bytes(p[5:9], "little"), bytes(p[11:11 + n]), bool(p[1] & 1))


@dataclass
class Info:
    inserted: bool
    readonly: bool
    slot: int
    type: int
    sector_size: int
    sector_count: int
    last_error: int


def info_response(slot, sector_size, sector_count, inserted=True, readonly=False, type_=4, last_error=0):
    flags = (1 if inserted else 0) | (2 if readonly else 0) | 0x10
    return (bytes([VERSION, flags, 0, 0, slot, type_]) + sector_size.to_bytes(2, "little")
            + sector_count.to_bytes(4, "little") + bytes([last_error]))


def parse_info_response(p):
    return Info(bool(p[1] & 1), bool(p[1] & 2), p[4], p[5], p[6] | p[7] << 8,
                int.from_bytes(p[8:12], "little"), p[12] if len(p) > 12 else 0)
