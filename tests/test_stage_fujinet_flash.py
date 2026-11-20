# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
import os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools import stage_fujinet_flash as stage  # noqa: E402


class StagedYamlTests(unittest.TestCase):
    def test_timezone_is_a_posix_tz_string_not_an_olson_name(self):
        # ESP32 newlib has no zoneinfo: set_timezone() just does setenv("TZ"), so "America/New_York" means UTC there.
        tz = re.search(r"^\s*timezone:\s*(\S+)", stage.YAML, re.M).group(1)
        self.assertEqual(tz, "EST5EDT,M3.2.0,M11.1.0")

    def test_loader_and_uart_settings(self):
        for line in ("baud_rate: 19200", "parity: odd", "enabled: true", "path: flash:/boot/trs80/nioboot.cmd",
                     "config_uri: flash:/boot/trs80/boot.xfd"):
            self.assertIn(line, stage.YAML)


if __name__ == "__main__":
    unittest.main()
