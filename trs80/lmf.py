"""TRSDOS load-module format and Intel HEX helpers."""


def lmf_data_block(addr, data):
    """Type 01 block: [01][len][addr lo][addr hi][data]; len counts addr+data, 256 -> 0."""
    assert 0 < len(data) <= 254
    return bytes([0x01, (len(data) + 2) & 0xFF, addr & 0xFF, addr >> 8]) + data


def lmf_entry(addr):
    return bytes([0x02, 0x02, addr & 0xFF, addr >> 8])


def build_lmf(segments, entry, block=16):
    """segments: {addr: bytes}. Splits into records of `block` data bytes."""
    out = bytearray()
    for addr, data in sorted(segments.items()):
        for i in range(0, len(data), block):
            out += lmf_data_block(addr + i, data[i:i + block])
    out += lmf_entry(entry)
    return bytes(out)


def parse_hex(path):
    """Intel HEX -> (contiguous segments dict, entry or None)."""
    mem, entry = {}, None
    with open(path) as f:
        lines = f.readlines()
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if line[0] != ':':
            raise SystemExit(f"{path}:{n}: not an Intel HEX line")
        raw = bytes.fromhex(line[1:])
        if sum(raw) & 0xFF:
            raise SystemExit(f"{path}:{n}: checksum error")
        ln, addr, typ, data = raw[0], (raw[1] << 8) | raw[2], raw[3], raw[4:-1]
        if typ == 0:
            for i, b in enumerate(data):
                mem[addr + i] = b
        elif typ == 1:
            break
        elif typ in (3, 5):
            # Beattie's tools put the entry point in the address field of an empty type-03 record
            entry = addr if ln == 0 else int.from_bytes(data[-2:], "big")
    segs, start, buf = {}, None, bytearray()
    for a in sorted(mem):
        if start is not None and a == start + len(buf):
            buf.append(mem[a])
        else:
            if start is not None:
                segs[start] = bytes(buf)
            start, buf = a, bytearray([mem[a]])
    if start is not None:
        segs[start] = bytes(buf)
    return segs, entry


def parse_lmf(blob):
    """Load module -> (contiguous segments dict, entry or None). Stops at the first
    transfer-address record; other record types (comments) are skipped."""
    mem, entry, i = {}, None, 0
    while i < len(blob):
        if i + 2 > len(blob):
            raise ValueError("truncated load module")
        typ, ln = blob[i], blob[i + 1] or 256
        body = blob[i + 2:i + 2 + ln]
        if len(body) < ln:
            raise ValueError("truncated load module")
        i += 2 + ln
        if typ == 1:
            addr = body[0] | (body[1] << 8)
            for k, b in enumerate(body[2:]):
                mem[addr + k] = b
        elif typ == 2:
            entry = body[0] | (body[1] << 8)
            break
    segs, start, buf = {}, None, bytearray()
    for a in sorted(mem):
        if start is not None and a == start + len(buf):
            buf.append(mem[a])
        else:
            if start is not None:
                segs[start] = bytes(buf)
            start, buf = a, bytearray([mem[a]])
    if start is not None:
        segs[start] = bytes(buf)
    return segs, entry
