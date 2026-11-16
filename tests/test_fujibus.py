"""Reference FujiBus/SLIP/DiskDevice codec, checked against the byte vectors in fujinet-nio's own docs
(docs/protocol_reference.md section 11, docs/disk_device_test_vectors.md)."""
import unittest

from fujinet import fujibus as fb
from fujinet import niodisk as nd

REQ = bytes.fromhex("01 10 0B 00 03 01 AA DE AD BE EF")     # protocol_reference.md section 11
RESP = bytes.fromhex("01 10 0B 00 58 01 00 DE AD BE EF")


class ChecksumTests(unittest.TestCase):
    def test_documented_examples(self):
        self.assertEqual(fb.checksum(REQ[:4] + b"\x00" + REQ[5:]), 0x03)
        self.assertEqual(fb.checksum(RESP[:4] + b"\x00" + RESP[5:]), 0x58)

    def test_carry_is_folded_back_in(self):
        self.assertEqual(fb.checksum(b"\xFF\x03"), 0x03)           # 0x102 -> 0x03
        self.assertEqual(fb.checksum(b"\xFF\xFF"), 0xFF)


class PacketTests(unittest.TestCase):
    def test_build_request_matches_documented_example(self):
        self.assertEqual(fb.build_packet(0x01, 0x10, b"\xDE\xAD\xBE\xEF", params=[(0xAA, 1)]), REQ)

    def test_build_response_matches_documented_example(self):
        self.assertEqual(fb.build_response(0x01, 0x10, 0, b"\xDE\xAD\xBE\xEF"), RESP)

    def test_parse_response(self):
        p = fb.parse_packet(RESP)
        self.assertEqual((p.device, p.command, p.params, p.payload), (1, 0x10, [0], b"\xDE\xAD\xBE\xEF"))

    def test_payload_only_request_has_no_descriptor_fields(self):
        raw = fb.build_packet(0xFC, 0x03, b"\x01\x01")
        self.assertEqual(raw[:2], b"\xFC\x03")
        self.assertEqual((raw[2] | raw[3] << 8, raw[5]), (8, 0))
        self.assertEqual(fb.parse_packet(raw).payload, b"\x01\x01")

    def test_bad_checksum_and_bad_length_are_rejected(self):
        bad = bytearray(RESP); bad[4] ^= 1
        with self.assertRaises(fb.PacketError):
            fb.parse_packet(bytes(bad))
        with self.assertRaises(fb.PacketError):
            fb.parse_packet(RESP + b"\x00")
        with self.assertRaises(fb.PacketError):
            fb.parse_packet(RESP[:5])

    def test_multi_byte_params_round_trip(self):
        raw = fb.build_packet(0x70, 0x01, b"xyz", params=[(0x1234, 2)])
        self.assertEqual(fb.parse_packet(raw).params, [0x1234])
        raw = fb.build_packet(0x70, 0x01, b"", params=[(0xDEADBEEF, 4)])
        self.assertEqual(fb.parse_packet(raw).params, [0xDEADBEEF])


class SlipTests(unittest.TestCase):
    def test_escapes_end_and_esc(self):
        self.assertEqual(fb.slip_encode(b"\x01\xC0\xDB\x02"), b"\xC0\x01\xDB\xDC\xDB\xDD\x02\xC0")

    def test_decoder_handles_split_chunks_empty_frames_and_back_to_back_frames(self):
        dec = fb.SlipDecoder()
        wire = fb.slip_encode(b"\x01\xC0\x02") + b"\xC0" + fb.slip_encode(b"\xDB\x03")
        out = []
        for i in range(0, len(wire), 2):
            out += dec.feed(wire[i:i + 2])
        self.assertEqual(out, [b"\x01\xC0\x02", b"\xDB\x03"])

    def test_bad_escape_drops_the_frame(self):
        dec = fb.SlipDecoder()
        self.assertEqual(dec.feed(b"\xC0\x01\xDB\x55\x02\xC0"), [])


class DiskCodecTests(unittest.TestCase):
    def test_documented_request_vectors(self):
        self.assertEqual(nd.read_sector_request(1, 1759, 8), bytes.fromhex("01 01 df 06 00 00 08 00"))
        self.assertEqual(nd.write_sector_request(1, 2, bytes([1, 2, 3, 4])), bytes.fromhex("01 01 02 00 00 00 04 00 01 02 03 04"))
        self.assertEqual(nd.mount_request(1, "host:/images/test.adf", readonly=True),
                         bytes.fromhex("01 01 01 00 00 00 15 00") + b"host:/images/test.adf")

    def test_documented_read_response(self):
        r = nd.parse_read_response(bytes.fromhex("01 00 00 00 01 df 06 00 00 04 00 41 42 43 44"))
        self.assertEqual((r.slot, r.lba, r.data), (1, 1759, b"ABCD"))

    def test_documented_info_response(self):
        i = nd.parse_info_response(bytes.fromhex("01 09 00 00 01 04 00 02 e0 06 00 00 00"))
        self.assertEqual((i.inserted, i.slot, i.sector_size, i.sector_count), (True, 1, 512, 1760))
        i = nd.parse_info_response(bytes.fromhex("01 09 00 00 01 04 00 02 e0 06 00 00"))     # 12-byte form
        self.assertEqual(i.last_error, 0)


if __name__ == "__main__":
    unittest.main()
