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


if __name__ == "__main__":
    unittest.main()
