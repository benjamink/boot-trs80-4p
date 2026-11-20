# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Runs the real build/mon.hex in a tiny Z80 interpreter behind the real Monitor client."""
import os, shutil, subprocess, unittest

from tests.emutransport import EmuTransport
from trs80.monitor import Monitor, MonitorError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class EmulatedMonitorTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT, "build/mon.hex"], check=True,
                       stdout=subprocess.DEVNULL)
        self.t = EmuTransport(os.path.join(ROOT, "build", "mon.hex"),
                              os.path.join(ROOT, "build", "mon.sym"))
        self.m = Monitor(self.t, timeout=0.01, retries=4)

    def test_ping_echo_empty_and_max(self):
        self.assertEqual(self.m.ping(b"hello"), b"hello")
        self.assertEqual(self.m.ping(), b"")
        self.assertEqual(self.m.ping(bytes(range(250))), bytes(range(250)))

    def test_write_read_roundtrip_2k(self):
        data = bytes((i * 7 + 3) & 0xFF for i in range(2048))
        self.m.write_mem(0x8000, data)
        self.assertEqual(bytes(self.t.cpu.mem[0x8000:0x8800]), data)
        self.assertEqual(self.m.read_mem(0x8000, 2048), data)

    def test_exec_returns_a_register(self):
        self.m.write_mem(0x8000, bytes([0x3E, 0x42, 0xC9]))   # LD A,42h ; RET
        self.assertEqual(self.m.exec(0x8000)["A"], 0x42)

    def test_exec_returns_all_registers_in_order(self):
        # LD BC,0102h; LD DE,0304h; LD HL,0506h; LD A,07h; RET
        self.m.write_mem(0x8000, bytes([0x01, 2, 1, 0x11, 4, 3, 0x21, 6, 5, 0x3E, 7, 0xC9]))
        r = self.m.exec(0x8000)
        self.assertEqual((r["A"], r["B"], r["C"], r["D"], r["E"], r["H"], r["L"]),
                         (7, 1, 2, 3, 4, 5, 6))

    def test_port_in_and_out(self):
        self.assertEqual(self.m.port_in(0x77), 0x5A)
        self.m.port_out(0x90, 0x33)
        self.assertIn((0x90, 0x33), self.t.port_writes)

    def test_bad_checksum_is_nakked_and_retried(self):
        self.t.corrupt_next_write = True
        self.assertEqual(self.m.ping(b"retry me"), b"retry me")

    def test_duplicate_seq_not_reexecuted(self):
        self.m.write_mem(0x9000, bytes([0]))
        self.m.write_mem(0x8000, bytes([0x21, 0x00, 0x90, 0x34, 0xC9]))  # LD HL,9000h; INC (HL); RET
        self.t.drop_next_response = True
        self.m.exec(0x8000)
        self.assertEqual(self.t.cpu.mem[0x9000], 1)

    def test_partial_frame_times_out_and_monitor_resyncs(self):
        self.t.truncate_next_write = 3          # A5 cmd seq ... then silence
        self.assertEqual(self.m.ping(b"after the stall"), b"after the stall")

    def test_garbage_before_frame_is_skipped(self):
        self.t.rx.extend(b"\x00\x13\x99\x42")
        self.assertEqual(self.m.ping(b"ok"), b"ok")

    def test_unknown_command_reports_error(self):
        with self.assertRaises(MonitorError):
            self.m._request(0x7F, b"")

    def test_write_with_short_payload_is_rejected(self):
        with self.assertRaises(MonitorError):
            self.m._request(2, b"\x00")          # WRITE_MEM needs addr (2 bytes)


if __name__ == "__main__":
    unittest.main()
