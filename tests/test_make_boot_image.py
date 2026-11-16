import os, shutil, subprocess, tempfile, unittest

from tools.make_boot_image import NAME, make_boot_image, serial_cmd
from trs80 import lsdosfs
from trs80.dmk import parse_dmk

def rd(path):
    with open(path, "rb") as f:
        return f.read()


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "images", "lsdos631l-upstream", "L631NEW.DSK")


@unittest.skipUnless(shutil.which("sjasmplus") and os.path.exists(BASE), "needs sjasmplus and the LS-DOS images")
class BootImageTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = os.path.join(self.tmp, "boot.dsk")

    def test_combined_image_lists_serial_cmd_and_is_bootable(self):
        n = make_boot_image(BASE, self.out)
        img = parse_dmk(rd(self.out))
        self.assertIn(("SERIAL", "CMD", n), [(f.name, f.ext, f.size) for f in lsdosfs.list_files(img)])
        self.assertTrue(lsdosfs.is_bootable(img))
        self.assertEqual(lsdosfs.check_hit(img), [])

    def test_file_is_the_load_module_with_entry_at_front_end(self):
        make_boot_image(BASE, self.out)
        img = parse_dmk(rd(self.out))
        blob = lsdosfs.read_file(img, NAME)
        self.assertEqual(blob, serial_cmd())
        self.assertEqual(blob[-4:], bytes([0x02, 0x02, 0x00, 0x5F]))       # transfer address 5F00h

    def test_base_image_is_left_untouched(self):
        before = rd(BASE)
        make_boot_image(BASE, self.out)
        self.assertEqual(rd(BASE), before)

    def test_every_other_file_survives_byte_for_byte(self):
        make_boot_image(BASE, self.out)
        old, new = parse_dmk(rd(BASE)), parse_dmk(rd(self.out))
        for f in lsdosfs.list_files(old):
            n = f"{f.name}/{f.ext}"
            if n != "DIR/SYS":
                self.assertEqual(lsdosfs.read_file(new, n), lsdosfs.read_file(old, n), n)


if __name__ == "__main__":
    unittest.main()
