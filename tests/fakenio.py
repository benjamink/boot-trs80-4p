"""A Python stand-in for fujinet-nio's DiskDevice, spoken over FujiBus/SLIP, for testing the Z80 client."""
from fujinet import fujibus as fb
from fujinet import niodisk as nd

OK, DEVICE_NOT_FOUND, INVALID_REQUEST, DEVICE_BUSY, NOT_READY, IO_ERROR, TIMEOUT, INTERNAL, UNSUPPORTED = range(9)
CLOCK_DEVICE, CLOCK_GET_FORMAT = 0x45, 0x03
NOT_FOUND_STATUS = 1
ERR_NOT_MOUNTED, ERR_OUT_OF_RANGE, ERR_READ_ONLY, ERR_FILE_NOT_FOUND = 10, 12, 11, 4


class FakeNio:
    def __init__(self):
        self.dirs = {}                        # uri -> text lines of a directory listing
        self.library = {}                     # uri -> image bytes that Mount can open
        self.uris = {}                        # slot -> (uri, readonly)
        self.slots = {}                       # slot -> [bytearray image, readonly]
        self.requests = []                    # decoded request packets, in arrival order
        self.clock = None                     # (year, month, day, hour, minute, second) the Clock device reports; None = no clock device
        self.appstore = {}                    # (namespace, key) -> bytes, the AppStore device (F1h)
        self.catalog = {}                     # index -> (flags, uri), the SlotCatalog device (F2h)
        self.wifi_networks = []               # (ssid, rssi, auth)
        self.wifi_joined = None               # (ssid, password) after a TryJoin
        self.wifi_join_ok = True
        self.list_pages = True                # False: ListPages answers "unsupported" like older firmware
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
        if not pl[7 + n] & 4:                                  # entries, not text lines (what the portable fnsvc asks for)
            return self._entries(self.dirs[uri], start, room)
        lines = [ln.encode() + b"\n" for ln in self.dirs[uri]][start:]
        out, k = b"", 0
        for ln in lines:
            if len(out) + len(ln) > room:
                break
            out += ln; k += 1
        return OK, bytes([1, 4 | (k < len(lines))]) + (0).to_bytes(2, "little") + start.to_bytes(2, "little") \
            + k.to_bytes(2, "little") + len(out).to_bytes(2, "little") + out

    def _appstore(self, p):
        """AppStore v1 (fujinet-nio docs/host_service_protocol.md): 1 stat, 2 read, 3 write, 4 delete, 5 list."""
        pl, u16 = p.payload, lambda b, o: b[o] | b[o + 1] << 8
        nl = u16(pl, 1)
        ns = bytes(pl[3:3 + nl]).decode()
        kl = u16(pl, 3 + nl)
        key = bytes(pl[5 + nl:5 + nl + kl]).decode()
        off = 5 + nl + kl
        data = self.appstore.get((ns, key))
        if p.command == 1:
            return OK, bytes([1, data is not None]) + bytes(2) + len(data or b"").to_bytes(8, "little") + bytes(8)
        if p.command == 2:
            at, room = int.from_bytes(pl[off:off + 4], "little"), u16(pl, off + 4)
            if data is None:
                return OK, bytes([1, 0]) + bytes(2) + at.to_bytes(4, "little") + bytes(2)
            chunk = data[at:at + room]
            eof = at + len(chunk) >= len(data)
            return OK, bytes([1, 2 | eof]) + bytes(2) + at.to_bytes(4, "little") + len(chunk).to_bytes(2, "little") + chunk
        if p.command == 3:
            at, n = int.from_bytes(pl[off:off + 4], "little"), u16(pl, off + 4)
            cur = bytearray(data or b"")
            cur[at:at + n] = pl[off + 6:off + 6 + n]
            self.appstore[(ns, key)] = bytes(cur)
            return OK, bytes([1, 0]) + bytes(2) + at.to_bytes(4, "little") + n.to_bytes(2, "little")
        if p.command == 4:
            gone = self.appstore.pop((ns, key), None) is not None
            return OK, bytes([1, gone]) + bytes(2)
        return UNSUPPORTED, b""

    def _catalog(self, p):
        """SlotCatalog v1 (docs/slot_catalog_service_protocol.md): 1 get, 2 put, 3 delete."""
        pl = p.payload
        idx = pl[1]
        if p.command == 1:
            if idx not in self.catalog:
                return NOT_FOUND_STATUS, b""
            flags, uri = self.catalog[idx]
            return OK, bytes([1, flags, idx]) + len(uri).to_bytes(2, "little") + uri.encode()
        if p.command == 2:
            n = pl[3] | pl[4] << 8
            self.catalog[idx] = (pl[2] | 1, bytes(pl[5:5 + n]).decode())
            flags, uri = self.catalog[idx]
            return OK, bytes([1, flags, idx]) + len(uri).to_bytes(2, "little") + uri.encode()   # the stored entry
        if p.command == 3:
            gone = self.catalog.pop(idx, None) is not None
            return OK, bytes([1, int(gone), idx])
        if p.command == 4:                                     # Range: presence bitmap, then the entries from `cursor`
            lower, upper, cursor, maxuri = pl[1], pl[2], pl[3], pl[5]
            room = pl[6] | pl[7] << 8
            bits = bytearray((upper - lower) // 8 + 1)
            for i in self.catalog:
                if lower <= i <= upper:
                    bits[(i - lower) // 8] |= 1 << ((i - lower) % 8)
            out, count, nxt, more = b"", 0, upper + 1, 0
            for i in sorted(k for k in self.catalog if cursor <= k <= upper):
                flags, uri = self.catalog[i]
                e = bytes([i, flags, len(uri[:maxuri])]) + uri[:maxuri].encode()
                if len(bits) + len(out) + len(e) > room:
                    nxt, more = i, 1
                    break
                out += e; count += 1
            return OK, bytes([1, more, nxt & 0xFF, len(bits), count]) + len(out).to_bytes(2, "little") + bytes(bits) + out
        return UNSUPPORTED, b""

    @staticmethod
    def _entry(line):
        """'d    0 Nov 16 09:00 utils/' -> eflags, nameLen, name, size(4), reserved(4), mtime(4), reserved(4)."""
        parts = line.split()
        name = parts[-1].rstrip("/").encode()
        return (bytes([1 if parts[0] == "d" else 0, len(name)]) + name + int(parts[1]).to_bytes(4, "little")
                + bytes(4) + bytes(4) + bytes(4))

    def _wifi(self, p):
        """Wi-Fi v1 (fujinet-nio docs): 1 status, 4 scan, 6 try-join, 7 join status."""
        pl = p.payload
        if p.command == 1:
            ip = b"192.168.1.50" if self.wifi_joined else b""
            link = 2 if self.wifi_joined else 0
            return OK, bytes([1, link, 1, 0, 1, 0]) + bytes(6) + bytes([len(ip)]) + ip + bytes([0]) * 3 + bytes([0, 0, 0])
        if p.command == 4:
            start, limit = pl[1] | pl[2] << 8, pl[3]
            chunk = self.wifi_networks[start:start + limit]
            body = b"".join(bytes([len(s)]) + s.encode() + bytes(6) + bytes([r & 255, 6, a]) for s, r, a in chunk)
            return OK, bytes([1, int(start + limit < len(self.wifi_networks)), len(chunk)]) + body
        if p.command == 6:
            sl = pl[1]
            ssid = bytes(pl[2:2 + sl]).decode()
            pw = bytes(pl[3 + sl:3 + sl + pl[2 + sl]]).decode()
            if self.wifi_join_ok:
                self.wifi_joined = (ssid, pw)
            return OK, bytes([1])
        if p.command == 7:
            return OK, bytes([1, 2 if self.wifi_joined else 3])
        return UNSUPPORTED, b""

    @staticmethod
    def _page_entry(line):
        """eflags, nameLen, name, size(4), mtime(4)."""
        parts = line.split()
        name = parts[-1].rstrip("/").encode()
        return bytes([1 if parts[0] == "d" else 0, len(name)]) + name + int(parts[1]).to_bytes(4, "little") + bytes(4)

    def _pages(self, pl):
        """FileDevice ListPages: uri, startPage(2), pageSize(1), maxPayload(2), flags, maxName. Sorted: directories first."""
        n = pl[1] | pl[2] << 8
        uri = bytes(pl[3:3 + n]).decode()
        o = 3 + n
        start, size, room = pl[o] | pl[o + 1] << 8, pl[o + 2], pl[o + 3] | pl[o + 4] << 8
        if uri not in self.dirs:
            return IO_ERROR, b""
        lines = sorted(self.dirs[uri], key=lambda l: (l.split()[0] != "d", l.split()[-1].lower()))
        pages, used, page = b"", 0, start
        while page * size < len(lines):
            chunk = lines[page * size:(page + 1) * size]
            body = b"".join(self._page_entry(l) for l in chunk)
            if used + 3 + len(body) > room:
                break
            pages += bytes([len(chunk)]) + len(body).to_bytes(2, "little") + body
            used += 3 + len(body)
            page += 1
        npages = page - start
        more = page * size < len(lines)
        return OK, bytes([1, int(more), 0, 0]) + len(lines).to_bytes(4, "little") + bytes(3) + bytes([npages]) + pages

    def _entries(self, lines, start, room):
        out, k = b"", 0
        for ln in lines[start:]:
            e = self._entry(ln)
            if len(out) + len(e) + 10 > room:
                break
            out += e; k += 1
        more = start + k < len(lines)
        return OK, bytes([1, int(more)]) + bytes(2) + start.to_bytes(2, "little") + k.to_bytes(2, "little") \
            + len(out).to_bytes(2, "little") + out

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
            status, payload = OK, bytes([1, getattr(self, "clock_format_echo", p.payload[1]), y // 100, y % 100, mo, d, h, mi, sec])      # simple format: century first
        elif p.device == 0xF1:
            status, payload = self._appstore(p)
        elif p.device == 0xF2:
            status, payload = self._catalog(p)
        elif p.device == 0xF3:
            status, payload = self._wifi(p)
        elif p.device == nd.FILE_DEVICE and p.command == 7 and self.list_pages:
            status, payload = self._pages(p.payload)
        elif p.device == nd.FILE_DEVICE and p.command == 7:
            status, payload = UNSUPPORTED, b""
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
