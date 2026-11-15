import unittest

from tests.fake4p import FakeFourP
from tools.monstress import run_stress
from trs80.monitor import Monitor


def rig():
    fake = FakeFourP()
    fake.exec_handlers[0x8100] = lambda f: {"A": 0x42}
    return fake, Monitor(fake, timeout=0.01, retries=3)


class StressTests(unittest.TestCase):
    def test_clean_run_reports_zero_failures(self):
        fake, m = rig()
        r = run_stress(m, pings=40, mem_bytes=2048, port_reads=5, seed=1)
        self.assertEqual(r.failures, 0)
        self.assertEqual(r.operations, 40 + 2 + 5 + 1)

    def test_memory_corruption_is_counted_as_failure(self):
        fake, m = rig()
        orig = fake._execute

        def flaky(cmd, pl):
            st, out = orig(cmd, pl)
            if cmd == 3 and len(out) > 4:               # corrupt every READ_MEM answer
                out = bytes([out[0] ^ 1]) + out[1:]
            return st, out
        fake._execute = flaky
        r = run_stress(m, pings=1, mem_bytes=1024, port_reads=1, seed=1)
        self.assertGreaterEqual(r.failures, 1)

    def test_dead_link_counts_failures_instead_of_raising(self):
        fake, m = rig()
        fake.mute = True
        r = run_stress(m, pings=3, mem_bytes=256, port_reads=1, seed=1)
        self.assertEqual(r.failures, r.operations)


if __name__ == "__main__":
    unittest.main()
