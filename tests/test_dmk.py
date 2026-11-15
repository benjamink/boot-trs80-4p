import glob, os, unittest

from tests.dmkbuild import make_dmk, make_track, sector
from trs80 import dmk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mfm18(cyl, side):
    return make_track([sector(cyl, side, n) for n in range(1, 19)], mfm=True)


class DmkTests(unittest.TestCase):
    def test_crc16_ccitt_known_vector(self):
        self.assertEqual(dmk.crc16(b"123456789"), 0x29B1)

    def test_parse_single_track_mfm(self):
        img = dmk.parse_dmk(make_dmk([mfm18(0, 0)], tracks=1, sides=1))
        self.assertEqual((img.tracks, img.sides, img.track_len), (1, 1, 6400))
        t = img.get(0, 0)
        self.assertTrue(t.present)
        self.assertEqual([s.num for s in t.sectors], list(range(1, 19)))
        s = t.sectors[4]
        self.assertEqual((s.cyl, s.side, s.size, s.dam, s.density), (0, 0, 256, 0xFB, "MFM"))
        self.assertEqual(s.data, bytes((5 + i) & 0xFF for i in range(256)))
        self.assertTrue(s.id_crc_ok and s.data_crc_ok)

    def test_fm_track_density(self):
        tr = make_track([sector(0, 0, n, size_code=0) for n in range(1, 11)], mfm=False, doubled=True)
        img = dmk.parse_dmk(make_dmk([tr], tracks=1, sides=1))
        t = img.get(0, 0)
        self.assertEqual(len(t.sectors), 10)
        self.assertTrue(all(s.density == "FM" and s.size == 128 for s in t.sectors))
        self.assertTrue(all(s.id_crc_ok and s.data_crc_ok for s in t.sectors))
        self.assertEqual(t.sectors[0].data, bytes((1 + i) & 0xFF for i in range(128)))

    def test_mixed_fm_track0_mfm_rest(self):
        fm0 = make_track([sector(0, 0, n, size_code=0) for n in range(1, 11)], mfm=False, doubled=True)
        img = dmk.parse_dmk(make_dmk([fm0, mfm18(1, 0)], tracks=2, sides=1))
        self.assertEqual(img.get(0, 0).sectors[0].density, "FM")
        self.assertEqual(img.get(1, 0).sectors[0].density, "MFM")

    def test_deleted_dam_preserved(self):
        tr = make_track([sector(0, 0, 1, dam=0xF8), sector(0, 0, 2)], mfm=True)
        t = dmk.parse_dmk(make_dmk([tr], tracks=1, sides=1)).get(0, 0)
        self.assertEqual([s.dam for s in t.sectors], [0xF8, 0xFB])

    def test_missing_trailing_track_marked_not_present(self):
        recs = [mfm18(0, 0), mfm18(0, 1), mfm18(1, 0)]                 # cyl 1 side 1 missing
        img = dmk.parse_dmk(make_dmk(recs, tracks=2, sides=2))
        self.assertTrue(img.get(1, 0).present)
        self.assertFalse(img.get(1, 1).present)
        self.assertEqual(img.get(1, 1).sectors, [])

    def test_bad_data_crc_flagged(self):
        tr = make_track([sector(0, 0, 1, bad_crc=True), sector(0, 0, 2)], mfm=True)
        t = dmk.parse_dmk(make_dmk([tr], tracks=1, sides=1)).get(0, 0)
        self.assertFalse(t.sectors[0].data_crc_ok)
        self.assertTrue(t.sectors[0].id_crc_ok)
        self.assertTrue(t.sectors[1].data_crc_ok)

    def test_set_sector_data_recomputes_crc_and_roundtrips(self):
        raw = make_dmk([mfm18(0, 0)], tracks=1, sides=1)
        img = dmk.parse_dmk(raw)
        new = bytes([0xE5]) * 256
        img.set_sector_data(0, 0, 7, new)
        again = dmk.parse_dmk(img.to_bytes())
        s = [x for x in again.get(0, 0).sectors if x.num == 7][0]
        self.assertEqual(s.data, new)
        self.assertTrue(s.data_crc_ok)
        self.assertNotEqual(img.to_bytes(), raw)
        with self.assertRaises(ValueError):
            img.set_sector_data(0, 0, 7, b"short")

    def test_set_sector_data_on_fm_sector(self):
        tr = make_track([sector(0, 0, n, size_code=0) for n in range(1, 4)], mfm=False, doubled=True)
        img = dmk.parse_dmk(make_dmk([tr], tracks=1, sides=1))
        img.set_sector_data(0, 0, 2, bytes([0x77]) * 128)
        s = dmk.parse_dmk(img.to_bytes()).get(0, 0).sectors[1]
        self.assertEqual(s.data, bytes([0x77]) * 128)
        self.assertTrue(s.data_crc_ok)

    def test_truncated_header_raises(self):
        with self.assertRaises(ValueError):
            dmk.parse_dmk(b"\x00\x28\x00")
        with self.assertRaises(ValueError):
            dmk.parse_dmk(bytes([0, 0]) + bytes(14))                    # zero tracks

    def test_to_bytes_roundtrip_identity(self):
        raw = make_dmk([mfm18(0, 0), mfm18(0, 1), mfm18(1, 0)], tracks=2, sides=2)
        self.assertEqual(dmk.parse_dmk(raw).to_bytes(), raw)


class RealImageTests(unittest.TestCase):
    def test_real_images_parse(self):
        paths = sorted(glob.glob(os.path.join(ROOT, "images", "lsdos631l-upstream", "*.DSK")))
        if not paths:
            self.skipTest("no real images downloaded")
        for p in paths:
            with open(p, "rb") as f:
                img = dmk.parse_dmk(f.read())
            bad = []
            for c in range(img.tracks):
                for sd in range(img.sides):
                    t = img.get(c, sd)
                    for s in t.sectors:
                        if not (s.id_crc_ok and s.data_crc_ok):
                            bad.append((c, sd, s.num))
            present = sum(img.get(c, sd).present for c in range(img.tracks) for sd in range(img.sides))
            print(f"\n{os.path.basename(p)}: tracks={img.tracks} sides={img.sides} len={img.track_len} "
                  f"present={present} bad_crc={bad[:5]}")
            for c in (0, 1, 17, 39):
                for sd in range(img.sides):
                    t = img.get(c, sd)
                    if t.present:
                        print(f"  cyl{c} side{sd}: {len(t.sectors)} sectors "
                              f"{sorted({s.density for s in t.sectors})} sizes={sorted({s.size for s in t.sectors})} "
                              f"dams={sorted({hex(s.dam) for s in t.sectors})} "
                              f"order={[s.num for s in t.sectors]}")
            self.assertEqual(bad, [], os.path.basename(p))


if __name__ == "__main__":
    unittest.main()
