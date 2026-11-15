import io, os, tempfile, unittest

import writedisk
from tests.dmkbuild import make_dmk, make_track, sector
from tests.fakefdc import FakeFdc
from trs80 import dmk
from trs80.fdc import DriveInfo, FdcError


def tiny_image(tracks=3, skip=()):
    """3 cylinders, side 0 only, 4 sectors each, with F5/F6/F7 bytes in the data."""
    recs = []
    for c in range(tracks):
        for side in (0, 1):
            if side == 1 or (c, side) in skip:
                recs.append(make_track([]))
            else:
                recs.append(make_track([sector(c, 0, n, fill=0xF5 + n % 3) for n in (0, 2, 1, 3)]))
    return dmk.parse_dmk(make_dmk(recs, tracks=tracks, sides=2))


def image_file(**kw):
    img = tiny_image(**kw)
    f = tempfile.NamedTemporaryFile(suffix=".dmk", delete=False)
    f.write(make_dmk([make_track([sector(c, 0, n, fill=0xF5 + n % 3) for n in (0, 2, 1, 3)]) if s == 0 else make_track([])
                      for c in range(kw.get("tracks", 3)) for s in (0, 1)], tracks=kw.get("tracks", 3), sides=2))
    f.close()
    return f.name


class ConfirmTests(unittest.TestCase):
    info = DriveInfo(0, True, 39, 1, "x")

    def test_confirm_rejects_wrong_text(self):
        for text in ("", "yes", "erase drive 0", "ERASE DRIVE 1", "ERASE DRIVE 0 "):
            self.assertFalse(writedisk.confirm_erase(0, self.info, lambda p, t=text: t, None, True), text)

    def test_confirm_accepts_exact_text_interactively(self):
        self.assertTrue(writedisk.confirm_erase(0, self.info, lambda p: "ERASE DRIVE 0", None, True))

    def test_noninteractive_without_confirm_arg_refuses(self):
        def boom(p):
            raise AssertionError("must not prompt")
        self.assertFalse(writedisk.confirm_erase(0, self.info, boom, None, False))

    def test_noninteractive_with_exact_confirm_proceeds(self):
        self.assertTrue(writedisk.confirm_erase(0, self.info, None, "ERASE DRIVE 0", False))
        self.assertFalse(writedisk.confirm_erase(0, self.info, None, "ERASE DRIVE 1", False))


class WriteImageTests(unittest.TestCase):
    def test_write_requires_probe_first(self):
        f = FakeFdc()
        with self.assertRaises(RuntimeError):
            writedisk.write_image(f, tiny_image(), 0, progress=lambda *_: None)
        self.assertEqual(f.tracks_written, [])

    def test_writes_every_sector_with_exact_data_even_with_special_bytes(self):
        f, img = FakeFdc(), tiny_image()
        f.probe(0)
        writedisk.write_image(f, img, 0, progress=lambda *_: None)
        self.assertEqual(f.tracks_written, [(0, 0), (1, 0), (2, 0)])
        for c in range(3):
            for s in img.get(c, 0).sectors:
                self.assertEqual(f.disk[(c, 0, s.num)], s.data)
        self.assertFalse(f.armed)                                  # disarmed afterwards

    def test_format_stream_never_carries_sector_data(self):
        f = FakeFdc()
        f.probe(0)
        writedisk.write_image(f, tiny_image(tracks=1), 0, progress=lambda *_: None)
        self.assertNotIn(bytes([0xF6]) * 256, f.last_stream)
        self.assertIn(b"\xE5" * 256, f.last_stream)

    def test_image_track_not_present_is_skipped_and_reported(self):
        f, msgs = FakeFdc(), []
        f.probe(0)
        writedisk.write_image(f, tiny_image(skip={(1, 0)}), 0, progress=msgs.append)
        self.assertEqual(f.tracks_written, [(0, 0), (2, 0)])
        self.assertTrue(any("skipped" in m and "C1 H0" in m for m in msgs), msgs)

    def test_verify_mismatch_retries_then_succeeds(self):
        f = FakeFdc()
        f.probe(0)
        f.corrupt[(1, 0, 2)] = 1
        writedisk.write_image(f, tiny_image(), 0, progress=lambda *_: None, retries=2)
        self.assertEqual(f.tracks_written.count((1, 0)), 2)

    def test_verify_mismatch_retries_then_raises(self):
        f = FakeFdc()
        f.probe(0)
        f.corrupt[(1, 0, 2)] = 99
        with self.assertRaises(writedisk.WriteVerifyError) as cm:
            writedisk.write_image(f, tiny_image(), 0, progress=lambda *_: None, retries=2)
        self.assertEqual((cm.exception.cyl, cm.exception.side, cm.exception.sector), (1, 0, 2))
        self.assertEqual(f.tracks_written.count((1, 0)), 3)
        self.assertFalse(f.armed)

    def test_write_error_code_from_fdc_raises(self):
        f = FakeFdc()
        f.probe(0)
        f.write_errors = 1
        with self.assertRaises(FdcError):
            writedisk.write_image(f, tiny_image(), 0, progress=lambda *_: None)

    def test_deleted_data_mark_sectors_are_written_with_their_mark(self):
        # LS-DOS marks directory sectors with F8; the first real write refused them
        recs = [make_track([sector(0, 0, n, fill=0x41, dam=0xF8 if n == 1 else 0xFB) for n in (0, 1, 2)]), make_track([])]
        img = dmk.parse_dmk(make_dmk(recs, tracks=1, sides=2))
        f = FakeFdc()
        f.probe(0)
        writedisk.write_image(f, img, 0, progress=lambda *_: None)
        self.assertEqual([f.dams[(0, 0, n)] for n in (0, 1, 2)], [0xFB, 0xF8, 0xFB])

    def test_unwritable_data_mark_refuses_before_touching_the_disk(self):
        recs = [make_track([sector(0, 0, 0, fill=0x41, dam=0xFA)]), make_track([])]
        img = dmk.parse_dmk(make_dmk(recs, tracks=1, sides=2))
        f = FakeFdc()
        f.probe(0)
        with self.assertRaises(FdcError):
            writedisk.write_image(f, img, 0, progress=lambda *_: None)
        self.assertEqual(f.tracks_written, [])

    def test_verify_message_says_mismatch_or_read_error(self):
        f, msgs = FakeFdc(), []
        f.probe(0)
        f.corrupt[(1, 0, 2)] = 1
        writedisk.write_image(f, tiny_image(), 0, progress=msgs.append, retries=2)
        self.assertTrue(any("sector 2" in m and "read back different data" in m for m in msgs), msgs)
        f2, msgs = FakeFdc(), []
        f2.probe(0)
        orig = f2.read_sector
        calls = []

        def flaky(drive, cyl, side, sector, size, density):
            if (cyl, sector) == (1, 3) and not calls:
                calls.append(1)
                raise FdcError("RNF (status 0x10)")
            return orig(drive, cyl, side, sector, size, density)
        f2.read_sector = flaky
        writedisk.write_image(f2, tiny_image(), 0, progress=msgs.append, retries=2)
        self.assertTrue(any("sector 3" in m and "could not be read" in m and "RNF" in m for m in msgs), msgs)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.img = image_file()
        self.addCleanup(os.unlink, self.img)
        self.out = io.StringIO()
        self.opened = []

    def run_cli(self, argv, fake=None, input_fn=None, isatty=False):
        fake = fake or FakeFdc()

        def open_fdc(port):
            self.opened.append(port)
            return fake
        self.fake = fake
        return writedisk.main(argv, input_fn=input_fn or (lambda p: ""), open_fdc=open_fdc,
                              out=lambda *a: print(*a, file=self.out), isatty=isatty)

    def test_dry_run_never_touches_serial_or_fdc(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--dry-run"])
        self.assertEqual((rc, self.opened), (0, []))
        self.assertIn("3 tracks", self.out.getvalue())

    def test_probe_only_never_arms_or_writes(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--probe-only"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.events, ["probe"])

    def test_drive_not_present_refuses(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--confirm", "ERASE DRIVE 0"], fake=FakeFdc(present=False))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.fake.tracks_written, [])

    def test_wrong_confirmation_writes_nothing(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0"], input_fn=lambda p: "no", isatty=True)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.fake.tracks_written, [])
        self.assertNotIn("arm", self.fake.events)

    def test_confirmed_write_succeeds(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--confirm", "ERASE DRIVE 0"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.fake.tracks_written), 3)

    def test_image_larger_than_drive_refuses_before_writing(self):
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--confirm", "ERASE DRIVE 0"], fake=FakeFdc(max_track=1))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.fake.tracks_written, [])

    def test_no_yes_flag(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["--image", self.img, "--drive", "0", "--yes"])

    def test_keyboard_interrupt_reports_partial_disk_and_exit_code(self):
        fake = FakeFdc()
        fake.interrupt_on_track = (1, 0)
        rc = self.run_cli(["--image", self.img, "--drive", "0", "--confirm", "ERASE DRIVE 0"], fake=fake)
        self.assertNotEqual(rc, 0)
        text = self.out.getvalue()
        self.assertIn("partly written", text)
        self.assertIn("will not boot", text)
        self.assertIn("track 0", text)
        self.assertFalse(fake.armed)


if __name__ == "__main__":
    unittest.main()
