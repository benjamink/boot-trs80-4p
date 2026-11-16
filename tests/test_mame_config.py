"""CONFIG/CMD (nio-config's trs80/ C program, built with z88dk) on MAME's Model 4P.

Opt-in like test_mame_integration:  MAME_TESTS=1 python3 -m unittest tests.test_mame_config
Needs z88dk and the nio-config checkout (NIO_CONFIG_DIR, default ../fujinet-nio-workspace/repos/nio-config).
"""
import os, select, shutil, subprocess, tempfile, threading, time, tty, unittest

from fujinet import fujibus as fb
from tests.fakenio import FakeNio
from tests.test_mame_integration import BASE, ROMS, HAVE, serve
from tools.make_boot_image import DROP, make_boot_image
from tools.mame4p import Mame4P
from tools.zcc_cmd import bin_to_lmf
from trs80 import dmk, lsdosfs
from trs80.lmf import build_lmf, parse_hex

NIO_CONFIG = os.environ.get("NIO_CONFIG_DIR", os.path.expanduser("~/dev/fujinet-nio-workspace/repos/nio-config"))
TRS80 = os.path.join(NIO_CONFIG, "trs80")


# The stock LS-DOS disk is nearly full; CONFIG is far bigger than the commands already added. Tests drop the
# BASIC family and other bulk (about 30 KB) to make room; what the shipped boot disk drops is Task 7's decision.
TEST_DROP = DROP + ("BASIC/CMD", "BASIC/OV1", "BASIC/OV2", "BREF/CMD")


@unittest.skipUnless(HAVE and shutil.which("zcc"), "set MAME_TESTS=1 and install mame, sjasmplus, z88dk, the LS-DOS image and the 4P ROMs")
class ConfigOnMameTests(unittest.TestCase):
    def boot(self, extra):
        """Boots LS-DOS from a scratch image that also holds {name: /CMD bytes}."""
        subprocess.run(["make", "-C", os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "all"], check=True, stdout=subprocess.DEVNULL)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        disk = os.path.join(tmp, "boot.dmk")
        make_boot_image(BASE, disk, drop=TEST_DROP)
        with open(disk, "rb") as f:
            img = dmk.parse_dmk(f.read())
        for name, blob in extra.items():
            img = lsdosfs.add_file(img, name, blob)
        with open(disk, "wb") as f:
            f.write(img.to_bytes())
        self.mame = Mame4P(ROMS, disk)
        self.mame.start()
        self.addCleanup(self.mame.stop)
        self.mame.wait_for("Date MM/DD/YY", 120)
        self.mame.type("01/02/26\n")
        self.mame.wait_for("Time HH:MM:SS", 30)
        self.mame.type("\n")
        self.mame.wait_for("LS-DOS Ready", 30)
        time.sleep(1)

    def build(self, name, with_client=False):
        """/CMD for trs80/build/<name>.bin; with_client also carries the client (nioclient_config.asm, D000h), as CONFIG/CMD does."""
        subprocess.run(["make", "-C", TRS80, "build/%s.bin" % name], check=True, stdout=subprocess.DEVNULL)
        with open(os.path.join(TRS80, "build", name + ".bin"), "rb") as f:
            segs = {0x3000: f.read()}
        if with_client:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            subprocess.run(["make", "-C", root, "build/nioclient_config.hex"], check=True, stdout=subprocess.DEVNULL)
            client, _ = parse_hex(os.path.join(root, "build", "nioclient_config.hex"))
            segs.update(client)
        assert 0x3000 + len(segs[0x3000]) <= 0xD000, "program overlaps the client at D000h"
        return build_lmf(segs, 0x3000, block=240)

    def serve_nio(self, nio):
        """Answer FujiBus requests from the 4P's serial port with the fake NIO."""
        fd = os.open(self.mame.pty, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(fd)
        stop = threading.Event()
        t = threading.Thread(target=serve, args=(fd, nio, stop), daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(2), os.close(fd)))

    def test_hello_from_c_runs_under_ls_dos(self):
        self.boot({"HELLO/CMD": self.build("hello")})
        self.mame.type("HELLO\n")
        self.mame.wait_for("hello from C", 30)
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_console_and_widgets_work_under_ls_dos(self):
        self.boot({"UIDEMO/CMD": self.build("uidemo")})
        self.mame.type("UIDEMO\n")
        self.mame.wait_for("[*Browse*]", 30)
        self.mame.wait_for("> item 000", 10)
        self.mame.press("Left Shift+Down")                       # page: selection moves height-1 = 17
        self.mame.wait_for("> item 017", 10)
        self.mame.press("Down")
        self.mame.wait_for("> item 018", 10)
        self.mame.type("aHi there\n")                          # text field: 'a' opens it, ENTER accepts
        self.mame.wait_for("Hi there", 10)
        self.mame.press("Break")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_portable_fnsvc_lists_a_directory_through_the_fake_nio(self):
        nio = FakeNio()
        nio.dirs["sd0:/"] = ["-  720 Nov 16 09:00 Game.img", "d    0 Nov 16 09:00 utils/"]
        self.boot({"NIOSELF/CMD": self.build("nio_selftest", with_client=True)})
        self.serve_nio(nio)
        self.mame.type("NIOSELF\n")
        self.mame.wait_for("OK", 60)
        screen = self.mame.screen()
        self.assertIn("D utils", screen)
        self.assertIn("F Game.img", screen)

    def test_portable_store_round_trips_hosts_mappings_and_a_slot(self):
        nio = FakeNio()
        self.boot({"STORE/CMD": self.build("store_selftest", with_client=True)})
        self.serve_nio(nio)
        self.mame.type("STORE\n")
        self.mame.wait_for("slot0=", 90)
        screen = self.mame.screen()
        for expect in ("save_hosts=ok", "save_maps=ok", "write_slot=ok", "load=ok", "host0=sd0:/",
                       "host1=tnfs://example.org/trs80", "map1=121", "read_slot=ok", "slot0=host:/disks/work.dsk"):
            self.assertIn(expect, screen)
        self.assertEqual(nio.catalog[0][1], "host:/disks/work.dsk")
        self.assertIn(("config-nio", "hosts"), nio.appstore)

    def test_unanswered_request_returns_to_ls_dos_with_an_error(self):
        self.boot({"NIOSELF/CMD": self.build("nio_selftest", with_client=True)})   # nobody answers on the line
        self.mame.type("NIOSELF\n")
        self.mame.wait_for("E3", 120)                                 # FNSVC_ERR_TRANSPORT
        self.mame.wait_for("LS-DOS Ready", 60)


if __name__ == "__main__":
    unittest.main()
