"""The LS-DOS command programs (FMOUNT, FUMOUNT, FDRIVE) in the Z80 interpreter: command line in HL, text out through
@DSPLY (FakeDos), the FujiNet on the other end of a simulated UART (FakeNio)."""
import os, re, shutil, subprocess, unittest

from tests.fakedos import FakeDos, DosExit
from tests.fakenio import FakeNio
from tests.z80emu import Z80, load_hex
from fujinet import fujibus as fb
from fujinet import niodisk as nd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class CliTests(unittest.TestCase):
    PROGRAM = None

    def run_cli(self, line, nio=None):
        """Runs PROGRAM with the command line `line`; returns (return code, text shown, nio)."""
        subprocess.run(["make", "-B", "-C", ROOT, "build/%s.hex" % self.PROGRAM], check=True, stdout=subprocess.DEVNULL)
        cpu = Z80()
        load_hex(cpu, os.path.join(ROOT, "build", self.PROGRAM + ".hex"))
        with open(os.path.join(ROOT, "build", self.PROGRAM + ".sym")) as f:
            sym = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", f.read(), re.M)}
        cpu.mem[sym["recv_packet"] + 1] = 1                       # one short wait instead of four seconds
        self.nio = nio or FakeNio()
        dec, rx, self.uart = fb.SlipDecoder(), [], []

        def io_in(port):
            if port == 0xEA:
                return 0x80 if rx else 0
            return rx.pop(0) if port == 0xEB else 0xFF

        def io_out(port, val):
            self.uart.append((port, val))
            if port == 0xEB:
                for frame in dec.feed(bytes([val])):
                    rx.extend(self.nio.handle(frame))
        cpu.io_in, cpu.io_out = io_in, io_out
        dos = FakeDos(cpu)
        buf = 0x4800                                             # where LS-DOS keeps the command line
        line = line.split(" ", 1)[1] if " " in line else ""      # LS-DOS passes what follows the program name
        cpu.mem[buf:buf + len(line) + 1] = line.encode() + b"\r"
        cpu.set_rp(4, 5, buf)
        cpu.sp = 0x7000
        cpu.pc = 0x3000
        rc = None
        try:
            for _ in range(80_000_000):
                cpu.step()
        except DosExit:
            rc = cpu.hl()
        self.dos = dos
        return rc, "\n".join(dos.messages), self.nio


class FmountTests(CliTests):
    PROGRAM = "fmount"

    def nio_with(self, uri="host:/a.img", sectors=100):
        n = FakeNio()
        n.library[uri] = bytes(sectors * 256)
        return n

    def test_mounts_the_image_on_the_drive_and_says_so(self):
        rc, text, nio = self.run_cli("FMOUNT :2 host:/a.img", self.nio_with())
        self.assertEqual(rc, 0)
        self.assertIn(2 + 1, nio.slots)                                # drive :2 is NIO slot 3
        self.assertEqual(bytes(nio.requests[-1].payload), nd.mount_request(3, "host:/a.img"))
        self.assertIn("Mounted :2", text)
        self.assertIn("100 sectors", text)

    def test_options_read_only_and_sector_size(self):
        rc, _, nio = self.run_cli("FMOUNT :0 host:/a.img ro ss=256", self.nio_with())
        self.assertEqual(rc, 0)
        self.assertEqual(bytes(nio.requests[-1].payload), nd.mount_request(1, "host:/a.img", readonly=True, sector_size_hint=256))

    def test_uri_keeps_its_case(self):
        n = self.nio_with("tnfs://Host/Disks/Game.DSK")
        rc, _, nio = self.run_cli("FMOUNT :0 tnfs://Host/Disks/Game.DSK", n)
        self.assertEqual(rc, 0)

    def test_a_missing_image_is_reported_in_words(self):
        rc, text, nio = self.run_cli("FMOUNT :0 host:/nope.img")
        self.assertEqual(rc, 2)
        self.assertIn("not found", text.lower())

    def test_no_answer_from_the_fujinet(self):
        n = self.nio_with()
        n.mangle = [lambda w: b""] * 4
        rc, text, _ = self.run_cli("FMOUNT :0 host:/a.img", n)
        self.assertEqual(rc, 2)
        self.assertIn("no valid answer", text.lower())

    def test_usage_on_bad_arguments(self):
        for line in ("FMOUNT", "FMOUNT :9 host:/a.img", "FMOUNT :0", "FMOUNT :0 host:/a.img bogus", "FMOUNT :0 host:/a.img ss=100"):
            rc, text, nio = self.run_cli(line, self.nio_with())
            self.assertEqual(rc, 1, line)
            self.assertIn("Usage: FMOUNT", text, line)
            self.assertEqual(nio.requests, [], line)

    def test_warns_when_the_sector_size_is_not_256(self):
        class Wide(FakeNio):
            pass
        n = self.nio_with()
        orig = n._disk
        def disk(p):
            st, pl = orig(p)
            if p.command == nd.MOUNT and st == 0:
                pl = pl[:6] + (512).to_bytes(2, "little") + pl[8:]
            return st, pl
        n._disk = disk
        rc, text, _ = self.run_cli("FMOUNT :0 host:/a.img", n)
        self.assertIn("not 256", text)


class FumountTests(CliTests):
    PROGRAM = "fumount"

    def test_unmounts(self):
        n = FakeNio(); n.mount(2, bytes(256))
        rc, text, nio = self.run_cli("FUMOUNT :1", n)
        self.assertEqual(rc, 0)
        self.assertNotIn(2, nio.slots)
        self.assertIn("Unmounted :1", text)

    def test_nothing_mounted_there(self):
        rc, text, _ = self.run_cli("FUMOUNT :1")
        self.assertEqual(rc, 2)
        self.assertIn("nothing mounted", text.lower())

    def test_usage(self):
        for line in ("FUMOUNT", "FUMOUNT :8", "FUMOUNT :1 extra"):
            rc, text, nio = self.run_cli(line)
            self.assertEqual((rc, nio.requests), (1, []), line)
            self.assertIn("Usage: FUMOUNT", text)


class FdriveTests(CliTests):
    PROGRAM = "fdrive"

    def test_lists_each_mount_on_its_own_line(self):
        n = FakeNio()
        for slot in (1, 3):
            n.library["host:/d%d.img" % slot] = bytes(256)
            n.mount(slot, bytes(256)); n.uris[slot] = ("host:/d%d.img" % slot, slot == 3)
        rc, text, _ = self.run_cli("FDRIVE", n)
        self.assertEqual(rc, 0)
        self.assertEqual(self.dos.messages, ["0: AUTO host:/d1.img", "2: RO host:/d3.img"])

    def test_says_so_when_nothing_is_mounted(self):
        rc, text, _ = self.run_cli("FDRIVE")
        self.assertEqual(rc, 1)
        self.assertIn("No FujiNet images", text)

    def test_follows_the_more_flag(self):
        n = FakeNio()
        for slot in range(1, 9):
            u = "host:/a-rather-long-directory-name/image-number-%d.img" % slot
            n.library[u] = bytes(256); n.mount(slot, bytes(256)); n.uris[slot] = (u, False)
        rc, _, _ = self.run_cli("FDRIVE", n)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.dos.messages), 8)
        self.assertTrue(self.dos.messages[7].startswith("7: AUTO"))
        self.assertGreater(len([r for r in n.requests if r.command == nd.LIST_MOUNTS]), 1)


class FlsTests(CliTests):
    PROGRAM = "fls"

    def test_lists_the_directory_and_counts_the_entries(self):
        n = FakeNio()
        n.dirs["sd0:/"] = ["d     - Nov 16 09:00 games/", "-   720 Nov 16 09:00 ls631.img"]
        rc, _, nio = self.run_cli("FLS", n)
        self.assertEqual(rc, 0)
        self.assertEqual(self.dos.messages, ["d     - Nov 16 09:00 games/", "-   720 Nov 16 09:00 ls631.img", "2 entries"])
        self.assertEqual(bytes(nio.requests[-1].payload), nd.list_directory_request("sd0:/"))

    def test_lists_the_given_location_with_its_case(self):
        n = FakeNio()
        n.dirs["tnfs://Server/Disks"] = ["-  1 Nov 16 09:00 A.DSK"]
        rc, text, _ = self.run_cli("FLS tnfs://Server/Disks", n)
        self.assertEqual(rc, 0)
        self.assertIn("A.DSK", text)
        self.assertIn("1 entry", text)
        self.assertNotIn("entries", text)

    def test_long_listing_is_fetched_in_pages(self):
        n = FakeNio()
        n.dirs["sd0:/"] = ["-  %d Nov 16 09:00 a-fairly-long-file-name-%d.dsk" % (i, i) for i in range(30)]
        rc, _, nio = self.run_cli("FLS", n)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.dos.messages), 31)
        self.assertEqual(self.dos.messages[-1], "30 entries")
        self.assertGreater(len([r for r in nio.requests if r.device == nd.FILE_DEVICE]), 1)

    def test_a_missing_directory_is_reported_in_words(self):
        rc, text, _ = self.run_cli("FLS sd0:/nowhere")
        self.assertEqual(rc, 2)
        self.assertIn("Cannot list that location", text)

    def test_usage(self):
        rc, text, nio = self.run_cli("FLS a b")
        self.assertEqual((rc, nio.requests), (1, []))
        self.assertIn("Usage: FLS", text)


if __name__ == "__main__":
    unittest.main()
