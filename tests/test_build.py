import os, shutil, subprocess, unittest

from trs80 import lmf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class BuildTests(unittest.TestCase):
    def build(self, name):
        subprocess.run(["make", "-B", "-C", ROOT, f"build/{name}.hex"], check=True,
                       stdout=subprocess.DEVNULL)
        return lmf.parse_hex(os.path.join(ROOT, "build", f"{name}.hex"))

    def test_monitor_is_one_segment_at_6000_within_0x400(self):
        segs, _ = self.build("mon")
        self.assertEqual(list(segs), [0x6000])
        self.assertLessEqual(len(segs[0x6000]), 0x400)

    def test_memtest_is_one_segment_at_6000_below_its_variables(self):
        segs, _ = self.build("memtest")
        self.assertEqual(list(segs), [0x6000])                       # the ROM loader starts at the lowest address
        self.assertLess(0x6000 + len(segs[0x6000]), 0x6E00)          # code must stay clear of the variables at 6E00h
        kernel = open(os.path.join(ROOT, "build", "memtest_k.bin"), "rb").read()
        self.assertTrue(segs[0x6000].endswith(kernel))               # the relocated kernel travels at the end of the image


if __name__ == "__main__":
    unittest.main()
