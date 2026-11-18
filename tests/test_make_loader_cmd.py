import os, subprocess, sys, tempfile, unittest

from trs80 import lmf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "make_loader_cmd.py")
HEX = os.path.join(ROOT, "examples", "SCRDUMP.HEX")


def run(*args):
    return subprocess.run([sys.executable, "-I", TOOL, *args], capture_output=True, text=True)


class MakeLoaderCmdTests(unittest.TestCase):
    def test_cmd_matches_what_trs80boot_sends(self):
        segs, _ = lmf.parse_hex(HEX)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.cmd")
            r = run(HEX, out, "--entry", "0x5000")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), lmf.build_lmf(segs, 0x5000, 16))

    def test_entry_defaults_to_5000(self):
        segs, _ = lmf.parse_hex(HEX)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.cmd")
            self.assertEqual(run(HEX, out).returncode, 0)
            with open(out, "rb") as f:
                blob = f.read()
            self.assertEqual(blob[-4:], bytes([0x02, 0x02, 0x00, 0x50]))

    def test_entry_override(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.cmd")
            self.assertEqual(run(HEX, out, "--entry", "0x6000").returncode, 0)
            with open(out, "rb") as f:
                self.assertEqual(f.read()[-4:], bytes([0x02, 0x02, 0x00, 0x60]))


if __name__ == "__main__":
    unittest.main()
