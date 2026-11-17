#!/usr/bin/env python3
"""Show CONFIG (nio-config for the 4P) in the MAME emulator window, against the fake fujinet-nio.

  NIO_WORKSPACE=... tools/demo_config.py [--seconds 3600]

Builds the boot image with CONFIG/CMD, boots LS-DOS in a MAME window, answers the 4P's serial port with
tests/fakenio.py (a few disk images, a Wi-Fi network, a TNFS host) and types CONFIG for you. Close the window
or press Ctrl-C to stop. Nothing is mounted for real: the fake only records what CONFIG asks for.
"""
import argparse, os, select, subprocess, sys, tempfile, threading, time, tty

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.fakenio import FakeNio  # noqa: E402
from tests.test_mame_integration import BASE, ROMS, serve  # noqa: E402
from tools.make_boot_image import BASIC_DROP, CONFIG_BIN_DEFAULT, DROP, make_boot_image  # noqa: E402
from tools.mame4p import Mame4P  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=3600)
    ap.add_argument("--config-bin", default=CONFIG_BIN_DEFAULT)
    a = ap.parse_args()
    subprocess.run(["make", "-C", ROOT, "all"], check=True, stdout=subprocess.DEVNULL)
    disk = os.path.join(tempfile.mkdtemp(prefix="demo-config-"), "boot.dmk")
    make_boot_image(BASE, disk, drop=DROP + BASIC_DROP, config_bin=a.config_bin)

    nio = FakeNio()
    nio.dirs["sd0:/"] = ["d    0 Nov 16 09:00 games/", "d    0 Nov 16 09:00 utils/"] + \
        ["-  720 Nov 16 09:00 Disk%02d.dsk" % i for i in range(1, 31)]
    nio.dirs["sd0:/games/"] = ["-  720 Nov 16 09:00 Adventure.dsk", "-  720 Nov 16 09:00 Scarfman.dsk"]
    nio.dirs["sd0:/utils/"] = ["-  720 Nov 16 09:00 Tools.dsk"]
    nio.dirs["tnfs://pi/"] = ["-  720 Nov 16 09:00 FromThePi.dsk"]
    for uri in [u for d, lines in nio.dirs.items() for u in [d + l.split()[-1] for l in lines if l[0] == "-"]]:
        nio.library[uri] = bytes(720 * 256)
    nio.appstore[("config-nio", "hosts")] = b"sd0:/\ntnfs://pi/\n"
    nio.wifi_networks = [("HomeNet", -42, 3), ("CoffeeShop", -68, 0), ("Neighbour", -80, 3)]

    mame = Mame4P(ROMS, disk, seconds=a.seconds, window=True)
    pty = mame.start()
    fd = os.open(pty, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    stop = threading.Event()
    threading.Thread(target=serve, args=(fd, nio, stop), daemon=True).start()
    try:
        mame.wait_for("Date MM/DD/YY", 120)
        mame.type("01/02/26\n")
        mame.wait_for("Time HH:MM:SS", 30)
        mame.type("\n")
        mame.wait_for("LS-DOS Ready", 30)
        time.sleep(1)
        mame.type("CONFIG\n")
        print("CONFIG is running in the MAME window. Keys: SHIFT+Left/Right tabs, Up/Down, ENTER, Right = TAB, BREAK quits.")
        mame.proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        mame.stop()


if __name__ == "__main__":
    main()
