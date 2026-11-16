"""Real LS-DOS 6.3.1 on MAME's Model 4P (real boot ROM, emulated WD FDC and TR1865 UART), driven over a pty.

Opt-in because each test boots the machine (about a minute):  MAME_TESTS=1 python3 -m unittest tests.test_mame_integration
Needs `mame`, images/lsdos631l-upstream/L631NEW.DSK and the 4P ROMs in images/roms/trs80m4p/ (see tools/mame4p.py).
"""
import os, re, select, shutil, subprocess, tempfile, threading, time, tty, unittest

from fujinet import fujibus as fb
from tests.fakenio import FakeNio
from trs80 import dmk, lsdosfs
from tools.make_boot_image import make_boot_image
from tools.mame4p import Mame4P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "images", "lsdos631l-upstream", "L631NEW.DSK")
ROMS = os.path.join(ROOT, "images", "roms")
HAVE = (os.environ.get("MAME_TESTS") and shutil.which("mame") and shutil.which("sjasmplus") and os.path.exists(BASE)
        and os.path.exists(os.path.join(ROMS, "trs80m4p", "trs80m4p_loader_hack.rom")))


def serve(fd, nio, stop):
    """Answer FujiBus requests arriving on the pty with the fake NIO until `stop` is set."""
    dec = fb.SlipDecoder()
    while not stop.is_set():
        if select.select([fd], [], [], 0.1)[0]:
            for frame in dec.feed(os.read(fd, 4096)):
                os.write(fd, nio.handle(frame))


@unittest.skipUnless(HAVE, "set MAME_TESTS=1 and install mame, sjasmplus, the LS-DOS image and the 4P ROMs")
class LsDosOnMameTests(unittest.TestCase):
    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.disk = os.path.join(self.tmp, "boot.dmk")
        make_boot_image(BASE, self.disk)
        self.mame = Mame4P(ROMS, self.disk)
        self.mame.start()
        self.addCleanup(self.mame.stop)
        self.mame.wait_for("Date MM/DD/YY", 120)
        self.mame.type("01/02/26\n")
        self.mame.wait_for("Time HH:MM:SS", 30)
        self.mame.type("\n")
        self.mame.wait_for("LS-DOS Ready", 30)
        time.sleep(1)

    def at_prompt(self):
        """True when the last non-blank screen line is the LS-DOS prompt (a long listing scrolls older prompts away)."""
        lines = [l.strip().rstrip("_").strip() for l in self.mame.screen().splitlines() if l.strip().rstrip("_").strip()]
        return bool(lines) and lines[-1] == "LS-DOS Ready"

    def command(self, line, expect, timeout=60):
        self.mame.type(line + "\n")
        time.sleep(3)                                  # let the command start (the prompt line is replaced by the echo)
        end = time.time() + timeout
        while time.time() < end:
            if self.at_prompt():
                break
            time.sleep(0.5)
        else:
            self.fail(f"{line!r} never returned to LS-DOS Ready; screen:\n{self.mame.screen()}")
        s = self.mame.screen()
        self.assertIn(expect, s, line)
        return s

    def test_serial_link_receives_a_file_that_ls_dos_can_read(self):
        path = os.path.join(self.tmp, "hello.txt")
        with open(path, "wb") as f:
            f.write(b"Hello from the PC.\r")
        self.mame.type("SERIAL\n")
        self.mame.wait_for("Serial link ready", 30)
        r = subprocess.run(["python3", os.path.join(ROOT, "trs80put.py"), "-p", self.mame.pty, path, "--as", "HELLO/TXT", "--exit"],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        time.sleep(3)
        self.command("LIST HELLO/TXT", "Hello from the PC.")

    def test_fujinet_commands_work_under_ls_dos(self):
        nio = FakeNio()
        nio.dirs["sd0:/"] = ["-  720 Nov 16 09:00 Game.img"]
        nio.library["sd0:/Game.img"] = bytes(720 * 256)
        fd = os.open(self.mame.pty, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(fd)
        stop = threading.Event()
        t = threading.Thread(target=serve, args=(fd, nio, stop), daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(2), os.close(fd)))
        self.command("FLS", "Game.img")
        self.command("FMOUNT :1 sd0:/Game.img ss=256", "Mounted :1 (720 sectors)")   # mixed case must arrive intact
        self.assertEqual(nio.uris[2][0], "sd0:/Game.img")
        self.command("FDRIVE", "1: AUTO sd0:/Game.img")
        self.command("FUMOUNT :1", "Unmounted :1")
        self.assertNotIn(2, nio.slots)

    def test_driver_serves_a_drive_from_a_fujinet_image(self):
        with open(BASE, "rb") as f:
            flat = lsdosfs.flat_image(dmk.parse_dmk(f.read()))
        nio = FakeNio()
        nio.library["sd0:/Sys.img"] = flat
        fd = os.open(self.mame.pty, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(fd)
        stop = threading.Event()
        t = threading.Thread(target=serve, args=(fd, nio, stop), daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(2), os.close(fd)))
        self.command("FUJIDRV :2", "FujiNet driver installed on :2")
        self.command("FMOUNT :2 sd0:/Sys.img ss=256", "Mounted :2 (720 sectors)")
        self.mame.type("DIR :2\n")
        self.mame.wait_for("TED/CMD", 300)             # a full screen: LS-DOS pauses until a key is pressed
        self.mame.type("\n")
        time.sleep(3)
        end = time.time() + 60
        while not self.at_prompt() and time.time() < end:
            time.sleep(0.5)
        s = self.mame.screen()
        self.assertTrue(self.at_prompt(), s)
        self.assertIn("COMM/CMD", s)
        self.assertGreater(len([r for r in nio.requests if r.command == 3]), 3)     # sectors really came from the FujiNet


@unittest.skipUnless(HAVE, "set MAME_TESTS=1 and install mame, sjasmplus, the LS-DOS image and the 4P ROMs")
class FloppylessBootTests(unittest.TestCase):
    """The 4P with NO disk media: the ROM serial loader runs nioboot, which boots LS-DOS from a FujiNet image."""

    clock = None                                              # what the fake FujiNet's clock device reports

    def setUp(self):
        subprocess.run(["make", "-B", "-C", ROOT], check=True, stdout=subprocess.DEVNULL)
        with open(BASE, "rb") as f:
            flat = lsdosfs.flat_image(dmk.parse_dmk(f.read()))
        self.nio = FakeNio()
        self.nio.mount(1, flat)
        self.nio.clock = self.clock
        self.mame = Mame4P(ROMS, None, mode="serial")
        pty = self.mame.start()
        self.addCleanup(self.mame.stop)
        self.mame.wait_for("Ready", 120)                      # the ROM serial loader is waiting
        time.sleep(1)
        r = subprocess.run(["python3", os.path.join(ROOT, "trs80boot.py"), os.path.join(ROOT, "build", "nioboot.hex"),
                            "-p", pty, "--entry", "0x5000", "-y"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.mame.release_shift()                              # like letting go of the key once 'Ready' has appeared
        self.fd = os.open(pty, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(self.fd)
        self.stop = threading.Event()
        t = threading.Thread(target=serve, args=(self.fd, self.nio, self.stop), daemon=True)
        t.start()
        self.addCleanup(lambda: (self.stop.set(), t.join(2), os.close(self.fd)))

    def test_boots_ls_dos_to_the_date_prompt_without_any_disk(self):
        s = self.mame.wait_for("Date MM/DD/YY", 180)
        self.assertIn("LS-DOS 06.03.01", s)
        self.assertGreater(len([r for r in self.nio.requests if r.command == 3]), 20)    # sectors came from the FujiNet
        self.mame.type("01/02/26\n")
        self.mame.wait_for("Time HH:MM:SS", 30)
        self.mame.type("\n")
        self.mame.wait_for("LS-DOS Ready", 60)
        before = len(self.nio.requests)
        time.sleep(1)
        self.mame.type("DIR :0\n")
        end = time.time() + 240
        while time.time() < end and "FORMAT/CMD" not in self.mame.screen() and "SYS0/SYS" not in self.mame.screen():
            time.sleep(1)
        screen = self.mame.screen()
        self.assertIn("L631NEW", screen)                                                  # the volume name of the image we served
        self.assertGreater(len(self.nio.requests), before)                                # DIR read through the driver
        high = self.mame.peek(0x040E, 2)                                                  # HIGH$ (LS-DOS 6.3.1 keeps it here)
        self.assertEqual(high[0] | high[1] << 8, 0xDFFF)                                  # just below the driver at E000h


@unittest.skipUnless(HAVE, "set MAME_TESTS=1 and install mame, sjasmplus, the LS-DOS image and the 4P ROMs")
class FloppylessBootWithClockTests(FloppylessBootTests):
    """Same boot, but the FujiNet has a clock: LS-DOS must not ask for the date and time."""
    clock = (2027, 11, 23, 14, 37, 45)

    def test_boots_ls_dos_to_the_date_prompt_without_any_disk(self):
        self.skipTest("the date prompt is what the no-clock class checks")

    def test_boots_straight_to_ready_with_the_date_from_the_fujinet(self):
        s = self.mame.wait_for("LS-DOS Ready", 180)
        self.assertNotIn("Date MM/DD/YY", s)
        self.assertNotIn("Time HH:MM:SS", s)
        self.assertIn("Nov 23, 2027", s)
        time.sleep(2)
        self.mame.type("TIME\n")
        end = time.time() + 60
        while time.time() < end and not re.search(r"14:3[78]:\d\d", self.mame.screen()):
            time.sleep(1)
        self.assertRegex(self.mame.screen(), r"14:3[78]:\d\d")                # the time from the FujiNet, ticking on


if __name__ == "__main__":
    unittest.main()
