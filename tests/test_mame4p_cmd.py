import os, unittest
from unittest import mock
from tools.mame4p import Mame4P


class CommandTests(unittest.TestCase):
    def test_headless_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAME4P_WINDOW", None)
            c = Mame4P("/roms").command()
        self.assertIn("none", c[c.index("-video") + 1:c.index("-video") + 2])
        self.assertNotIn("-window", c)

    def test_window_by_argument_or_environment(self):
        self.assertIn("-window", Mame4P("/roms", window=True).command())
        with mock.patch.dict(os.environ, {"MAME4P_WINDOW": "1"}):
            c = Mame4P("/roms").command()
        self.assertIn("-window", c)
        self.assertNotIn("-video", c)

    def test_disk_is_added_when_given(self):
        c = Mame4P("/roms", "/x/boot.dmk").command()
        self.assertEqual(c[c.index("-flop1") + 1], "/x/boot.dmk")


if __name__ == "__main__":
    unittest.main()
