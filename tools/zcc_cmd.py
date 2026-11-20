# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Benjamin Krein
"""Turn a raw binary built by z88dk (loaded at a fixed address) into an LS-DOS /CMD load module."""
from trs80.lmf import build_lmf


def bin_to_lmf(path, load=0x3000, entry=0x3000):
    with open(path, "rb") as f:
        data = f.read()
    return build_lmf({load: data}, entry, block=240)
