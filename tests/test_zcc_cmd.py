import os, tempfile, unittest

from tools.zcc_cmd import bin_to_lmf
from trs80.lmf import parse_lmf


class ZccCmdTests(unittest.TestCase):
    def test_bin_to_lmf_roundtrip(self):
        blob = bytes(range(256)) * 2 + bytes(88)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            with open(p, "wb") as f:
                f.write(blob)
            segs, entry = parse_lmf(bin_to_lmf(p))
        self.assertEqual(segs, {0x3000: blob})
        self.assertEqual(entry, 0x3000)
