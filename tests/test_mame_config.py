# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
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

    def nio_with_folder(self, count=30):
        nio = FakeNio()
        nio.dirs["sd0:/"] = ["d    0 Nov 16 09:00 utils/"] + \
            ["-  720 Nov 16 09:00 Game%02d.img" % i for i in range(count)]
        for i in range(count):
            nio.library["sd0:/Game%02d.img" % i] = bytes(720 * 256)
        nio.library["sd0:/utils/Tool.img"] = bytes(720 * 256)
        nio.dirs["sd0:/utils/"] = ["-  720 Nov 16 09:00 Tool.img"]
        return nio

    def start_config(self, nio):
        self.boot({"CONFIG/CMD": self.build("config", with_client=True)})
        self.serve_nio(nio)
        nio.appstore[("config-nio", "hosts")] = b"sd0:/\n"
        self.mame.type("CONFIG\n")
        self.mame.wait_for("[*Browse*]", 90)

    def test_config_browses_pages_and_mounts_and_ejects(self):
        nio = self.nio_with_folder()
        self.start_config(nio)
        self.mame.wait_for("utils/", 30)
        self.mame.wait_for("1/31", 10)
        self.mame.press("Left Shift+Down")                          # a page down moves 11 rows: end of page 1
        self.mame.wait_for("12/31", 10)
        self.mame.press("Left Shift+Down")                          # next page (entries 12..23)
        self.mame.wait_for("23/31", 30)
        self.mame.wait_for("Game11.img", 30)
        self.mame.press("Left Shift+Down")
        self.mame.wait_for("31/31", 30)                             # clamps at the last entry
        self.mame.wait_for("Game29.img", 30)
        self.mame.wait_for("31/31", 10)
        self.mame.type("\n")                                       # ENTER on a file mounts it on the selected drive (:2: :0 is the boot disk, :1 may be a floppy)
        self.mame.wait_for("Mounted Game29.img on :2", 30)
        self.assertEqual(nio.uris[3][0], "sd0:/Game29.img")
        self.assertEqual(nio.catalog[2][1], "sd0:/Game29.img")      # catalogue entries follow the drive number
        self.assertNotIn(1, nio.uris)                               # nothing touched :0
        self.assertNotIn(2, nio.uris)                               # nor :1
        self.mame.wait_for(":2 Game29.img", 10)
        self.mame.wait_for(":0 (boot disk)", 10)
        self.mame.press("Right")                                    # (Right = TAB): focus the drives pane
        self.mame.wait_for("[drives]", 10)
        self.mame.press("Down")
        self.mame.wait_for("> :3", 10)
        self.mame.press("Right")                                    # back to the files; ENTER now mounts on :3
        self.mame.wait_for("[files]", 10)
        self.mame.type("\n")
        self.mame.wait_for("Mounted Game29.img on :3", 30)
        self.assertEqual(nio.uris[4][0], "sd0:/Game29.img")
        self.mame.press("Right")
        self.mame.wait_for("[drives]", 10)
        self.mame.type("x")                                         # eject drive :3
        self.mame.wait_for("Ejected", 30)
        self.assertNotIn(4, nio.uris)
        self.assertNotIn(3, nio.catalog)
        self.mame.wait_for(":3 (empty)", 10)
        time.sleep(1)
        self.mame.type("x")                                         # :3 is empty now
        self.mame.wait_for("Nothing to eject", 30)
        self.mame.press("↑")
        self.mame.wait_for("> :2", 10)
        self.mame.press("↑")
        self.mame.wait_for("> :1", 10)
        self.mame.press("↑")
        self.mame.wait_for("> :0", 10)
        self.mame.type("x")                                         # the boot disk is never ejected from CONFIG
        self.mame.wait_for("is the boot disk", 10)
        self.mame.press("Down")
        self.mame.wait_for("> :1", 10)
        self.mame.press("Down")
        self.mame.wait_for("> :2", 10)
        self.mame.type("x")
        self.mame.wait_for("Ejected", 30)
        self.assertNotIn(3, nio.uris)
        self.assertNotIn(2, nio.catalog)
        self.mame.type("q")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_config_enters_and_leaves_a_folder_and_works_without_listpages(self):
        nio = self.nio_with_folder(count=5)
        nio.list_pages = False                                      # older firmware: first entries only
        self.start_config(nio)
        self.mame.wait_for("utils/", 30)
        self.mame.type("\n")                                       # ENTER on utils/ (directories come first)
        self.mame.wait_for("Tool.img", 30)
        self.mame.press("Left")                                     # Left = up one folder
        self.mame.wait_for("Game04.img", 30)
        self.mame.press("Break")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_config_hosts_add_delete_and_browse(self):
        nio = self.nio_with_folder(count=3)
        nio.dirs["tnfs://pi/"] = ["-  720 Nov 16 09:00 Pi.img"]
        self.start_config(nio)
        self.mame.type("h")
        self.mame.wait_for("A add", 10)
        self.mame.wait_for("sd0:/", 10)
        self.mame.type("a")
        self.mame.wait_for("New host URI", 10)
        self.mame.type("tnfs://pi/\n")
        self.mame.wait_for("Saved", 30)
        self.assertEqual(nio.appstore[("config-nio", "hosts")], b"sd0:/\ntnfs://pi/\n")
        self.mame.press("Down")
        self.mame.wait_for("> tnfs://pi/", 10)
        self.mame.type("\n")                                       # ENTER browses the selected host
        self.mame.wait_for("Pi.img", 30)
        self.mame.type("h")
        self.mame.wait_for("A add", 10)
        self.mame.type("d")                                         # deletes the selected (second) host
        self.mame.wait_for("Deleted", 30)
        self.assertEqual(nio.appstore[("config-nio", "hosts")], b"sd0:/\n")
        self.mame.press("Break")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_config_setup_wifi_scan_join_and_prefs(self):
        nio = self.nio_with_folder(count=1)
        nio.wifi_networks = [("HomeNet", -40, 3), ("CafeOpen", -70, 0)]
        self.start_config(nio)
        self.mame.type("w")
        self.mame.wait_for("press N to scan", 10)
        self.mame.wait_for("not connected", 10)
        self.mame.type("n")
        self.mame.wait_for("HomeNet", 30)
        self.mame.wait_for("CafeOpen", 10)
        self.mame.type("\n")                                       # join the selected network
        self.mame.wait_for("Password", 10)
        self.mame.type("secret1\n")
        self.mame.wait_for("Connected", 60)
        self.assertEqual(nio.wifi_joined, ("HomeNet", "secret1"))
        self.mame.wait_for("connected 192.168.1.50", 10)
        self.mame.type("d")
        self.mame.wait_for("Date order: YDM", 30)
        self.assertIn(b"ydm", nio.appstore[("config-nio", "prefs")])
        self.mame.press("Break")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_config_walks_every_tab_and_slots_shows_the_mounted_image(self):
        nio = self.nio_with_folder(count=3)
        self.start_config(nio)
        self.mame.wait_for("Game02.img", 30)
        self.mame.type("\n")                                       # directories first: ENTER on utils/ opens it
        self.mame.wait_for("Tool.img", 30)
        self.mame.type("\n")                                       # mount Tool.img on :2
        self.mame.wait_for("Mounted Tool.img on :2", 30)
        for key, text in (("s", "sd0:/utils/Tool.img"), ("h", "A add"), ("w", "PREFERENCES"), ("s", ":3 (empty)"), ("b", "[files]")):
            self.mame.type(key)
            self.mame.wait_for(text, 15)
        for _ in range(3):                                          # SHIFT+Right across the tabs and back
            self.mame.press("Left Shift+Right")
            time.sleep(1.5)
        self.mame.type("s")
        self.mame.wait_for("sd0:/utils/Tool.img", 15)
        self.mame.type("q")
        self.mame.wait_for("LS-DOS Ready", 30)

    def test_unanswered_request_returns_to_ls_dos_with_an_error(self):
        self.boot({"NIOSELF/CMD": self.build("nio_selftest", with_client=True)})   # nobody answers on the line
        self.mame.type("NIOSELF\n")
        self.mame.wait_for("E3", 120)                                 # FNSVC_ERR_TRANSPORT
        self.mame.wait_for("LS-DOS Ready", 60)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE and shutil.which("zcc"), "set MAME_TESTS=1 and install mame, sjasmplus, z88dk, the LS-DOS image and the 4P ROMs")
class ConfigAutostartTests(unittest.TestCase):
    """nioboot-config.hex (nioboot with AUTO_CMD="CONFIG") boots the 4P straight into CONFIG, like an AUTOEXEC."""

    def boot(self, loader):
        from tools.make_boot_image import BASIC_DROP, CONFIG_BIN_DEFAULT
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(["make", "-C", TRS80, "build/config.bin"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["make", "-C", root, "all"], check=True, stdout=subprocess.DEVNULL)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        disk = os.path.join(tmp, "boot.dmk")
        make_boot_image(BASE, disk, drop=DROP + BASIC_DROP, config_bin=CONFIG_BIN_DEFAULT)
        with open(disk, "rb") as f:
            flat = lsdosfs.flat_image(dmk.parse_dmk(f.read()))
        self.nio = FakeNio()
        self.nio.mount(1, flat)
        self.nio.clock = (2027, 11, 23, 14, 37, 45)
        self.nio.appstore[("config-nio", "hosts")] = b"sd0:/\n"
        self.nio.dirs["sd0:/"] = ["-  720 Nov 16 09:00 Game.img"]
        self.nio.library["sd0:/Game.img"] = bytes(720 * 256)
        self.mame = Mame4P(ROMS, None, mode="serial")
        pty = self.mame.start()
        self.addCleanup(self.mame.stop)
        self.mame.wait_for("Ready", 120)
        time.sleep(1)
        r = subprocess.run(["python3", os.path.join(root, "trs80boot.py"), os.path.join(root, "build", loader),
                            "-p", pty, "--entry", "0x5000", "-y"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.mame.release_shift()
        fd = os.open(pty, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(fd)
        stop = threading.Event()
        t = threading.Thread(target=serve, args=(fd, self.nio, stop), daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(2), os.close(fd)))

    def test_config_starts_by_itself_and_quits_to_ls_dos(self):
        self.boot("nioboot-config.hex")
        self.mame.wait_for("[*Browse*]", 240)
        self.mame.wait_for("Game.img", 30)
        time.sleep(3)
        self.mame.type("q")
        self.mame.wait_for("LS-DOS Ready", 60)

    def test_quitting_after_a_mount_installs_the_driver_on_that_drive(self):
        self.boot("nioboot-config.hex")
        self.mame.wait_for("[*Browse*]", 240)
        self.mame.wait_for("Game.img", 30)
        time.sleep(3)
        self.assertEqual(self.mame.peek(0x0470 + 20, 1), b"\xc9")            # :2 starts disabled (nioboot)
        self.mame.type("\n")                                                 # ENTER mounts Game.img on :2
        self.mame.wait_for("FUJIDRV runs when you quit", 30)
        self.mame.type("q")
        self.mame.wait_for("FujiNet driver installed on :2", 60)
        self.mame.wait_for("LS-DOS Ready", 30)
        self.assertEqual(self.mame.peek(0x0470 + 20, 1), b"\xc3")            # enabled, pointing at the driver
        self.assertEqual(self.nio.uris[3][0], "sd0:/Game.img")

    def test_quitting_with_nothing_mounted_runs_no_installer(self):
        self.boot("nioboot-config.hex")
        self.mame.wait_for("[*Browse*]", 240)
        time.sleep(3)
        self.mame.type("q")
        self.mame.wait_for("LS-DOS Ready", 60)
        self.assertNotIn("driver installed", self.mame.screen())

    def test_the_plain_loader_still_stops_at_ls_dos_ready(self):
        self.boot("nioboot.hex")
        s = self.mame.wait_for("LS-DOS Ready", 240)
        time.sleep(5)
        self.assertNotIn("CONFIG NIO", self.mame.screen())
