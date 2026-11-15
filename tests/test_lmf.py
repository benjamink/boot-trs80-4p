import hashlib, os, pty, tempfile, unittest

from trs80 import lmf, serialio
import trs80boot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def records(blob):
    """Split a load module into (type, payload) records."""
    i, out = 0, []
    while i < len(blob):
        typ, ln = blob[i], blob[i + 1]
        ln = ln or 256
        out.append((typ, blob[i + 2:i + 2 + ln]))
        i += 2 + ln
    return out


class LmfTests(unittest.TestCase):
    def test_build_lmf_16_byte_records(self):
        segs, entry = trs80boot.test_program()
        blob = lmf.build_lmf(segs, entry, 16)
        recs = records(blob)
        data_recs = [r for r in recs if r[0] == 1]
        self.assertTrue(all(len(p) <= 18 for _, p in data_recs))  # 2 addr bytes + <=16 data
        self.assertEqual(blob[-4:], bytes([0x02, 0x02, 0x00, 0x60]))

    def test_parse_hex_scrdump(self):
        segs, entry = lmf.parse_hex(os.path.join(ROOT, "examples", "SCRDUMP.HEX"))
        self.assertEqual({k: len(v) for k, v in segs.items()}, {0x6000: 156})
        self.assertEqual(entry, 0x604B)

    def test_parse_hex_bad_checksum_exits(self):
        with tempfile.NamedTemporaryFile("w", suffix=".hex", delete=False) as f:
            f.write(":0100000041BF\n:00000001FF\n")  # correct checksum is BE, this is off by one
            path = f.name
        try:
            with self.assertRaises(SystemExit):
                lmf.parse_hex(path)
        finally:
            os.unlink(path)

    def test_test_program_matches_known_bytes(self):
        segs, entry = trs80boot.test_program()
        blob = lmf.build_lmf(segs, entry, 16)
        self.assertEqual(len(blob), 263)
        self.assertEqual(hashlib.sha256(blob).hexdigest(),
                         "f8b5082864c0bde8800ce4b9080b37e564ae333f4e930015f288b561e67a8a23")


class ParseLmfTests(unittest.TestCase):
    def test_parse_lmf_roundtrip(self):
        segs, entry = trs80boot.test_program()
        got_segs, got_entry = lmf.parse_lmf(lmf.build_lmf(segs, entry, 16))
        self.assertEqual(got_segs, segs)
        self.assertEqual(got_entry, entry)

    def test_parse_lmf_ignores_comment_records_and_stops_at_entry(self):
        blob = bytes([0x05, 0x03, 0x41, 0x42, 0x43]) + lmf.lmf_data_block(0x8000, b"\x01\x02") \
            + lmf.lmf_entry(0x8000) + bytes([0x01, 0x03, 0x00, 0x90, 0xFF])   # junk after entry
        segs, entry = lmf.parse_lmf(blob)
        self.assertEqual(segs, {0x8000: b"\x01\x02"})
        self.assertEqual(entry, 0x8000)

    def test_parse_lmf_truncated_raises(self):
        with self.assertRaises(ValueError):
            lmf.parse_lmf(bytes([0x01, 0x10, 0x00, 0x80, 0x01]))


class SerialTests(unittest.TestCase):
    def test_handshake_times_out(self):
        master, slave = pty.openpty()
        try:
            with self.assertRaises(serialio.LoaderNotReady) as cm:
                serialio.handshake(slave, 19200, ["8O1"], timeout=0.5)
            self.assertIn("right-shift", str(cm.exception).lower())
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
