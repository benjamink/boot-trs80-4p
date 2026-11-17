import unittest

from trs80 import jv3


def make_jv3(entries, size=256):
    """entries: [(track, sector, flags, fill)] in file order -> a JV3 file (2901 headers, write-protect byte, data)."""
    head = bytearray(b"\xff" * (2901 * 3))
    data = bytearray()
    for i, (t, s, f, fill) in enumerate(entries):
        head[i * 3:i * 3 + 3] = bytes([t, s, f])
        data += bytes([fill]) * size
    return bytes(head) + b"\xff" + bytes(data)


class Jv3Tests(unittest.TestCase):
    def test_sectors_land_at_cylinder_times_sectors_per_cylinder_plus_sector(self):
        # stored out of order; 2 tracks x 3 sectors
        entries = [(1, 2, 0x80, 0x12), (0, 0, 0x80, 0x01), (1, 0, 0x80, 0x10), (0, 2, 0x80, 0x03), (0, 1, 0x80, 0x02), (1, 1, 0x80, 0x11)]
        flat = jv3.flat_image(make_jv3(entries))
        self.assertEqual(len(flat), 6 * 256)
        for lba, fill in enumerate((0x01, 0x02, 0x03, 0x10, 0x11, 0x12)):
            self.assertEqual(flat[lba * 256:(lba + 1) * 256], bytes([fill]) * 256, lba)

    def test_the_directory_track_marks_and_crc_flags_do_not_change_the_data(self):
        flat = jv3.flat_image(make_jv3([(0, 0, 0xA0, 7), (0, 1, 0x88, 8)]))
        self.assertEqual((flat[0], flat[256]), (7, 8))

    def test_unused_header_slots_are_ignored(self):
        self.assertEqual(len(jv3.flat_image(make_jv3([(0, 0, 0x80, 1)]))), 256)

    def test_other_sector_sizes_and_second_sides_are_refused(self):
        with self.assertRaises(ValueError):
            jv3.flat_image(make_jv3([(0, 0, 0x81, 1)], size=128))        # size code 1
        with self.assertRaises(ValueError):
            jv3.flat_image(make_jv3([(0, 0, 0x90, 1)]))                  # side 1

    def test_a_file_that_is_not_jv3_is_refused(self):
        with self.assertRaises(ValueError):
            jv3.flat_image(b"\x00\xfe\x14" * 100)
        self.assertFalse(jv3.looks_like_jv3(b"\x00\xfe\x14" + bytes(256)))
        self.assertTrue(jv3.looks_like_jv3(make_jv3([(0, 0, 0x80, 1), (0, 1, 0x80, 1), (0, 2, 0x80, 1)])[:256]))


if __name__ == "__main__":
    unittest.main()
