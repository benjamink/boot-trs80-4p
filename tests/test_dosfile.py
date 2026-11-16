"""trs80.dosfile against the real build/dosio.hex + build/mon.hex in the Z80 interpreter, with FakeDos
standing in for LS-DOS."""
import os, shutil, subprocess, unittest

from tests.emutransport import EmuTransport
from tests.fakedos import DosExit, FakeDos
from trs80.dosfile import DosError, DosLink
from trs80.lmf import parse_hex
from trs80.monitor import Monitor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = lambda n: os.path.join(ROOT, "build", n)


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class DosLinkTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        self.t = EmuTransport(B("mon.hex"), B("mon.sym"))
        self.dos = FakeDos(self.t.cpu)
        self.link = DosLink(Monitor(self.t, timeout=0.01, retries=4), hex_path=B("dosio.hex"))
        self.link.upload()

    def test_put_writes_file_with_exact_size_and_content(self):
        data = bytes((i * 11) % 256 for i in range(700))                 # 2 full records + 188 bytes
        self.link.put("TEST/BIN", data)
        self.assertEqual(self.dos.files["TEST/BIN"], data)

    def test_put_reports_whether_it_replaced_a_file(self):
        self.assertFalse(self.link.put("TEST/BIN", b"one"))
        self.assertTrue(self.link.put("TEST/BIN", b"two"))

    def test_put_sizes_on_record_boundaries(self):
        for n in (0, 1, 255, 256, 257, 512):
            data = bytes([n % 251 + 1]) * n
            self.link.put(f"F{n}/DAT", data)
            self.assertEqual(self.dos.files[f"F{n}/DAT"], data, n)

    def test_put_replaces_a_longer_existing_file(self):
        self.link.put("TEST/BIN", bytes(range(256)) * 4)
        self.link.put("TEST/BIN", b"short")
        self.assertEqual(self.dos.files["TEST/BIN"], b"short")
        self.assertIn(57, self.dos.calls)                                 # old copy was @REMOVed, freeing its space

    def test_filespec_names_the_drive_and_name_is_upper_cased(self):
        self.link.put("test/bin", b"x", drive=1)
        self.assertEqual(list(self.dos.files), ["TEST/BIN"])
        self.assertEqual(self.dos.specs, ["TEST/BIN:1", "TEST/BIN:1"])     # @OPEN for the delete, then @INIT

    def test_dos_error_is_raised_with_its_number_and_file_is_closed(self):
        self.dos.fail[75] = 0x1B                                          # e.g. disk full on @WRITE
        with self.assertRaises(DosError) as cm:
            self.link.put("TEST/BIN", b"x" * 300)
        self.assertEqual(cm.exception.code, 0x1B)
        self.assertEqual(self.dos.pending, {})

    def test_open_error_stops_before_writing(self):
        self.dos.fail[58] = 0x18
        with self.assertRaises(DosError):
            self.link.put("TEST/BIN", b"x")
        self.assertNotIn(75, self.dos.calls)

    def test_invalid_name_is_rejected_without_calling_dos(self):
        for bad in ("TOOLONGNAME/CMD", "A B/CMD", ""):
            with self.assertRaises(ValueError):
                self.link.put(bad, b"x")
        self.assertEqual(self.dos.calls, [])

    def test_interrupts_are_off_again_after_every_call(self):
        self.link.put("TEST/BIN", b"x" * 300)
        self.assertTrue(all(self.dos.interrupts_on_at_svc))               # on while LS-DOS runs
        self.assertFalse(self.t.cpu.iff)                                  # off while the monitor polls

    def test_exit_calls_exit_svc(self):
        with self.assertRaises(DosExit):
            self.link.exit()


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class SerialCmdTests(unittest.TestCase):
    def test_front_end_programs_the_uart_then_the_monitor_answers(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        t = EmuTransport(B("mon.hex"), B("mon.sym"))
        segs, _ = parse_hex(B("serialcmd.hex"))
        for a, d in segs.items():
            t.cpu.mem[a:a + len(d)] = d
        dos = FakeDos(t.cpu)
        t.cpu.pc = 0x5F00
        m = Monitor(t, timeout=0.01, retries=4)
        self.assertEqual(m.ping(b"hi"), b"hi")                            # init ran, then the monitor
        # exactly what the 4P ROM does (EA control, E9 baud, E8 with a NONZERO value): MAME's UART is left at 5 data
        # bits if E8 is written with 0, and this is the sequence known to talk to the PC on the real machine
        self.assertEqual([p for p in t.port_writes if p[0] in (0xE8, 0xE9, 0xEA)],
                         [(0xEA, 0x64), (0xE9, 0xFF), (0xE8, 0xFF)])
        self.assertIn("19200", dos.messages[0])
        self.assertFalse(t.cpu.iff)


if __name__ == "__main__":
    unittest.main()
