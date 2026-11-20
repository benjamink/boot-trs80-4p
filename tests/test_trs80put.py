# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
import io, os, shutil, subprocess, tempfile, unittest

import trs80put
from tests.emutransport import EmuTransport
from tests.fakedos import DosExit, FakeDos
from trs80.monitor import Monitor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = lambda n: os.path.join(ROOT, "build", n)


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class PutCliTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        self.t = EmuTransport(B("mon.hex"), B("mon.sym"))
        self.dos = FakeDos(self.t.cpu)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = io.StringIO()

    def local(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def run_cli(self, argv):
        return trs80put.main(argv, open_monitor=lambda port: Monitor(self.t, timeout=0.01, retries=4),
                             out=lambda *a: print(*a, file=self.out), hex_path=B("dosio.hex"))

    def test_local_file_name_becomes_the_ls_dos_name(self):
        rc = self.run_cli([self.local("game.cmd", b"abc" * 100)])
        self.assertEqual(rc, 0)
        self.assertEqual(self.dos.files, {"GAME/CMD": b"abc" * 100})

    def test_several_files_and_explicit_name(self):
        a, b = self.local("one.bas", b"1"), self.local("two.txt", b"2")
        self.assertEqual(self.run_cli([a, b]), 0)
        self.assertEqual(sorted(self.dos.files), ["ONE/BAS", "TWO/TXT"])
        self.assertEqual(self.run_cli([a, "--as", "RENAMED/BAS"]), 0)
        self.assertIn("RENAMED/BAS", self.dos.files)

    def test_text_mode_converts_line_endings_to_cr(self):
        p = self.local("notes.txt", b"one\r\ntwo\nthree\rfour\r\n\r\nend")
        self.assertEqual(self.run_cli([p, "--text"]), 0)
        self.assertEqual(self.dos.files["NOTES/TXT"], b"one\rtwo\rthree\rfour\r\rend")
        self.assertIn("text", self.out.getvalue())

    def test_without_text_mode_bytes_are_untouched(self):
        self.assertEqual(self.run_cli([self.local("a.bin", b"x\r\ny\n")]), 0)
        self.assertEqual(self.dos.files["A/BIN"], b"x\r\ny\n")

    def test_as_with_several_files_is_an_error(self):
        a, b = self.local("one.bas", b"1"), self.local("two.txt", b"2")
        with self.assertRaises(SystemExit):
            self.run_cli([a, b, "--as", "X/Y"])

    def test_bad_name_reports_and_returns_error_without_touching_the_disk(self):
        rc = self.run_cli([self.local("waytoolongname.bin", b"1")])
        self.assertEqual(rc, 1)
        self.assertEqual(self.dos.calls, [])
        self.assertIn("invalid LS-DOS file name", self.out.getvalue())

    def test_replacing_a_file_is_reported(self):
        p = self.local("a.txt", b"x")
        self.run_cli([p])
        self.run_cli([p])
        self.assertIn("replaced existing A/TXT", self.out.getvalue())

    def test_dos_error_is_reported_and_stops(self):
        self.dos.fail[58] = 0x1D
        rc = self.run_cli([self.local("a.txt", b"x"), self.local("b.txt", b"y")])
        self.assertEqual(rc, 1)
        self.assertIn("error 29", self.out.getvalue())
        self.assertEqual(self.dos.files, {})

    def test_exit_flag_returns_to_ls_dos(self):
        with self.assertRaises(DosExit):
            self.run_cli([self.local("a.txt", b"x"), "--exit"])


if __name__ == "__main__":
    unittest.main()
