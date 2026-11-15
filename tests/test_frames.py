import unittest

from trs80 import frames as F


class FrameTests(unittest.TestCase):
    def test_roundtrip_all_commands(self):
        for cmd in (F.CMD_PING, F.CMD_WRITE_MEM, F.CMD_READ_MEM, F.CMD_EXEC, F.CMD_IN, F.CMD_OUT):
            pl = bytes(range(cmd, cmd + 5))
            p = F.parse_frame(F.encode_request(cmd, 7, pl), F.SYNC_REQ)
            self.assertEqual((p.code, p.seq, p.payload, p.ok), (cmd, 7, pl, True))
        r = F.parse_frame(F.encode_response(F.ST_OK, 9, b"xyz"), F.SYNC_RSP)
        self.assertEqual((r.code, r.seq, r.payload, r.ok), (F.ST_OK, 9, b"xyz", True))

    def test_checksum_known_value(self):
        self.assertEqual(F.encode_request(F.CMD_PING, 1, b"\x01\x02"),
                         bytes([0xA5, 0x01, 0x01, 0x02, 0x01, 0x02, 0x07, 0x00]))
        self.assertEqual(F.checksum(bytes([1, 1, 2, 1, 2])), 7)

    def test_bad_checksum_flagged_and_consumed(self):
        raw = bytearray(F.encode_request(F.CMD_PING, 3, b"abc"))
        raw[5] ^= 0xFF
        p = F.parse_frame(bytes(raw), F.SYNC_REQ)
        self.assertFalse(p.ok)
        self.assertEqual(p.consumed, len(raw))

    def test_garbage_prefix_skipped(self):
        good = F.encode_request(F.CMD_PING, 4, b"hi")
        p = F.parse_frame(b"\x00\x13\x99" + good, F.SYNC_REQ)
        self.assertTrue(p.ok)
        self.assertEqual(p.consumed, 3 + len(good))
        self.assertEqual(p.payload, b"hi")

    def test_incomplete_returns_none(self):
        good = F.encode_request(F.CMD_PING, 4, b"hello")
        for n in range(len(good)):
            self.assertIsNone(F.parse_frame(good[:n], F.SYNC_REQ), n)

    def test_payload_too_long_raises(self):
        F.encode_request(F.CMD_PING, 0, bytes(F.MAX_PAYLOAD))
        with self.assertRaises(ValueError):
            F.encode_request(F.CMD_PING, 0, bytes(F.MAX_PAYLOAD + 1))
        with self.assertRaises(ValueError):
            F.encode_response(F.ST_OK, 0, bytes(F.MAX_PAYLOAD + 1))

    def test_two_frames_back_to_back(self):
        a = F.encode_request(F.CMD_PING, 1, b"a")
        b = F.encode_request(F.CMD_PING, 2, b"bb")
        buf = a + b
        p1 = F.parse_frame(buf, F.SYNC_REQ)
        p2 = F.parse_frame(buf[p1.consumed:], F.SYNC_REQ)
        self.assertEqual((p1.seq, p1.payload, p2.seq, p2.payload), (1, b"a", 2, b"bb"))


if __name__ == "__main__":
    unittest.main()
