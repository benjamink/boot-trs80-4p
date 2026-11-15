import glob, os, unittest

from trs80 import dmk, lsdosfs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = sorted(glob.glob(os.path.join(ROOT, "images", "lsdos631l-upstream", "*.DSK")))


def load(path):
    with open(path, "rb") as f:
        return dmk.parse_dmk(f.read())


@unittest.skipUnless(IMAGES, "LS-DOS images not downloaded (images/lsdos631l-upstream)")
class RealImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.imgs = {os.path.basename(p): load(p) for p in IMAGES}
        cls.ld4 = cls.imgs["LD4-631.DSK"]

    def test_lists_known_system_files(self):
        files = {f"{e.name}/{e.ext}": e for e in lsdosfs.list_files(self.ld4)}
        print("\nLD4-631.DSK:", ", ".join(sorted(files)))
        for name in ("BOOT/SYS", "DIR/SYS", "SYS6/SYS", "SYS7/SYS", "LOG/CMD"):
            self.assertIn(name, files)
        # sizes worked out by hand from the raw directory bytes (ERN records, EOF offset)
        self.assertEqual(files["BOOT/SYS"].size, 16 * 256)
        self.assertEqual(files["DIR/SYS"].size, 18 * 256)
        self.assertEqual(files["SYS6/SYS"].size, 0x35 * 256 + 0xB4)     # ERN 0x36, EOF offset 0xB4
        self.assertEqual(files["LOG/CMD"].size, 256 + 0x6F)
        self.assertTrue(files["BOOT/SYS"].system)
        self.assertFalse(files["LOG/CMD"].system)

    def test_read_file_matches_directory_size(self):
        for fname, img in self.imgs.items():
            for e in lsdosfs.list_files(img):
                data = lsdosfs.read_file(img, f"{e.name}/{e.ext}")
                self.assertEqual(len(data), e.size, f"{fname} {e.name}/{e.ext}")

    def test_boot_sys_starts_with_the_boot_sector(self):
        boot = next(s.data for s in self.ld4.get(0, 0).sectors if s.num == 0)
        self.assertEqual(lsdosfs.read_file(self.ld4, "BOOT/SYS")[:256], boot)

    def test_read_file_name_is_case_insensitive_and_unknown_raises(self):
        self.assertEqual(lsdosfs.read_file(self.ld4, "log/cmd"), lsdosfs.read_file(self.ld4, "LOG/CMD"))
        with self.assertRaises(FileNotFoundError):
            lsdosfs.read_file(self.ld4, "NOPE/XYZ")

    def test_is_bootable_distinguishes_images(self):
        for fname, img in self.imgs.items():
            names = {f"{e.name}/{e.ext}" for e in lsdosfs.list_files(img)}
            print(f"\n{fname}: bootable={lsdosfs.is_bootable(img)} SYS0/SYS={'SYS0/SYS' in names} files={len(names)}")
            self.assertEqual(lsdosfs.is_bootable(img), "SYS0/SYS" in names)
        broken = load(IMAGES[0])
        broken.set_sector_data(0, 0, 0, bytes(256))                     # wipe the boot sector
        self.assertFalse(lsdosfs.is_bootable(broken))


if __name__ == "__main__":
    unittest.main()
