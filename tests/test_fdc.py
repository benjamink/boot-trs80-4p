"""Host Fdc driver against the real monitor + real fdc.hex in the Z80 interpreter and a fake WD1773."""
import os, shutil, subprocess, unittest

from tests.emutransport import EmuTransport
from tests.fakewd import FakeWD1773
from trs80.fdc import Fdc, FdcError
from trs80.monitor import Monitor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P_ARMED = 0x9F07


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class FdcDriverTests(unittest.TestCase):
    def setUp(self):
        for t in ("build/mon.hex", "build/fdc.hex"):
            subprocess.run(["make", "-B", "-C", ROOT, t], check=True, stdout=subprocess.DEVNULL)
        self.t = EmuTransport(os.path.join(ROOT, "build", "mon.hex"), os.path.join(ROOT, "build", "mon.sym"))
        self.wd = FakeWD1773()
        self.t.attach(FakeWD1773.PORTS, self.wd.io_in, self.wd.io_out)
        self.fdc = Fdc(Monitor(self.t, timeout=0.01, retries=4), os.path.join(ROOT, "build", "fdc.hex"))
        self.fdc.upload()

    def touched_fdc(self):
        return [e for e in self.wd.log if e[0] == "out"]

    def test_probe_reports_geometry(self):
        info = self.fdc.probe(0)
        self.assertTrue(info.present)
        self.assertEqual((info.drive, info.max_track, info.sides), (0, 39, 1))
        self.wd.sides = 2
        self.wd.max_cyl = 79
        info = self.fdc.probe(1)
        self.assertEqual((info.drive, info.max_track, info.sides), (1, 79, 2))
        self.assertIn(0x82, [v for k, p, v in self.wd.log if k == "out" and p == 0xF4])   # drive 1 selected

    def test_probe_no_disk_reports_not_present_and_never_writes(self):
        self.wd.ready = False
        info = self.fdc.probe(0)
        self.assertFalse(info.present)
        self.assertNotIn(0xF4, self.wd.commands)
        self.assertEqual(len(self.wd.wbuf), 0)

    def test_probe_never_calls_arm_write(self):
        self.fdc.probe(0)
        self.assertEqual(self.t.cpu.mem[P_ARMED], 0)

    def test_write_track_refused_when_not_armed(self):
        before = len(self.touched_fdc())
        self.assertEqual(self.fdc.write_track(0, 0, 0, bytes(6400)), 1)
        self.assertEqual(len(self.touched_fdc()), before)
        self.assertNotIn(0xF4, self.wd.commands)

    def test_write_track_after_arm_streams_stream(self):
        stream = bytes((i * 5) & 0xFF for i in range(6400))
        self.fdc.arm_write()
        self.assertEqual(self.fdc.write_track(0, 3, 0, stream), 0)
        self.assertEqual(bytes(self.wd.wbuf[:6250]), stream[:6250])
        self.assertEqual(self.wd.track, 3)
        self.assertEqual(self.fdc.write_track(0, 3, 0, stream), 1)         # one-shot arm

    def test_read_sector_returns_data(self):
        self.wd.disk[(2, 0, 7)] = bytes(range(256))
        self.assertEqual(self.fdc.read_sector(0, 2, 0, 7, 256, "MFM"), bytes(range(256)))

    def test_read_sector_error_raises_fdcerror(self):
        with self.assertRaises(FdcError):
            self.fdc.read_sector(0, 2, 0, 7, 256, "MFM")                   # RNF

    def test_write_sector_refused_unarmed_then_writes_special_bytes_when_armed(self):
        data = bytes([0xF5, 0xF6, 0xF7] + list(range(253)))
        self.assertEqual(self.fdc.write_sector(0, 2, 0, 5, data), 1)
        self.assertEqual(self.wd.disk, {})
        self.fdc.arm_write()
        self.assertEqual(self.fdc.write_sector(0, 2, 0, 5, data), 0)
        self.assertEqual(self.wd.disk[(2, 0, 5)], data)
        self.fdc.disarm()
        self.assertEqual(self.fdc.write_sector(0, 2, 0, 6, data), 1)

    def test_probe_records_probed_drive_only_when_present(self):
        self.wd.ready = False
        self.fdc.probe(0)
        self.assertNotIn(0, self.fdc.probed)
        self.wd.ready = True
        self.fdc.probe(0)
        self.assertIn(0, self.fdc.probed)

    def test_write_sector_deleted_mark(self):
        self.fdc.arm_write()
        self.assertEqual(self.fdc.write_sector(0, 2, 0, 5, bytes(256), dam=0xF8), 0)
        self.assertEqual(self.fdc.write_sector(0, 2, 0, 6, bytes(256)), 0)
        self.assertEqual((self.wd.dams[(2, 0, 5)], self.wd.dams[(2, 0, 6)]), (0xF8, 0xFB))
        with self.assertRaises(ValueError):
            self.fdc.write_sector(0, 2, 0, 7, bytes(256), dam=0xF9)


if __name__ == "__main__":
    unittest.main()
