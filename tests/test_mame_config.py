"""CONFIG/CMD (nio-config's trs80/ C program, built with z88dk) on MAME's Model 4P.

Opt-in like test_mame_integration:  MAME_TESTS=1 python3 -m unittest tests.test_mame_config
Needs z88dk and the nio-config checkout (NIO_CONFIG_DIR, default ../fujinet-nio-workspace/repos/nio-config).
"""
import os, shutil, subprocess, tempfile, time, unittest

from tests.test_mame_integration import BASE, ROMS, HAVE
from tools.make_boot_image import make_boot_image
from tools.mame4p import Mame4P
from tools.zcc_cmd import bin_to_lmf
from trs80 import dmk, lsdosfs

NIO_CONFIG = os.environ.get("NIO_CONFIG_DIR", os.path.expanduser("~/dev/fujinet-nio-workspace/repos/nio-config"))
TRS80 = os.path.join(NIO_CONFIG, "trs80")


@unittest.skipUnless(HAVE and shutil.which("zcc"), "set MAME_TESTS=1 and install mame, sjasmplus, z88dk, the LS-DOS image and the 4P ROMs")
class ConfigOnMameTests(unittest.TestCase):
    def boot(self, extra):
        """Boots LS-DOS from a scratch image that also holds {name: /CMD bytes}."""
        subprocess.run(["make", "-C", os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "all"], check=True, stdout=subprocess.DEVNULL)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        disk = os.path.join(tmp, "boot.dmk")
        make_boot_image(BASE, disk)
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

    def build(self, name):
        subprocess.run(["make", "-C", TRS80, "build/%s.bin" % name], check=True, stdout=subprocess.DEVNULL)
        return bin_to_lmf(os.path.join(TRS80, "build", name + ".bin"))

    def test_hello_from_c_runs_under_ls_dos(self):
        self.boot({"HELLO/CMD": self.build("hello")})
        self.mame.type("HELLO\n")
        self.mame.wait_for("hello from C", 30)
        self.mame.wait_for("LS-DOS Ready", 30)


if __name__ == "__main__":
    unittest.main()
