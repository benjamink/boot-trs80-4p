"""Real LS-DOS 6.3.1 on MAME's Model 4P (real boot ROM, emulated WD FDC and TR1865 UART), driven over a pty.

Opt-in because each test boots the machine (about a minute):  MAME_TESTS=1 python3 -m unittest tests.test_mame_integration
Needs `mame`, images/lsdos631l-upstream/L631NEW.DSK and the 4P ROMs in images/roms/trs80m4p/ (see tools/mame4p.py).
"""
import os, select, shutil, subprocess, tempfile, threading, time, tty, unittest

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


if __name__ == "__main__":
    unittest.main()
