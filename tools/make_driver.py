#!/usr/bin/env python3
"""Build the relocatable package for the resident FujiNet disk driver (fujinet/z80/fujidrv.asm).

The driver is assembled twice, at 1000h and 2000h; every byte that differs is the high byte of an address word, so the
positions of those words are exactly the relocations. The package holds the image rebased to address 0, the relocation
offsets and the sizes the installer (FUJIDRV/CMD) needs:

    dw image_length, dw total_length (image plus buffers), dw entry_offset, dw slot_offset, dw reloc_count, dw reloc_offsets..., image

Used by the Makefile:  python3 tools/make_driver.py build/fujidrv.pkg
"""
import os, re, struct, subprocess, sys, tempfile
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trs80.lmf import parse_hex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fujinet", "z80", "fujidrv.asm")
BASE_A, BASE_B = 0x1000, 0x2000

Package = namedtuple("Package", "blob total entry slot relocs")


def _assemble(base, workdir):
    hexf, symf = (os.path.join(workdir, f"drv{base:X}.{e}") for e in ("hex", "sym"))
    subprocess.run(["sjasmplus", "--nologo", "--msg=err", "-I", os.path.dirname(SRC), f"-DDRV_BASE={base:#x}",
                    f"--sym={symf}", f"--hex={hexf}", SRC], check=True)
    segs, _ = parse_hex(hexf)
    image = bytearray()
    for addr in sorted(segs):
        if addr != base + len(image):
            raise RuntimeError("driver image is not contiguous")
        image += segs[addr]
    syms = {k: int(v, 16) for k, v in re.findall(r"^(\w+):\s+EQU\s+0x([0-9A-Fa-f]+)", open(symf).read(), re.M)}
    return bytes(image), syms


def build_package(outdir):
    """Assembles the driver and writes <outdir>/fujidrv.pkg; returns its path."""
    with tempfile.TemporaryDirectory() as tmp:
        a, syms_a = _assemble(BASE_A, tmp)
        b, syms_b = _assemble(BASE_B, tmp)
    if len(a) != len(b):
        raise RuntimeError("the two assemblies differ in length")
    relocs = []
    delta = (BASE_B - BASE_A) >> 8
    for k in range(len(a)):
        if a[k] != b[k]:
            if k == 0 or a[k - 1] != b[k - 1] and False or (b[k] - a[k]) & 255 != delta:
                raise RuntimeError(f"byte {k} differs by something other than a relocated high byte")
            if a[k - 1] != b[k - 1]:
                raise RuntimeError(f"address word at {k - 1} changes in its low byte too")
            relocs.append(k - 1)
    blob = bytearray(a)
    for off in relocs:                                          # rebase to address 0
        word = (blob[off] | blob[off + 1] << 8) - BASE_A
        blob[off], blob[off + 1] = word & 255, (word >> 8) & 255
    total = syms_a["drv_end"] - BASE_A
    entry = syms_a["drv_entry"] - BASE_A
    slot = syms_a["v_slot"] - BASE_A
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "fujidrv.pkg")
    with open(path, "wb") as f:
        f.write(struct.pack("<5H", len(blob), total, entry, slot, len(relocs)))
        f.write(struct.pack(f"<{len(relocs)}H", *relocs))
        f.write(blob)
    return path


def parse_package(path):
    d = open(path, "rb").read()
    n, total, entry, slot, count = struct.unpack("<5H", d[:10])
    relocs = list(struct.unpack(f"<{count}H", d[10:10 + 2 * count]))
    blob = d[10 + 2 * count:]
    assert len(blob) == n
    return Package(blob, total, entry, slot, relocs)


if __name__ == "__main__":
    print(build_package(os.path.dirname(os.path.abspath(sys.argv[1])) if len(sys.argv) > 1 else os.path.join(ROOT, "build")))
