# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
import os, unittest

from tools.dmk_to_img import dmk_to_img
from tools.jv3_to_dmk import jv3_to_dmk
from tools.make_data_image import build_disk, dos_name
from trs80 import jv3, lsdosfs
from trs80.dmk import parse_dmk


def make_jv3(cyls=3, spt=18, deleted=((1, 5),)):
    hdr, body = bytearray(b"\xFF" * 2901 * 3), bytearray()
    i = 0
    for t in range(cyls):
        for s in range(spt):
            hdr[i * 3:i * 3 + 3] = bytes([t, s, 0x80 | (0x20 if (t, s) in deleted else 0)])
            body += bytes((t * 31 + s * 7 + k) & 0xFF for k in range(256))
            i += 1
    return bytes(hdr) + b"\x00" + bytes(body)


class Jv3ToDmkTests(unittest.TestCase):
    def test_every_sector_survives_with_its_id_and_mark(self):
        src = make_jv3()
        dmk, bad = jv3_to_dmk(src)
        self.assertEqual(bad, 0)
        img = parse_dmk(dmk)
        flat = jv3.flat_image(src)
        for t in range(3):
            tr = img.get(t, 0)
            self.assertEqual([s.num for s in tr.sectors], list(range(18)))
            for s in tr.sectors:
                self.assertTrue(s.id_crc_ok and s.data_crc_ok and s.mfm)
                self.assertEqual(s.data, flat[(t * 18 + s.num) * 256:(t * 18 + s.num + 1) * 256])
                self.assertEqual(s.dam, 0xF8 if (t, s.num) == (1, 5) else 0xFB)

    def test_dmk_to_img_round_trips_a_real_ls_dos_disk(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "lsdos631l-upstream", "L631NEW.DSK")
        with open(base, "rb") as f:
            raw, bad = dmk_to_img(f.read())
        self.assertEqual(bad, [])
        self.assertEqual(len(raw) % 256, 0)
        self.assertEqual(raw, lsdosfs.flat_image(parse_dmk(open(base, "rb").read())))

    def test_data_image_holds_only_the_given_files_and_reads_back(self):
        prog = bytes((i * 13 + 5) & 0xFF for i in range(21483))        # about the size of a big game
        disk = build_disk([(dos_name("/x/TETRIS.CMD"), prog)])
        names = sorted(f"{e.name}/{e.ext}" for e in lsdosfs.list_files(disk))
        self.assertEqual(names, ["BOOT/SYS", "DIR/SYS", "TETRIS/CMD"])
        self.assertEqual(lsdosfs.read_file(disk, "TETRIS/CMD"), prog)
        self.assertEqual(dos_name("a/My.Game.cmd"), "MY.GAME/CMD")

    def test_real_image_if_present(self):
        path = os.path.expanduser("~/Downloads/Scripsit Pro v1.0.0 (1985)(Tandy)[DSK]/Spro.dsk")
        if not os.path.exists(path):
            self.skipTest("Spro.dsk not downloaded")
        src = open(path, "rb").read()
        dmk, _ = jv3_to_dmk(src)
        self.assertEqual(lsdosfs.flat_image(parse_dmk(dmk)), jv3.flat_image(src))


if __name__ == "__main__":
    unittest.main()
