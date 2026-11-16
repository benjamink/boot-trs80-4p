"""z80/nioclient.asm in the Z80 interpreter, talking FujiBus/SLIP to tests/fakenio.FakeNio through a simulated UART."""
import os, random, re, shutil, subprocess, unittest

from tests.fakenio import FakeNio
from tests.z80emu import Z80, load_hex
from trs80 import fujibus as fb
from trs80 import niodisk as nd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PB, NIO_TX, NIO_RX, BUF = 0x9F00, 0xA000, 0xA300, 0xC000
ENTRY = dict(exchange=0x8000, request=0x8003, info=0x8006, read=0x8009, write=0x800C)


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class NioClientTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT, "build/nioclient.hex"], check=True, stdout=subprocess.DEVNULL)
        self.cpu = Z80()
        load_hex(self.cpu, os.path.join(ROOT, "build", "nioclient.hex"))
        with open(os.path.join(ROOT, "build", "nioclient.sym")) as f:
            self.sym = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", f.read(), re.M)}
        # shorten the answer wait from ~4 s to one timeout: patch the immediate of "ld e,40"
        self.cpu.mem[self.sym["recv_packet"] + 1] = 1
        self.nio, self.rx, self.sent = FakeNio(), [], bytearray()
        self.dec = fb.SlipDecoder()
        self.noise = b""
        self.cpu.io_in, self.cpu.io_out = self._in, self._out
        self.nio.mount(1, bytes((i * 31 + (i >> 8)) & 255 for i in range(720 * 256)))

    def _in(self, port):
        if port == 0xEA:
            return 0x80 if self.rx else 0
        if port == 0xEB:
            return self.rx.pop(0)
        return 0xFF

    def _out(self, port, val):
        if port == 0xEB:
            self.sent.append(val)
            for frame in self.dec.feed(bytes([val])):
                self.rx.extend(self.noise + self.nio.handle(frame))

    def call(self, name, a=0, b=0, hl=0, de=0):
        c = self.cpu
        c.R[7] = a; c.R[0] = b
        c.set_rp(4, 5, hl); c.set_rp(2, 3, de)
        c.sp = 0x7000
        c.run_call(ENTRY[name], max_steps=60_000_000)
        return c.R[7], c.F & 1, c.hl(), c.rp(2, 3)

    def pb(self, **kw):
        m = self.cpu.mem
        m[PB] = kw.get("slot", 1)
        m[PB + 1:PB + 5] = kw.get("lba", 0).to_bytes(4, "little")
        m[PB + 5:PB + 7] = kw.get("buf", BUF).to_bytes(2, "little")

    def result(self):
        m = self.cpu.mem
        return dict(status=m[PB + 7], error=m[PB + 8], got=m[PB + 9] | m[PB + 10] << 8, disk_error=m[PB + 11])

    # ---- raw request ----
    def test_request_bytes_on_the_wire_equal_the_reference_codec(self):
        payload = bytes([1, 0xC0, 0xDB, 0xDB, 0xC0, 5, 6])              # needs every escape
        self.cpu.mem[0xB000:0xB000 + len(payload)] = payload
        self.call("request", a=0xFC, b=5, hl=0xB000, de=len(payload))
        self.assertEqual(bytes(self.sent), fb.slip_encode(fb.build_packet(0xFC, 5, payload)))

    def test_request_returns_status_and_payload(self):
        self.cpu.mem[0xB000:0xB002] = nd.info_request(1)
        a, cf, hl, de = self.call("request", a=0xFC, b=5, hl=0xB000, de=2)
        self.assertEqual((cf, a, de), (0, 0, 13))
        self.assertEqual(nd.parse_info_response(bytes(self.cpu.mem[hl:hl + de])).sector_count, 720)

    def test_unknown_device_comes_back_as_nio_status_not_a_transport_error(self):
        a, cf, hl, de = self.call("request", a=0x42, b=1, hl=0xB000, de=0)
        self.assertEqual((cf, a), (0, 1))                               # DeviceNotFound

    # ---- DiskDevice wrappers ----
    def test_disk_info(self):
        self.pb(slot=1)
        self.call("info")
        m = self.cpu.mem
        self.assertEqual((self.result()["error"], m[PB + 12] & 1, m[PB + 13] | m[PB + 14] << 8,
                          int.from_bytes(m[PB + 15:PB + 19], "little")), (0, 1, 256, 720))

    def test_disk_read_returns_the_sector(self):
        for lba in (0, 1, 359, 719):
            self.pb(lba=lba)
            self.call("read")
            self.assertEqual(self.result()["error"], 0, lba)
            self.assertEqual(bytes(self.cpu.mem[BUF:BUF + 256]), bytes(self.nio.slots[1][0][lba * 256:(lba + 1) * 256]), lba)
            self.assertEqual(self.result()["got"], 256)

    def test_disk_write_updates_the_image_even_with_escape_bytes(self):
        data = bytes([0xC0, 0xDB] * 128)
        self.cpu.mem[BUF:BUF + 256] = data
        self.pb(lba=100)
        self.call("write")
        self.assertEqual(self.result()["error"], 0)
        self.assertEqual(bytes(self.nio.slots[1][0][100 * 256:101 * 256]), data)
        self.pb(lba=100, buf=BUF + 0x400)
        self.call("read")
        self.assertEqual(bytes(self.cpu.mem[BUF + 0x400:BUF + 0x500]), data)

    def test_random_sectors_round_trip(self):
        rnd = random.Random(5)
        for _ in range(6):
            lba = rnd.randrange(720)
            data = bytes(rnd.choice([0xC0, 0xDB, 0xDC, 0xDD, rnd.randrange(256)]) for _ in range(256))
            self.cpu.mem[BUF:BUF + 256] = data
            self.pb(lba=lba)
            self.call("write")
            self.pb(lba=lba, buf=BUF + 0x400)
            self.call("read")
            self.assertEqual(bytes(self.cpu.mem[BUF + 0x400:BUF + 0x500]), data, lba)

    def test_nio_refusal_reports_the_disk_error(self):
        self.pb(lba=720)
        self.call("read")
        r = self.result()
        self.assertEqual((r["error"], r["status"], r["disk_error"]), (6, 2, 12))     # InvalidRequest / OutOfRange
        self.pb(slot=3)
        self.call("read")
        r = self.result()
        self.assertEqual((r["error"], r["status"], r["disk_error"]), (6, 4, 10))     # NotReady / NotMounted

    def test_write_to_a_read_only_slot_is_refused(self):
        self.nio.mount(2, bytes(256 * 4), readonly=True)
        self.pb(slot=2)
        self.call("write")
        self.assertEqual((self.result()["error"], self.result()["disk_error"]), (6, 11))
        self.assertEqual(bytes(self.nio.slots[2][0]), bytes(1024))

    # ---- transport faults ----
    def test_corrupt_checksum_is_retried(self):
        def flip(w):
            return w[:5] + bytes([w[5] ^ 1]) + w[6:]                    # checksum byte of the answer
        self.nio.mangle = [flip]
        self.pb(lba=7)
        self.call("read")
        self.assertEqual(self.result()["error"], 0)
        self.assertEqual(len(self.nio.requests), 2)

    def test_lost_answer_is_retried_after_a_timeout(self):
        self.nio.mangle = [lambda w: b""]
        self.pb(lba=7)
        self.call("read")
        self.assertEqual(self.result()["error"], 0)
        self.assertEqual(len(self.nio.requests), 2)

    def test_gives_up_after_three_tries_with_the_last_error(self):
        flip = lambda w: w[:5] + bytes([w[5] ^ 1]) + w[6:]
        self.nio.mangle = [flip, flip, flip, flip]
        self.pb(lba=7)
        self.call("read")
        self.assertEqual((self.result()["error"], len(self.nio.requests)), (4, 3))

    def test_line_noise_before_the_frame_is_ignored(self):
        self.noise = b"\x01\x02\x03"
        self.pb(lba=9)
        self.call("read")
        self.assertEqual(self.result()["error"], 0)

    def test_unsupported_descriptor_is_not_retried(self):
        def bad_descr(w):
            raw = bytearray(fb.SlipDecoder().feed(w)[0])
            raw[5] = 0x02                                               # two 1-byte params
            raw[4] = 0
            raw[4] = fb.checksum(bytes(raw))
            return fb.slip_encode(bytes(raw))
        self.nio.mangle = [bad_descr, bad_descr, bad_descr]
        self.pb(lba=7)
        self.call("read")
        self.assertEqual((self.result()["error"], len(self.nio.requests)), (5, 1))

    def test_oversized_answer_is_a_length_error_not_a_memory_overwrite(self):
        guard = bytes([0x5A]) * 16
        self.cpu.mem[NIO_RX + 0x300:NIO_RX + 0x310] = guard
        self.nio.mangle = [lambda w: b"\xC0" + b"\x11" * 0x400 + b"\xC0"] * 4
        self.pb(lba=7)
        self.call("read")
        self.assertEqual(self.result()["error"], 3)
        self.assertEqual(bytes(self.cpu.mem[NIO_RX + 0x300:NIO_RX + 0x310]), guard)

    def test_length_field_mismatch_is_a_length_error(self):
        def trunc(w):
            raw = bytearray(fb.SlipDecoder().feed(w)[0])
            return fb.slip_encode(bytes(raw[:-3]))
        self.nio.mangle = [trunc] * 4
        self.pb(lba=7)
        self.call("read")
        self.assertEqual(self.result()["error"], 3)


if __name__ == "__main__":
    unittest.main()
