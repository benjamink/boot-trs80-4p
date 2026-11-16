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

    def test_flat_image_is_cylinder_major_256_byte_sectors(self):
        flat = lsdosfs.flat_image(self.ld4)
        self.assertEqual(len(flat), 40 * 18 * 256)
        boot = lsdosfs._Geometry.sector(self.ld4, 0, 0)
        self.assertEqual(flat[:256], boot)
        gat = lsdosfs._Geometry.sector(self.ld4, 20, 0)
        self.assertEqual(flat[(20 * 18) * 256:(20 * 18 + 1) * 256], gat)
        s5 = lsdosfs._Geometry.sector(self.ld4, 7, 5)
        self.assertEqual(flat[(7 * 18 + 5) * 256:(7 * 18 + 6) * 256], s5)

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


@unittest.skipUnless(IMAGES, "LS-DOS images not downloaded (images/lsdos631l-upstream)")
class InjectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load(os.path.join(ROOT, "images", "lsdos631l-upstream", "L631NEW.DSK"))

    def roomy(self, *drop):
        img = self.base
        for n in drop or ("BASIC/CMD", "BASIC/OV1", "BASIC/OV2"):
            img = lsdosfs.delete_file(img, n)
        return img

    def test_added_file_reads_back_identical(self):
        data = bytes((i * 7) % 256 for i in range(5000))          # 5000 bytes: partial last record
        out = lsdosfs.add_file(self.roomy(), "TRSDW/CMD", data)
        self.assertEqual(lsdosfs.read_file(out, "TRSDW/CMD"), data)
        self.assertIn(("TRSDW", "CMD", 5000), [(f.name, f.ext, f.size) for f in lsdosfs.list_files(out)])

    def test_exact_record_multiple_and_tiny_files(self):
        out = lsdosfs.add_file(self.roomy(), "A/TXT", b"x")
        out = lsdosfs.add_file(out, "B/TXT", bytes(512))
        self.assertEqual(lsdosfs.read_file(out, "A/TXT"), b"x")
        self.assertEqual(lsdosfs.read_file(out, "B/TXT"), bytes(512))

    def test_other_files_unchanged_byte_for_byte(self):
        roomy = self.roomy()
        out = lsdosfs.add_file(roomy, "TRSDW/CMD", b"hello" * 400)
        for f in lsdosfs.list_files(roomy):
            n = f"{f.name}/{f.ext}"
            if n == "DIR/SYS":                                   # the directory itself changes by design
                continue
            self.assertEqual(lsdosfs.read_file(out, n), lsdosfs.read_file(roomy, n), n)

    def test_original_image_object_is_not_modified(self):
        before = self.base.to_bytes()
        lsdosfs.delete_file(self.base, "BASIC/CMD")
        self.assertEqual(self.base.to_bytes(), before)

    def test_delete_removes_file_and_frees_granules(self):
        out = lsdosfs.delete_file(self.base, "BASIC/CMD")
        self.assertNotIn("BASIC/CMD", [f"{f.name}/{f.ext}" for f in lsdosfs.list_files(out)])
        self.assertEqual(lsdosfs.free_granules(out), lsdosfs.free_granules(self.base) + 23076 // 1536 + 1)
        with self.assertRaises(FileNotFoundError):
            lsdosfs.delete_file(out, "BASIC/CMD")

    def test_gat_allocated_granule_count_matches_file_size(self):
        roomy = self.roomy()
        for size in (1, 1536, 1537, 10000):
            out = lsdosfs.add_file(roomy, "T/BIN", bytes(size))
            used = lsdosfs.free_granules(roomy) - lsdosfs.free_granules(out)
            self.assertEqual(used, -(-size // 1536), size)

    def test_duplicate_name_rejected(self):
        with self.assertRaises(lsdosfs.FileExistsError_):
            lsdosfs.add_file(self.base, "SYS0/SYS", b"x")

    def test_disk_full_raises(self):
        with self.assertRaises(lsdosfs.DiskFullError):
            lsdosfs.add_file(self.base, "BIG/BIN", bytes(1536 * 5))

    def test_invalid_names_rejected(self):
        for bad in ("TOOLONGNAME/CMD", "A/LONG", "has space/CMD", "", "/CMD", "A.B/CMD"):
            with self.assertRaises(ValueError, msg=bad):
                lsdosfs.add_file(self.roomy(), bad, b"x")

    def test_image_still_parses_with_valid_crcs(self):
        out = lsdosfs.add_file(self.roomy(), "TRSDW/CMD", bytes(range(256)) * 20)
        again = dmk.parse_dmk(out.to_bytes())
        for cyl in range(again.tracks):
            for s in again.get(cyl, 0).sectors:
                self.assertTrue(s.id_crc_ok and s.data_crc_ok, (cyl, s.num))
        self.assertEqual(lsdosfs.read_file(again, "TRSDW/CMD"), bytes(range(256)) * 20)

    def test_still_bootable_and_directory_marks_preserved(self):
        out = lsdosfs.add_file(self.roomy(), "TRSDW/CMD", b"abc")
        self.assertTrue(lsdosfs.is_bootable(out))
        self.assertTrue(all(s.dam == 0xF8 for s in out.get(20, 0).sectors))

    def test_hit_matches_hash_of_every_existing_entry_and_the_new_one(self):
        out = lsdosfs.add_file(self.roomy(), "TRSDW/CMD", b"abc")
        self.assertEqual(lsdosfs.check_hit(self.base), [])        # real image is the reference
        self.assertEqual(lsdosfs.check_hit(out), [])
