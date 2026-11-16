"""fujinet/z80/nioboot.asm: the loader the ROM's serial loader starts instead of a floppy boot (Z80 interpreter + FakeNio)."""
import os, re, shutil, subprocess, unittest

from fujinet import fujibus as fb
from tests.fakenio import FakeNio
from tests.z80emu import Z80, load_hex

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def image():
    return bytes((i * 11 + (i >> 8) * 5) & 255 for i in range(720 * 256))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class NiobootTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT, "build/nioboot.hex"], check=True, stdout=subprocess.DEVNULL)
        self.cpu = c = Z80()
        load_hex(c, os.path.join(ROOT, "build", "nioboot.hex"))
        with open(os.path.join(ROOT, "build", "nioboot.sym")) as f:
            self.sym = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", f.read(), re.M)}
        c.mem[self.sym["recv_packet"] + 1] = 1
        self.nio, self.img, self.rx, self.out = FakeNio(), image(), [], []
        self.nio.mount(1, self.img)                                     # drive 0 = slot 1
        dec = fb.SlipDecoder()

        def io_in(port):
            if port == 0xEA:
                return 0x80 if self.rx else 0
            return self.rx.pop(0) if port == 0xEB else 0xFF

        def io_out(port, val):
            self.out.append((port, val))
            if port == 0xEB:
                for frame in dec.feed(bytes([val])):
                    self.rx.extend(self.nio.handle(frame))
        c.io_in, c.io_out = io_in, io_out
        c.pc, c.sp = 0x5000, 0x7000

    def run_to_boot_sector(self):
        c = self.cpu
        for _ in range(30_000_000):
            if c.pc == 0x4300:
                return
            c.step()
        self.fail("never reached 4300h")

    def sector(self, lba):
        return self.img[lba * 256:(lba + 1) * 256]

    def test_loads_the_boot_sector_and_jumps_to_it_with_the_rom_switched_out(self):
        self.run_to_boot_sector()
        got, want = bytearray(self.cpu.mem[0x4300:0x4400]), bytearray(self.sector(1))      # cylinder 0, sector ID 1
        self.assertEqual(got[0x96:0x99], b"\xC3" + got[0x97:0x99])                          # the jump patched over the FDC routine
        got[0x96:0x99] = want[0x96:0x99] = b"\0\0\0"
        self.assertEqual(got, want)
        self.assertIn((0x9C, 0), self.out)                                        # boot ROM mapped out
        self.assertFalse(self.cpu.iff)

    def test_leaves_the_rom_boot_variables_for_a_floppy_boot(self):
        self.run_to_boot_sector()
        m = self.cpu.mem
        self.assertEqual((m[0x4055], m[0x4056]), (1, 1))                          # boot type floppy, 256-byte sector

    def test_the_boot_sectors_fdc_routine_now_reads_from_the_fujinet(self):
        self.run_to_boot_sector()
        c, m = self.cpu, self.cpu.mem
        self.assertEqual(m[0x4396], 0xC3)
        entry = m[0x4397] | m[0x4398] << 8
        # what the boot sector's callers do: D = cylinder, E = sector, HL = destination; A & 1Ch must be 0
        c.set_rp(2, 3, 3 << 8 | 7)
        c.set_rp(4, 5, 0x1000)
        c.set_rp(0, 1, 0x0505)
        c.sp, c.iff = 0x7000, False
        c.run_call(entry, max_steps=60_000_000)
        self.assertEqual(c.R[7] & 0x1C, 0)
        self.assertEqual(c.rp(2, 3), 3 << 8 | 7)                                  # D and E untouched
        self.assertEqual(bytes(m[0x1000:0x1100]), self.sector(3 * 18 + 7))
        self.assertFalse(c.iff)

    def test_the_directory_cylinder_reads_without_a_system_record_error(self):
        self.run_to_boot_sector()
        c, m = self.cpu, self.cpu.mem
        c.set_rp(2, 3, 20 << 8 | 4)
        c.set_rp(4, 5, 0x1200)
        c.run_call(m[0x4397] | m[0x4398] << 8, max_steps=60_000_000)
        self.assertEqual(c.R[7] & 0x1C, 0)
        self.assertEqual(bytes(m[0x1200:0x1300]), self.sector(20 * 18 + 4))

    def test_after_the_last_boot_sector_load_drive_0_is_pointed_at_the_driver(self):
        self.run_to_boot_sector()
        c, m = self.cpu, self.cpu.mem
        entry = m[0x4397] | m[0x4398] << 8
        m[0x0470:0x047A] = bytes([0xC3, 0x3D, 0x0E, 0x44, 0xC1, 0x15, 0x27, 0x11, 0x45, 0x14])   # as the boot loads it
        for sec in range(0, 15):                                           # earlier sectors leave it alone
            c.set_rp(2, 3, sec); c.set_rp(4, 5, 0x8000)
            c.run_call(entry, max_steps=60_000_000)
        self.assertEqual(bytes(m[0x0470:0x0473]), bytes([0xC3, 0x3D, 0x0E]))
        c.set_rp(2, 3, 15); c.set_rp(4, 5, 0x1100)
        c.run_call(entry, max_steps=60_000_000)
        drv_entry = self.sym["drv_entry"]
        self.assertEqual(bytes(m[0x0470:0x047A]), bytes([0xC3, drv_entry & 255, drv_entry >> 8, 0x44, 0xC1, 0x15, 0x27, 0x11, 0x45, 0x14]))

    def test_the_driver_serves_slot_1_whatever_dct_plus_5_says(self):
        self.run_to_boot_sector()
        self.assertEqual(self.cpu.mem[self.sym["v_slot"]], 1)

    def test_a_dead_link_stops_before_leaving_the_rom(self):
        self.nio.slots.clear()
        c = self.cpu
        for _ in range(3_000_000):
            c.step()
            self.assertNotEqual(c.pc, 0x4300)
        self.assertNotIn((0x9C, 0), self.out)


if __name__ == "__main__":
    unittest.main()
