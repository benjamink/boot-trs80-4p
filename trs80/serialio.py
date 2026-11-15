"""Serial-port helpers for the TRS-80 4P: format setup, ROM-loader handshake, transport."""
import os, select, termios, time, tty

BAUDS = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400}

FORMATS = {  # ROM loader needs 8 data bits + ODD parity (Model 4P Service Manual); 1 or 2 stop bits
    "8O1": termios.CS8 | termios.PARENB | termios.PARODD,
    "8O2": termios.CS8 | termios.PARENB | termios.PARODD | termios.CSTOPB,
    "8N1": termios.CS8,   # handshake bytes 0x55/0xFF happen to pass in 8N1, but file data will NOT
}


class LoaderNotReady(Exception):
    """The 4P never answered the ROM loader handshake."""


def open_port(dev, baud):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    set_format(fd, baud, "8O1")
    return fd


def set_format(fd, baud, fmt):
    a = termios.tcgetattr(fd)
    a[0] = 0                                   # no sw flow control, don't drop parity errors
    a[2] = FORMATS[fmt] | termios.CREAD | termios.CLOCAL
    a[3] = 0
    a[4] = a[5] = BAUDS[baud]
    a[6][termios.VMIN], a[6][termios.VTIME] = 0, 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)


def read_all(fd, wait=0.0):
    """Return whatever bytes arrive within `wait` seconds (empty if none)."""
    out = b""
    end = time.time() + wait
    while True:
        r, _, _ = select.select([fd], [], [], max(0, end - time.time()))
        if not r:
            return out
        out += os.read(fd, 256)
        end = max(end, time.time() + 0.05)


def handshake(fd, baud, formats, timeout=None):
    """ROM serial loader handshake (as SBOOT4): send 0x55 until the 4P answers,
    then send 0xFF sync and wait for its answer. Cycles through serial formats.
    Raises LoaderNotReady after `timeout` seconds (None = wait forever)."""
    print("handshake: sending 0x55 until the 4P answers (Ctrl-C to give up)")
    deadline = None if timeout is None else time.time() + timeout
    while True:
        for fmt in formats:
            set_format(fd, baud, fmt)
            end = time.time() + 6   # ROM needs ~20 good bytes at 0.1s spacing
            if deadline is not None:
                end = min(end, deadline)
            while time.time() < end:
                os.write(fd, b"\x55")
                termios.tcdrain(fd)
                got = read_all(fd, 0.1)
                if got:
                    print(f"  reply to 0x55 with {fmt}: {got.hex(' ')}")
                    read_all(fd, 0.3)                      # drain
                    os.write(fd, b"\xff"); termios.tcdrain(fd)
                    sync = read_all(fd, 1.0)
                    print(f"  reply to sync 0xFF: {sync.hex(' ') or '(none)'}")
                    if sync[:1] == b"E":
                        raise SystemExit("4P reported an error ('E') during sync")
                    return fmt
            if deadline is not None and time.time() >= deadline:
                raise LoaderNotReady(
                    "no answer from the 4P. Hold the RIGHT-SHIFT key, press RESET, and keep holding "
                    "until the screen shows 'Ready'; check the null-modem cable and port.")
            print(f"  no reply with {fmt}, trying next format...")


class SerialTransport:
    """Transport for trs80.monitor.Monitor over a serial fd."""
    def __init__(self, fd):
        self.fd = fd

    def write(self, data):
        os.write(self.fd, data)
        termios.tcdrain(self.fd)

    def read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        return os.read(self.fd, 256) if r else b""
