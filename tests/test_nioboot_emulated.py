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

    def test_the_real_floppy_drives_1_to_7_are_disabled_so_ls_dos_does_not_probe_hardware_that_may_be_empty(self):
        # on the 4P an empty drive makes LS-DOS's boot-time drive probe hang with the drive light on
        self.run_to_boot_sector()
        c, m = self.cpu, self.cpu.mem
        for d in range(8):
            m[0x0470 + 10 * d:0x047A + 10 * d] = bytes([0xC3, 0x3D, 0x0E, 0x44, 0xC1, 0x15, 0x27, 0x11, 0x45, 0x14])
        c.set_rp(2, 3, 15); c.set_rp(4, 5, 0x1100); c.set_rp(0, 1, 0x1234)
        c.run_call(m[0x4397] | m[0x4398] << 8, max_steps=60_000_000)
        self.assertEqual((c.R[1], c.rp(2, 3)), (0x34, 15))                          # the boot sector relies on C and DE (cylinder, sector) surviving
        self.assertEqual(m[0x0470], 0xC3)                                       # drive 0 is the FujiNet
        self.assertEqual([m[0x0470 + 10 * d] for d in range(1, 8)], [0xC9] * 7)  # "disabled": a RET
        self.assertEqual(bytes(m[0x0473:0x047A]), bytes([0x44, 0xC1, 0x15, 0x27, 0x11, 0x45, 0x14]))

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


    def test_a_banner_is_on_screen_as_soon_as_it_starts(self):
        c = self.cpu
        for _ in range(300):                                             # long before the first answer could arrive
            c.step()
        self.assertIn(b"nioboot", bytes(c.mem[0x3E00:0x3E40]))

    def test_a_link_that_comes_up_late_still_boots_and_the_wait_is_announced(self):
        saved = self.nio.slots.copy()
        self.nio.slots.clear()
        c = self.cpu
        for _ in range(4_000_000):                                       # far longer than one answer timeout: three tries are over
            c.step()
        self.assertIn(b"Waiting for FujiNet", bytes(c.mem[0x3E80:0x3E80 + 40]))
        self.nio.slots.update(saved)                                     # the FujiNet is plugged in / started
        self.run_to_boot_sector()                                        # ... and the boot goes on by itself

    # ---- HIGH$ protection: LS-DOS 6.3.1 keeps HIGH$ at 040Eh (read 0FFFFh at the prompt, 0F790h after FUJIDRV lowered it by
    # the size of the driver -- found by diffing MAME's memory). The floppy-less driver sits at E000h, and LS-DOS sets HIGH$
    # itself after this loader has handed over, so the driver lowers it on every call instead.
    def call_rdsec_with_high(self, high):
        c = self.cpu
        c.mem[0x040E], c.mem[0x040F] = high & 255, high >> 8
        c.R[0], c.R[1] = 9, 0                                           # B = RDSEC
        c.set_rp(2, 3, 0x0001)                                          # cylinder 0, sector 1
        c.set_rp(4, 5, 0xC000)
        c.iy, c.sp, c.iff = 0x0470, 0x7000, False
        c.run_call(self.sym["drv_entry"], max_steps=60_000_000)
        return c.mem[0x040E] | c.mem[0x040F] << 8

    def test_driver_lowers_a_high_pointer_that_sits_above_it(self):
        for high in (0xFFFF, 0xF790, 0xE000):
            self.assertEqual(self.call_rdsec_with_high(high), 0xDFFF, hex(high))

    def test_driver_leaves_a_high_pointer_below_it_alone(self):
        for high in (0xDFFF, 0xB000, 0x7FFF):
            self.assertEqual(self.call_rdsec_with_high(high), high, hex(high))

    # ---- date and time. LS-DOS keeps them at 002Dh (sec, min, hour) and 0033h (year-1900, day, month). Its SYS0 initialisation
    # (disassembled from SYS0/SYS, confirmed in MAME) takes the date from 0033h and skips the date prompt when it is valid, and skips
    # the time prompt when the flag byte at 04C3h is nonzero. SYS0 then overwrites the time with its default, after the last disk
    # read, and sets HIGH$ (040Eh, 0000 until then). So: when the loader has read the last boot sector (before SYS0) it asks the
    # FujiNet's clock device (0x45, GetTimeFormat, simple format) and stores the date and the flag; the first driver call after HIGH$
    # has jumped back up (LS-DOS finished initialising) asks again and stores the time.
    def hook_sector_15(self):
        """Run the boot sector's patched FDC routine for cylinder 0 sector 15 (where the loader points drive 0 at the driver)."""
        self.run_to_boot_sector()
        self.nio.requests.clear()
        c, m = self.cpu, self.cpu.mem
        m[self.sym["v_clk"]] = 3
        m[0x0470:0x047A] = bytes([0xC3, 0x3D, 0x0E, 0x44, 0xC1, 0x15, 0x27, 0x11, 0x45, 0x14])
        m[0x33:0x36] = bytes([0xFF, 0xFF, 0xFF])                      # cold RAM
        m[0x2D:0x30] = bytes([1, 0, 0])
        m[0x04C3] = 0
        c.set_rp(2, 3, 15); c.set_rp(4, 5, 0x1100)
        c.run_call(m[0x4397] | m[0x4398] << 8, max_steps=60_000_000)

    def test_after_the_last_boot_sector_the_date_and_the_time_flag_come_from_the_fujinet_clock(self):
        self.nio.clock = (2027, 11, 23, 14, 37, 45)
        self.hook_sector_15()
        m = self.cpu.mem
        self.assertEqual(bytes(m[0x33:0x36]), bytes([127, 23, 11]))   # year - 1900, day, month
        self.assertNotEqual(m[0x04C3], 0)                             # "time already set": no time prompt

    def test_the_time_follows_once_ls_dos_has_finished_initialising(self):
        self.nio.clock = (2027, 11, 23, 14, 37, 45)
        self.hook_sector_15()
        m = self.cpu.mem
        self.nio.clock = (2027, 11, 23, 14, 38, 2)                    # a little later: the time is fetched afresh
        self.call_rdsec_with_high(0x0000)                             # mid-boot: HIGH$ still 0
        self.assertEqual(bytes(m[0x2D:0x30]), bytes([1, 0, 0]))
        self.call_rdsec_with_high(0xFFFF)                             # init done
        self.assertEqual(bytes(m[0x2D:0x30]), bytes([2, 38, 14]))
        m[0x2D] = 9
        self.call_rdsec_with_high(0xFFFF)
        self.assertEqual(m[0x2D], 9)                                  # once only

    def test_without_a_clock_device_nothing_is_touched_and_boot_carries_on(self):
        self.nio.clock = None
        self.hook_sector_15()
        m = self.cpu.mem
        self.call_rdsec_with_high(0xFFFF)
        self.assertEqual((bytes(m[0x33:0x36]), m[0x04C3], bytes(m[0x2D:0x30])), (bytes([0xFF] * 3), 0, bytes([1, 0, 0])))
        self.assertEqual(m[0xC000:0xC100], bytes(self.sector(1)))
        self.assertLessEqual(len([r for r in self.nio.requests if r.device == 0x45]), 3)


if __name__ == "__main__":
    unittest.main()
