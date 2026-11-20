# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
import os, unittest

from tests.fake4p import FakeFourP
from trs80.monitor import Monitor, MonitorError


def make(**kw):
    fake = FakeFourP()
    return fake, Monitor(fake, timeout=0.01, retries=4, **kw)


class MonitorTests(unittest.TestCase):
    def test_ping_echo(self):
        _, m = make()
        self.assertEqual(m.ping(b"hello"), b"hello")
        self.assertEqual(m.ping(), b"")

    def test_write_read_64k_roundtrip(self):
        fake, m = make()
        data = os.urandom(65536)
        m.write_mem(0, data)
        self.assertEqual(bytes(fake.mem), data)
        self.assertEqual(m.read_mem(0, 65536), data)

    def test_retry_on_dropped_response(self):
        fake, m = make()
        fake.drop_next_response()
        self.assertEqual(m.ping(b"x"), b"x")

    def test_retry_on_corrupt_response(self):
        fake, m = make()
        fake.corrupt_next_response()
        self.assertEqual(m.ping(b"y"), b"y")

    def test_duplicate_seq_not_reexecuted(self):
        fake, m = make()
        fake.exec_handlers[0x8000] = lambda f: {"A": 1}
        fake.drop_next_response()
        regs = m.exec(0x8000)
        self.assertEqual(fake.exec_count[0x8000], 1)
        self.assertEqual(regs["A"], 1)

    def test_resync_after_garbage_between_frames(self):
        fake, m = make()
        fake.inject_garbage(b"\x00\x13\x99")
        self.assertEqual(m.ping(b"ok"), b"ok")
        self.assertEqual(m.ping(b"again"), b"again")

    def test_timeout_raises_monitor_error(self):
        fake, m = make()
        fake.mute = True
        with self.assertRaises(MonitorError):
            m.ping(b"anyone?")

    def spy_reads(self, fake):
        waits = []
        real = fake.read
        fake.read = lambda timeout: (waits.append(timeout), real(timeout))[1]
        return waits

    def test_exec_waits_long_for_the_answer_because_an_ls_dos_call_can_take_seconds(self):
        # a floppy needs motor spin-up and seeks for @INIT/@WRITE; the monitor cannot answer until the call returns
        fake, m = make()
        fake.exec_handlers[0x8000] = lambda f: {"A": 1}
        waits = self.spy_reads(fake)
        m.exec(0x8000)
        self.assertGreaterEqual(max(waits), 10)
        waits.clear()
        m.ping(b"x")
        self.assertLessEqual(max(waits), 0.01)                        # other commands keep the short timeout

    def test_exec_can_be_given_the_short_timeout(self):
        fake, m = make()
        fake.exec_handlers[0x8000] = lambda f: {"A": 1}
        waits = self.spy_reads(fake)
        m.exec(0x8000, timeout=0.01)
        self.assertLessEqual(max(waits), 0.01)

    def test_exec_returns_registers(self):
        fake, m = make()
        fake.exec_handlers[0x9000] = lambda f: dict(A=0x42, F=0x44, B=1, C=2, D=3, E=4, H=5, L=6)
        self.assertEqual(m.exec(0x9000),
                         dict(A=0x42, F=0x44, B=1, C=2, D=3, E=4, H=5, L=6))

    def test_port_in_out(self):
        fake, m = make()
        m.port_out(0xEB, 0x41)
        self.assertEqual(fake.ports[0xEB], 0x41)
        fake.ports[0xEA] = 0x77
        self.assertEqual(m.port_in(0xEA), 0x77)

    def test_retry_count_is_tracked(self):
        fake, m = make()
        m.ping(b"a")
        self.assertEqual(m.retry_count, 0)
        fake.drop_next_response()
        m.ping(b"b")
        self.assertEqual(m.retry_count, 1)

    def test_sync_recovers_from_stale_duplicate(self):
        fake = FakeFourP()
        Monitor(fake, timeout=0.01).ping(b"old")                  # 4P now remembers seq 0
        stale = Monitor(fake, timeout=0.01).ping(b"new")           # fresh client reuses seq 0
        self.assertEqual(stale, b"old")                            # the hazard: replayed answer
        m = Monitor(fake, timeout=0.01)
        m.sync()
        self.assertEqual(m.ping(b"z"), b"z")

    def test_sequence_numbers_wrap(self):
        _, m = make()
        for i in range(300):
            self.assertEqual(m.ping(bytes([i & 255])), bytes([i & 255]))


if __name__ == "__main__":
    unittest.main()
