"""Real LS-DOS 6.3.1 on MAME's Model 4P (real boot ROM, emulated WD FDC and TR1865 UART), driven over a pty.

Opt-in because each test boots the machine (about a minute):  MAME_TESTS=1 python3 -m unittest tests.test_mame_integration
Needs `mame`, images/lsdos631l-upstream/L631NEW.DSK and the 4P ROMs in images/roms/trs80m4p/ (see tools/mame4p.py).
"""
import os, select, shutil, subprocess, tempfile, threading, time, tty, unittest

from fujinet import fujibus as fb
from tests.fakenio import FakeNio
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

    def command(self, line, expect, timeout=60):
        before = self.mame.screen().count("LS-DOS Ready")
        self.mame.type(line + "\n")
        end = time.time() + timeout
        while time.time() < end:
            s = self.mame.screen()
            if s.count("LS-DOS Ready") > before:
                break
            time.sleep(0.5)
        else:
            self.fail(f"{line!r} never returned to LS-DOS Ready; screen:\n{self.mame.screen()}")
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


if __name__ == "__main__":
    unittest.main()
