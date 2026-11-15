#!/usr/bin/env python3
"""serial_diag -- watch the serial port: modem-control lines + any received bytes.

  serial_diag.py                 # watch only
  serial_diag.py --loopback      # send test bytes (jumper pins 2-3 on the adapter first)
  serial_diag.py --toggle        # also wiggle DTR/RTS and see whether CTS/DSR/CD follow
Ctrl-C to quit. Prints a line only when something changes.
"""
import argparse, fcntl, os, select, struct, sys, termios, time, tty

L = {"DTR": termios.TIOCM_DTR, "RTS": termios.TIOCM_RTS, "CTS": termios.TIOCM_CTS,
     "DSR": termios.TIOCM_DSR, "CD": termios.TIOCM_CD, "RI": termios.TIOCM_RI}


def lines(fd):
    v = struct.unpack("I", fcntl.ioctl(fd, termios.TIOCMGET, b"\0\0\0\0"))[0]
    return " ".join(f"{n}={int(bool(v & m))}" for n, m in L.items())


def setl(fd, dtr, rts):
    for on, m in ((dtr, L["DTR"]), (rts, L["RTS"])):
        fcntl.ioctl(fd, termios.TIOCMBIS if on else termios.TIOCMBIC, struct.pack("I", m))


ap = argparse.ArgumentParser()
ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
ap.add_argument("--loopback", action="store_true")
ap.add_argument("--toggle", action="store_true")
a = ap.parse_args()

fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY)
tty.setraw(fd)
t = termios.tcgetattr(fd)
t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
t[4] = t[5] = termios.B19200
t[6][termios.VMIN], t[6][termios.VTIME] = 0, 0
termios.tcsetattr(fd, termios.TCSANOW, t)

if a.loopback:
    os.write(fd, b"\x55\xaa\x01")
    time.sleep(0.2)
    got = os.read(fd, 16) if select.select([fd], [], [], 0.5)[0] else b""
    print("loopback sent 55 aa 01, got:", got.hex(" ") or "NOTHING (adapter TX->RX path broken or no jumper)")
    sys.exit(0)

if a.toggle:
    for dtr, rts in ((1, 1), (0, 0), (1, 0), (0, 1), (1, 1)):
        setl(fd, dtr, rts)
        time.sleep(0.3)
        print(f"set DTR={dtr} RTS={rts} ->", lines(fd))
    sys.exit(0)

print("watching; reset / power-cycle the 4P now. Ctrl-C to stop.")
last = None
try:
    while True:
        cur = lines(fd)
        if cur != last:
            print(time.strftime("%H:%M:%S"), cur)
            last = cur
        if select.select([fd], [], [], 0.1)[0]:
            print(time.strftime("%H:%M:%S"), "RX:", os.read(fd, 64).hex(" "))
except KeyboardInterrupt:
    pass
