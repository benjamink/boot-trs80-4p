"""The resident LS-DOS disk driver (fujinet/z80/fujidrv.asm) in the Z80 interpreter, with a FakeNio on the simulated UART.

ABI under test (as MEMDISK/FLOPPY drivers of LS-DOS 6 use it): B = function, D = cylinder, E = sector, HL = buffer,
IY = the drive's DCT entry; returns Z = ok, NZ with A = LS-DOS error number. Registers BC, DE, HL are preserved.
"""
import os, re, shutil, subprocess, unittest

from fujinet import fujibus as fb
from fujinet import niodisk as nd
from tests.fakenio import FakeNio
from tests.z80emu import Z80, load_hex

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DCT, BUF = 0x0470 + 20, 0xC000            # drive 2's entry in an LS-DOS-like table
(DCSTAT, SELECT, DCINIT, DCRES, RSTOR, STEPI, SEEK, TSTBSY, RDHDR, RDSEC, VRSEC, RDTRK, HDFMT, WRSEC, WRSYS,
 WRTRK) = range(16)
E_DNF, E_SYSREC, E_NODEV, E_RERR, E_WERR, E_WPROT = 5, 6, 8, 4, 12, 15


def image():
    return bytes((i * 7 + (i >> 8) * 3) & 255 for i in range(720 * 256))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class DriverTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT, "build/fujidrv.hex"], check=True, stdout=subprocess.DEVNULL)
        self.cpu = Z80()
        load_hex(self.cpu, os.path.join(ROOT, "build", "fujidrv.hex"))
        with open(os.path.join(ROOT, "build", "fujidrv.sym")) as f:
            self.sym = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", f.read(), re.M)}
        self.cpu.mem[self.sym["recv_packet"] + 1] = 1                   # one short wait instead of four seconds
        self.nio, self.rx, self.writes = FakeNio(), [], []
        self.img = image()
        self.nio.mount(3, self.img)                                     # drive 2 = NIO slot 3
        self.dec = fb.SlipDecoder()
        self.cpu.io_in, self.cpu.io_out = self._in, self._out
        # DCT entry: JP driver, flags (DDEN), alien controller + DD capable, slot, last cylinder, sectors-1, gran, dir cyl
        self.cpu.mem[DCT:DCT + 10] = bytes([0xC3, 0, 0, 0x44, 0x50, 3, 39, 17, 0x45, 20])

    def _in(self, port):
        if port == 0xEA:
            return 0x80 if self.rx else 0
        return self.rx.pop(0) if port == 0xEB else 0xFF

    def _out(self, port, val):
        self.writes.append((port, val))
        if port == 0xEB:
            for frame in self.dec.feed(bytes([val])):
                self.rx.extend(self.nio.handle(frame))

    def call(self, func, cyl=0, sec=0, hl=BUF, bc=0x1234, de=None):
        c = self.cpu
        c.R[0], c.R[1] = func, bc & 255                                 # B = function, C = anything
        c.R[1] = bc & 255
        c.set_rp(2, 3, (cyl << 8 | sec) if de is None else de)
        c.set_rp(4, 5, hl)
        c.iy = DCT
        c.sp = 0x7000
        c.iff = False
        c.run_call(self.sym["drv_entry"], max_steps=60_000_000)
        return c.R[7], not (c.F & 0x40)                                 # (A, NZ?)

    def nio_requests(self, command=None):
        return [r for r in self.nio.requests if command is None or r.command == command]

    # ---- reads ----
    def test_rdsec_maps_cylinder_and_sector_to_the_lba_and_returns_the_data(self):
        a, nz = self.call(RDSEC, cyl=3, sec=5)
        self.assertEqual((a, nz), (0, False))
        lba = 3 * 18 + 5
        self.assertEqual(bytes(self.cpu.mem[BUF:BUF + 256]), self.img[lba * 256:(lba + 1) * 256])
        self.assertEqual(self.nio_requests(nd.READ_SECTOR)[-1].payload[1:6], bytes([3]) + lba.to_bytes(4, "little"))

    def test_rdtrk_behaves_as_rdsec(self):
        self.call(RDTRK, cyl=1, sec=2)
        self.assertEqual(bytes(self.cpu.mem[BUF:BUF + 256]), self.img[20 * 256:21 * 256])

    def test_reading_the_directory_cylinder_delivers_the_data_but_reports_a_system_record(self):
        a, nz = self.call(RDSEC, cyl=20, sec=1)
        self.assertEqual((a, nz), (E_SYSREC, True))
        lba = 20 * 18 + 1
        self.assertEqual(bytes(self.cpu.mem[BUF:BUF + 256]), self.img[lba * 256:(lba + 1) * 256])

    def test_sector_past_the_end_of_the_cylinder_or_image_is_record_not_found(self):
        self.assertEqual(self.call(RDSEC, cyl=2, sec=18), (E_DNF, True))
        self.assertEqual(self.call(RDSEC, cyl=40, sec=0), (E_DNF, True))
        self.assertEqual(self.nio_requests(nd.READ_SECTOR), [])         # refused without asking the FujiNet

    def test_slot_comes_from_the_dct(self):
        self.nio.mount(5, bytes(range(256)) * 720)
        self.cpu.mem[DCT + 5] = 5
        self.call(RDSEC, cyl=0, sec=1)
        self.assertEqual(bytes(self.cpu.mem[BUF:BUF + 256]), bytes(range(256)))

    # ---- writes ----
    def test_wrsec_and_wrsys_write_through(self):
        self.cpu.mem[BUF:BUF + 256] = bytes([0xC0, 0xDB] * 128)
        for func, lba in ((WRSEC, 18 + 4), (WRSYS, 18 * 20 + 2)):
            cyl, sec = divmod(lba, 18)
            self.assertEqual(self.call(func, cyl=cyl, sec=sec), (0, False))
            self.assertEqual(bytes(self.nio.slots[3][0][lba * 256:(lba + 1) * 256]), bytes([0xC0, 0xDB] * 128))

    def test_software_write_protect_refuses_writes_without_touching_the_fujinet(self):
        self.cpu.mem[DCT + 3] |= 0x80
        self.assertEqual(self.call(WRSEC, cyl=1, sec=1), (E_WPROT, True))
        self.assertEqual(self.nio_requests(nd.WRITE_SECTOR), [])

    def test_read_only_image_is_write_protected(self):
        self.nio.mount(3, self.img, readonly=True)
        self.assertEqual(self.call(WRSEC, cyl=1, sec=1), (E_WPROT, True))

    def test_formatting_calls_are_refused(self):
        self.assertEqual(self.call(HDFMT), (E_NODEV, True))
        self.assertEqual(self.call(WRTRK), (E_NODEV, True))

    # ---- state and housekeeping functions ----
    def test_select_is_ok_when_an_image_is_mounted_and_remembered(self):
        self.assertEqual(self.call(SELECT), (0, False))
        n = len(self.nio.requests)
        self.assertEqual(self.call(SELECT), (0, False))
        self.assertEqual(len(self.nio.requests), n)                     # cached: no second round trip

    def test_nothing_mounted_is_device_not_available(self):
        del self.nio.slots[3]
        self.assertEqual(self.call(SELECT), (E_NODEV, True))
        self.assertEqual(self.call(RDSEC, cyl=1, sec=1), (E_NODEV, True))
        self.assertEqual(self.call(WRSEC, cyl=1, sec=1), (E_NODEV, True))

    def test_media_that_vanishes_is_noticed_on_the_next_select(self):
        self.assertEqual(self.call(SELECT), (0, False))
        self.call(RDSEC, cyl=1, sec=1)
        del self.nio.slots[3]
        self.assertEqual(self.call(RDSEC, cyl=1, sec=1), (E_NODEV, True))   # the failure clears the cache
        self.assertEqual(self.call(SELECT), (E_NODEV, True))

    def test_verify_succeeds_without_io_except_on_the_directory_cylinder(self):
        self.assertEqual(self.call(VRSEC, cyl=3, sec=3), (0, False))
        self.assertEqual(self.call(VRSEC, cyl=20, sec=3), (E_SYSREC, True))
        self.assertEqual(self.nio.requests, [])

    def test_the_motion_and_status_functions_are_harmless_successes(self):
        for func in (DCSTAT, DCINIT, DCRES, RSTOR, STEPI, SEEK, TSTBSY, RDHDR, 16, 99):
            self.assertEqual(self.call(func), (0, False), func)
        self.assertEqual(self.nio.requests, [])

    # ---- faults ----
    def test_no_answer_is_a_read_or_write_error_not_a_hang(self):
        self.nio.mangle = [lambda w: b""] * 12
        self.assertEqual(self.call(RDSEC, cyl=1, sec=1), (E_RERR, True))
        self.assertEqual(self.call(WRSEC, cyl=1, sec=1), (E_WERR, True))

    def test_one_corrupted_answer_is_retried_transparently(self):
        self.nio.mangle = [lambda w: bytes(w[:5]) + bytes([w[5] ^ 1]) + bytes(w[6:])]
        self.assertEqual(self.call(RDSEC, cyl=1, sec=1), (0, False))

    # ---- conventions ----
    def test_registers_are_preserved_and_interrupts_end_up_enabled(self):
        self.call(RDSEC, cyl=2, sec=3, hl=BUF, bc=0xBEEF)
        c = self.cpu
        self.assertEqual((c.rp(0, 1), c.rp(2, 3), c.hl()), (RDSEC << 8 | 0xEF, 2 << 8 | 3, BUF))   # B = the function, C kept
        self.assertTrue(c.iff)

    def test_uart_is_programmed_like_the_rom_each_time(self):
        self.call(SELECT)
        setup = [w for w in self.writes if w[0] in (0xE8, 0xE9, 0xEA)]
        self.assertEqual(setup[:3], [(0xEA, 0x64), (0xE9, 0xFF), (0xE8, 0xFF)])

    def test_module_header_names_the_driver_for_gtmod(self):
        base = self.sym["mod_hdr"]
        m = self.cpu.mem
        self.assertEqual(m[base], 0x18)                                 # JR over the header
        self.assertEqual(bytes(m[base + 4:base + 8]), bytes([3]) + b"$FJ")
        self.assertEqual(m[base + 2] | m[base + 3] << 8, self.sym["drv_end"] - 1)


if __name__ == "__main__":
    unittest.main()
