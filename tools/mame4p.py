"""Drive MAME's Model 4P (trs80m4p) headless: boot LS-DOS from a disk image, type at it, read its screen, and reach
its RS-232 port through a pty (19200 baud 8O1). For development without the real machine; see docs/superpowers/specs.

Needs `mame`, and the 4P ROMs (8075332.u69, 8049007.u103, trs80m4p_loader_hack.rom) in <rom_dir>/trs80m4p/.
"""
import os, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))


class Mame4P:
    def __init__(self, rom_dir, disk=None, mode="disk", seconds=900, tap=None):
        self.rom_dir, self.disk, self.mode, self.seconds, self.tap = rom_dir, disk, mode, seconds, tap
        self.tmp = tempfile.mkdtemp(prefix="mame4p-")
        self.ctl = os.path.join(self.tmp, "ctl")
        self.proc = self.pty = self.log = None

    def start(self):
        before = set(os.listdir("/dev/pts"))
        env = dict(os.environ, MAME4P_CTL=self.ctl, MAME4P_MODE=self.mode)
        if self.tap:
            env["MAME4P_TAP"] = self.tap
        cmd = ["mame", "trs80m4p", "-rompath", self.rom_dir, "-rs232", "pty", "-video", "none", "-sound", "none",
               "-noplugins", "-seconds_to_run", str(self.seconds), "-autoboot_script", os.path.join(HERE, "mame4p.lua")]
        if self.disk:
            cmd += ["-flop1", self.disk]
        self.log = open(os.path.join(self.tmp, "mame.out"), "w")
        self.proc = subprocess.Popen(cmd, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(100):
            new = set(os.listdir("/dev/pts")) - before - {"ptmx"}
            if new:
                self.pty = "/dev/pts/" + sorted(new, key=int)[0]
                return self.pty
            time.sleep(0.1)
        raise RuntimeError("MAME did not create its pty; see " + os.path.join(self.tmp, "mame.out"))

    def screen(self):
        try:
            with open(self.ctl + ".screen") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def type(self, text):
        """Type text at the 4P's keyboard; "\\n" in it is Enter."""
        with open(self.ctl + ".cmd", "a") as f:
            f.write("keys " + text.replace("\n", "\\n") + "\n")

    def wait_for(self, text, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.screen():
                return self.screen()
            time.sleep(0.5)
        raise TimeoutError(f"{text!r} never appeared; screen was:\n{self.screen()}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.log:
            self.log.close()
            self.log = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()
