# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
import glob, os, unittest

from trs80 import dmk, trackplan as tp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MFM_ID = b"\xF5\xF5\xF5\xFE"
MFM_DATA = b"\xF5\xF5\xF5"


def sec(num, size=256, dam=0xFB, density="MFM", cyl=0, side=0):
    data = bytes((num + i) % 0xF0 for i in range(size))          # never produces F5..FF
    return dmk.Sector(cyl, side, num, size, dam, data, density, True, True)


def track(sectors):
    return dmk.Track(0, 0, True, sectors)


def id_sector_order(stream, marker=MFM_ID):
    out, i = [], 0
    while True:
        i = stream.find(marker, i)
        if i < 0:
            return out
        out.append(stream[i + len(marker) + 2])                   # cyl, side, SECTOR, size
        i += len(marker)


class TrackPlanTests(unittest.TestCase):
    def test_mfm_18x256_structure(self):
        t = track([sec(n) for n in range(1, 19)])
        s = tp.build_write_track(t)
        self.assertEqual(len(s), tp.PAD_LEN)
        self.assertEqual(id_sector_order(s), list(range(1, 19)))
        self.assertEqual(s.count(MFM_ID), 18)
        self.assertEqual(s.count(MFM_DATA + b"\xFB"), 18)
        self.assertEqual(s.count(b"\xF7"), 36)                    # one per ID field, one per data field
        first = s.find(MFM_ID)
        self.assertEqual(s[first - 44:first], b"\x4E" * 32 + b"\x00" * 12)   # pre-gap, then sync zeros
        self.assertEqual(s[first + 4:first + 8], bytes([0, 0, 1, 1]))   # cyl, side, sector, size code
        self.assertEqual(s[first + 8], 0xF7)

    def test_fm_track_uses_no_f5_and_has_fc_index(self):
        t = track([sec(n, size=128, density="FM") for n in range(1, 11)])
        s = tp.build_write_track(t)
        self.assertNotIn(b"\xF5", s)
        self.assertEqual(s.count(b"\xFC"), 1)
        self.assertEqual(s.count(b"\xFE"), 10)
        self.assertEqual(s.count(b"\xFB"), 10)
        self.assertEqual(s.count(b"\xF7"), 20)

    def test_deleted_dam_f8_preserved(self):
        s = tp.build_write_track(track([sec(1, dam=0xF8), sec(2)]))
        self.assertIn(MFM_DATA + b"\xF8", s)
        self.assertEqual(s.count(MFM_DATA + b"\xFB"), 1)

    def test_non_default_interleave_preserved(self):
        order = [0, 9, 1, 10, 2, 11, 3, 12, 4, 13, 5, 14, 6, 15, 7, 16, 8, 17]
        s = tp.build_write_track(track([sec(n) for n in order]))
        self.assertEqual(id_sector_order(s), order)

    def test_oversize_track_raises(self):
        with self.assertRaises(ValueError):
            tp.build_write_track(track([sec(n) for n in range(26)]))     # 26 x 256 does not fit

    def test_mixed_density_in_one_track_rejected(self):
        with self.assertRaises(ValueError):
            tp.build_write_track(track([sec(1), sec(2, size=128, density="FM")]))

    def test_empty_track_rejected(self):
        with self.assertRaises(ValueError):
            tp.build_write_track(track([]))

    def test_verify_plan_matches_image_data(self):
        secs = [sec(n) for n in (3, 1, 2)]
        self.assertEqual(tp.verify_plan(track(secs)), [(3, 256, secs[0].data), (1, 256, secs[1].data),
                                                       (2, 256, secs[2].data)])

    def test_real_image_tracks_fit(self):
        paths = sorted(glob.glob(os.path.join(ROOT, "images", "lsdos631l-upstream", "LD4-631.DSK")))
        if not paths:
            self.skipTest("no real image")
        with open(paths[0], "rb") as f:
            img = dmk.parse_dmk(f.read())
        n = 0
        for c in range(img.tracks):
            t = img.get(c, 0)
            if t.sectors:
                s = tp.build_write_track(t)
                self.assertEqual(id_sector_order(s), [x.num for x in t.sectors])
                n += 1
        self.assertEqual(n, 40)


if __name__ == "__main__":
    unittest.main()


class FormatFillTests(unittest.TestCase):
    def test_fill_replaces_data_so_special_bytes_never_reach_write_track(self):
        s = dmk.Sector(0, 0, 1, 256, 0xFB, bytes([0xF5, 0xF6, 0xF7, 0xE5] * 64), "MFM", True, True)
        plain = tp.build_write_track(track([s]))
        filled = tp.build_write_track(track([s]), fill=0xE5)
        self.assertEqual(len(plain), len(filled))
        self.assertIn(b"\xF5\xF6\xF7\xE5", plain)
        body = filled[filled.index(b"\xFB") + 1:][:256]
        self.assertEqual(body, b"\xE5" * 256)
        self.assertEqual(id_sector_order(filled), [1])
