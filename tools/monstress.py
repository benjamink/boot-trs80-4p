#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Hardware gate for the resident monitor: hammer it and count failures.

  tools/monstress.py [-p /dev/ttyUSB0]      (monitor must already be running: trs80mon.py boot)
Exit status is non-zero if any operation failed.
"""
import argparse, os, random, sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80.monitor import Monitor, MonitorError  # noqa: E402


@dataclass
class StressResult:
    operations: int = 0
    failures: int = 0
    retries: int = 0
    messages: list = field(default_factory=list)
    aborted: bool = False


class _Abort(Exception):
    pass


def run_stress(mon, pings=500, mem_bytes=16384, port_reads=50, seed=None,
               max_consecutive_failures=None, progress=None, progress_every=100):
    rnd = random.Random(seed)
    r = StressResult()
    start_retries = mon.retry_count
    streak = [0]

    def op(name, fn):
        r.operations += 1
        try:
            err = fn()
        except MonitorError as e:
            err = f"{e}"
        if err:
            r.failures += 1
            streak[0] += 1
            r.messages.append(f"{name}: {err}")
            if max_consecutive_failures and streak[0] >= max_consecutive_failures:
                r.aborted = True
                raise _Abort
        else:
            streak[0] = 0

    def ping():
        data = bytes(rnd.randrange(256) for _ in range(rnd.randrange(0, 251)))
        return None if mon.ping(data) == data else "echo mismatch"

    try:
        for i in range(pings):
            op(f"ping {i}", ping)
            if progress and (i + 1) % progress_every == 0:
                progress(i + 1)

        blob = bytes(rnd.randrange(256) for _ in range(mem_bytes))
        op("write_mem", lambda: mon.write_mem(0x8000, blob))
        op("read_mem", lambda: None if mon.read_mem(0x8000, mem_bytes) == blob else "memory mismatch")

        for i in range(port_reads):
            op(f"port_in {i}", lambda: mon.port_in(0xEA) and None)

        def exec_a():
            mon.write_mem(0x8100, bytes([0x3E, 0x42, 0xC9]))        # LD A,42h ; RET
            a = mon.exec(0x8100)["A"]
            return None if a == 0x42 else f"A={a:#04x}"
        op("exec", exec_a)

    except _Abort:
        pass

    r.retries = mon.retry_count - start_retries
    return r


def main():
    from trs80.serialio import SerialTransport, open_port
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("--pings", type=int, default=500)
    ap.add_argument("--mem", type=int, default=16384)
    a = ap.parse_args()
    mon = Monitor(SerialTransport(open_port(a.port, 19200)))
    mon.sync()
    r = run_stress(mon, pings=a.pings, mem_bytes=a.mem, max_consecutive_failures=5,
                   progress=lambda n: print(f"  {n} pings done", flush=True))
    print(f"operations={r.operations} failures={r.failures} retries={r.retries}" + (" ABORTED (link dead)" if r.aborted else ""))
    for m in r.messages[:20]:
        print("  FAIL", m)
    sys.exit(1 if r.failures else 0)


if __name__ == "__main__":
    main()
