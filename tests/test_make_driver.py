import os, re, shutil, struct, subprocess, tempfile, unittest

from tools.make_driver import build_package, parse_package
from tests.z80emu import Z80

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class DriverPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.pkg = parse_package(build_package(self.tmp))

    def test_relocating_the_package_to_any_address_equals_assembling_there(self):
        subprocess.run(["sjasmplus", "--nologo", "--msg=err", "-I", os.path.join(ROOT, "fujinet", "z80"),
                        "-DDRV_BASE=0xC123", "--raw=" + os.path.join(self.tmp, "ref.bin"),
                        os.path.join(ROOT, "fujinet", "z80", "fujidrv.asm")], check=True)
        ref = open(os.path.join(self.tmp, "ref.bin"), "rb").read()
        image = bytearray(self.pkg.blob)
        for off in self.pkg.relocs:
            word = image[off] | image[off + 1] << 8
            word = (word + 0xC123) & 0xFFFF
            image[off], image[off + 1] = word & 255, word >> 8
        self.assertEqual(bytes(image), ref[:len(image)])

    def test_sizes_and_entry(self):
        p = self.pkg
        self.assertEqual(p.blob[0], 0x18)                               # starts with the module header's JR
        self.assertEqual(p.blob[4:8], bytes([3]) + b"$FJ")
        self.assertGreater(p.total, len(p.blob) + 0x300)                # room for the buffers after the image
        self.assertLess(p.total, 0x1000)
        self.assertTrue(0 < p.slot < len(p.blob))                       # where the installer writes the FujiNet slot
        self.assertTrue(0 < p.entry < len(p.blob))                      # drv_entry offset from the module start
        self.assertEqual(len(p.relocs), len(set(p.relocs)))
        self.assertTrue(all(0 <= r < len(p.blob) - 1 for r in p.relocs))
        # the header's END-1 word is itself a relocated address
        self.assertIn(2, p.relocs)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus not installed")
class InstallerTests(unittest.TestCase):
    """FUJIDRV :d under the fake DOS: copies the driver below HIGH$, relocates it, points the drive's DCT at it."""

    def run_installer(self, line, high=0xF7FF):
        from tests.fakedos import FakeDos, DosExit
        from tests.z80emu import load_hex
        subprocess.run(["make", "-B", "-C", ROOT, "build/fujidrv_cmd.hex"], check=True, stdout=subprocess.DEVNULL)
        cpu = Z80()
        load_hex(cpu, os.path.join(ROOT, "build", "fujidrv_cmd.hex"))
        self.dos = FakeDos(cpu)
        self.dos.high = high
        line = line.split(" ", 1)[1] if " " in line else ""
        cpu.mem[0x4800:0x4800 + len(line) + 1] = line.encode() + b"\r"
        cpu.set_rp(4, 5, 0x4800)
        cpu.sp, cpu.pc = 0x7000, 0x3000
        try:
            for _ in range(5_000_000):
                cpu.step()
        except DosExit:
            pass
        self.cpu = cpu
        return cpu.hl(), "\n".join(self.dos.messages)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.pkg = parse_package(build_package(os.path.join(ROOT, "build")))

    def test_installs_below_high_and_patches_the_dct(self):
        rc, text = self.run_installer("FUJIDRV :2")
        self.assertEqual(rc, 0, text)
        base = self.dos.high + 1
        self.assertEqual(self.dos.high, 0xF7FF - self.pkg.total)
        self.assertEqual(base, 0xF800 - self.pkg.total)
        m = self.cpu.mem
        dct = 0x0470 + 20
        self.assertEqual(m[dct], 0xC3)
        self.assertEqual(m[dct + 1] | m[dct + 2] << 8, base + self.pkg.entry)
        self.assertEqual(m[base + self.pkg.slot], 3)                      # NIO slot = drive + 1, in the driver's own image
        self.assertEqual(list(m[dct + 6:dct + 10]), [39, 17, 0x45, 20])
        self.assertEqual(m[base], 0x18)
        self.assertIn("$FJ", bytes(m[base + 5:base + 8]).decode())
        endword = m[base + 2] | m[base + 3] << 8
        self.assertEqual(endword, base + self.pkg.total - 1)             # relocated END-1
        self.assertIn(":2", text)

    def test_second_driver_stacks_below_the_first_and_both_work(self):
        self.run_installer("FUJIDRV :2")
        h1 = self.dos.high
        rc, _ = self.run_installer("FUJIDRV 3", high=h1)
        self.assertEqual(rc, 0)
        self.assertEqual(self.cpu.mem[h1 - self.pkg.total + 1 + self.pkg.slot], 4)
        self.assertEqual(self.dos.high, h1 - self.pkg.total)

    def test_bad_drive_is_a_usage_error_and_changes_nothing(self):
        for line in ("FUJIDRV", "FUJIDRV :9", "FUJIDRV :x", "FUJIDRV :2 junk"):
            rc, text = self.run_installer(line)
            self.assertEqual(rc, 1, line)
            self.assertIn("Usage", text)
            self.assertEqual(self.dos.high, 0xF7FF)

    def test_refuses_drive_0(self):
        rc, text = self.run_installer("FUJIDRV :0")
        self.assertEqual(rc, 1)
        self.assertEqual(self.dos.high, 0xF7FF)
