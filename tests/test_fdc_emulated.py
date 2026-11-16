"""Runs the real build/fdc.hex in the Z80 interpreter against a fake WD1773."""
import os, re, shutil, subprocess, unittest

from tests.fakewd import FakeWD1773
from tests.z80emu import Z80, load_hex

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PB = 0x9F00
P_LATCH, P_TRACK, P_SECTOR, P_BUF, P_STATUS, P_ERR, P_ARMED, P_SPIN = (PB + i for i in (0, 1, 2, 3, 5, 6, 7, 8))
PB_NOVERIFY = PB + 11
P_ARMED_S = PB + 9
P_DEL = PB + 10
ENTRY = dict(init=0x8000, restore=0x8003, seek=0x8006, read_addr=0x8009,
             read_sector=0x800C, arm_write=0x800F, write_track=0x8012,
             write_sector=0x8015, disarm=0x8018)


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class FdcRoutineTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT, "build/fdc.hex"], check=True, stdout=subprocess.DEVNULL)
        self.cpu = Z80()
        load_hex(self.cpu, os.path.join(ROOT, "build", "fdc.hex"))
        self.fdc = FakeWD1773()
        self.other_out = []

        def io_in(port):
            return self.fdc.io_in(port) if port in FakeWD1773.PORTS else 0xFF

        def io_out(port, val):
            if port in FakeWD1773.PORTS:
                self.fdc.io_out(port, val)
            else:
                self.other_out.append((port, val))
        self.cpu.io_in, self.cpu.io_out = io_in, io_out

    def call(self, name, **params):
        m = self.cpu.mem
        m[P_LATCH] = params.get("latch", 0x81)
        m[P_TRACK] = params.get("track", 0)
        m[P_SECTOR] = params.get("sector", 0)
        buf = params.get("buf", 0xC000)
        m[P_BUF], m[P_BUF + 1] = buf & 255, buf >> 8
        m[P_SPIN] = params.get("spin", 0)
        m[PB_NOVERIFY] = params.get("noverify", 0)
        self.cpu.sp = 0x7000
        self.cpu.run_call(ENTRY[name])
        return m[P_STATUS], m[P_ERR]

    def test_entry_points_match_symbols(self):
        with open(os.path.join(ROOT, "build", "fdc.sym")) as f:
            syms = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", f.read(), re.M)}
        for name, addr in ENTRY.items():
            self.assertEqual(self.cpu.mem[addr], 0xC3, name)                      # JP
            target = self.cpu.mem[addr + 1] | self.cpu.mem[addr + 2] << 8
            self.assertEqual(target, syms[name], name)

    def test_init_disables_nmi_and_sets_fast_clock(self):
        self.call("init")
        self.assertIn((0xE4, 0x00), self.other_out)
        self.assertIn((0xEC, 0x40), self.other_out)

    def test_restore_reports_track0_status(self):
        self.fdc.track = 17
        status, err = self.call("restore")
        self.assertEqual((status & 0x04, err), (0x04, 0))
        self.assertEqual(self.fdc.track, 0)
        self.assertEqual(self.fdc.latch, 0x81)                                  # latch written first

    def test_seek_sets_destination_track(self):
        status, err = self.call("seek", track=17)
        self.assertEqual((self.fdc.track, err), (17, 0))

    def test_seek_uses_verify_so_the_head_settles(self):
        # 13h has no settle delay; with V set (17h) the controller waits 15 ms and checks the ID.
        # Writing right after a bare step is a suspect for sporadic unreadable sectors.
        self.call("seek", track=17)
        self.assertEqual(self.fdc.commands, [0x17])

    def test_seek_without_verify_is_available_for_probing_past_the_last_track(self):
        self.call("seek", track=17, noverify=1)
        self.assertEqual(self.fdc.commands, [0x13])

    def test_read_addr_returns_six_bytes(self):
        self.fdc.phys = 5
        status, err = self.call("read_addr", buf=0xC000)
        self.assertEqual(bytes(self.cpu.mem[0xC000:0xC006]), bytes([5, 0, 1, 1, 0xAA, 0xBB]))
        self.assertEqual((status, err), (0, 0))

    def test_read_sector_returns_data_and_uses_sector_and_side(self):
        data = bytes(range(256))
        self.fdc.track = 3
        self.fdc.disk[(3, 1, 9)] = data
        status, err = self.call("read_sector", latch=0x91, sector=9, buf=0xC100)
        self.assertEqual(bytes(self.cpu.mem[0xC100:0xC200]), data)
        self.assertEqual((status, err), (0, 0))

    def test_read_sector_not_found_ends_with_rnf_status(self):
        status, err = self.call("read_sector", sector=4)
        self.assertEqual((status & 0x10, err), (0x10, 0))

    def test_write_track_refused_when_not_armed(self):
        self.cpu.mem[0xA000:0xA000 + 6400] = bytes(range(256)) * 25
        status, err = self.call("write_track", buf=0xA000)
        self.assertEqual(err, 1)
        self.assertEqual([e for e in self.fdc.log if e[1] in (0xF0, 0xF1, 0xF2, 0xF3, 0xF4)], [])

    def test_write_track_armed_streams_bytes_then_disarms(self):
        pattern = bytes((i * 3) & 0xFF for i in range(6400))
        self.cpu.mem[0xA000:0xA000 + 6400] = pattern
        self.call("arm_write")
        status, err = self.call("write_track", buf=0xA000, latch=0xA1)
        self.assertEqual(err, 0)
        self.assertEqual(bytes(self.fdc.wbuf[:6250]), pattern[:6250])
        self.assertEqual(self.fdc.latch & 0xBF, 0xA1)                              # WSGEN (0x40) may be set
        self.assertEqual(0xF4 in self.fdc.commands, True)
        self.assertEqual(self.cpu.mem[P_ARMED], 0)
        before = len(self.fdc.log)
        status, err = self.call("write_track", buf=0xA000)                       # second call: refused
        self.assertEqual(err, 1)
        self.assertEqual(len(self.fdc.log), before)

    def test_timeout_aborts_with_force_interrupt_instead_of_hanging(self):
        self.fdc.stuck = True
        status, err = self.call("read_sector", sector=1)
        self.assertEqual(err, 2)
        self.assertIn(0xD0, self.fdc.commands)

    def test_type_i_timeout_aborts_too(self):
        self.fdc.stuck = True
        status, err = self.call("restore")
        self.assertEqual(err, 2)
        self.assertIn(0xD0, self.fdc.commands)

    def test_spin_up_delay_only_when_requested(self):
        self.call("restore", spin=0)
        quick = self.cpu.steps
        self.cpu.steps = 0
        self.fdc = FakeWD1773()
        self.call("restore", spin=1)
        self.assertGreater(self.cpu.steps, quick + 50000)

    def test_write_sector_refused_when_not_armed(self):
        self.cpu.mem[0xA000:0xA100] = bytes(256)
        status, err = self.call("write_sector", sector=3, buf=0xA000)
        self.assertEqual(err, 1)
        self.assertEqual([e for e in self.fdc.log if e[0] == "out"], [])

    def test_write_sector_armed_writes_all_bytes_and_stays_armed_until_disarm(self):
        data = bytes([0xF5, 0xF6, 0xF7] + list(range(253)))
        self.cpu.mem[0xA000:0xA100] = data
        self.fdc.phys = self.fdc.track = 4
        self.call("arm_write")
        status, err = self.call("write_sector", sector=9, buf=0xA000, latch=0x81)
        self.assertEqual(err, 0)
        self.assertIn(0xA4, self.fdc.commands)
        self.assertEqual(self.fdc.disk[(4, 0, 9)], data)
        status, err = self.call("write_sector", sector=10, buf=0xA000)           # still armed
        self.assertEqual(err, 0)
        self.call("disarm")
        self.assertEqual(self.cpu.mem[P_ARMED_S], 0)
        self.assertEqual(self.cpu.mem[P_ARMED], 0)
        status, err = self.call("write_sector", sector=11, buf=0xA000)
        self.assertEqual(err, 1)

    def test_every_transfer_routine_runs_with_interrupts_disabled(self):
        # the 60 Hz clock interrupt would steal ~100 us in the middle of a 32 us/byte transfer
        self.fdc.disk[(0, 0, 1)] = bytes(256)
        self.call("arm_write")
        for name in ("restore", "seek", "read_addr", "read_sector", "write_sector", "write_track"):
            self.cpu.iff = True
            self.cpu.mem[0xA000:0xA000 + 6400] = bytes(6400)
            self.call(name, sector=1, buf=0xA000)
            self.assertFalse(self.cpu.iff, name)
            self.call("arm_write")

    def test_write_sector_uses_deleted_mark_command_only_when_asked(self):
        self.cpu.mem[0xA000:0xA100] = bytes(256)
        self.fdc.phys = self.fdc.track = 4
        self.call("arm_write")
        self.cpu.mem[P_DEL] = 0
        self.call("write_sector", sector=1, buf=0xA000)
        self.cpu.mem[P_DEL] = 1
        self.call("write_sector", sector=2, buf=0xA000)
        self.cpu.mem[P_DEL] = 0xFF                      # only bit 0 may pick the command; never 0xA4|garbage
        self.call("write_sector", sector=3, buf=0xA000)
        self.assertEqual([c for c in self.fdc.commands if c & 0xFE == 0xA4], [0xA4, 0xA5, 0xA5])
        self.assertEqual([self.fdc.dams[(4, 0, n)] for n in (1, 2, 3)], [0xFB, 0xF8, 0xF8])


if __name__ == "__main__":
    unittest.main()
