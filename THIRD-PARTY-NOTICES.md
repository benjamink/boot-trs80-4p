# Third-party notices

This repository's own code is GPL-3.0-or-later (see `LICENSE`). It does not contain the third-party material below; it
fetches or refers to it, and the terms here apply to that material and to anything built from it.

## LS-DOS 6.3.1 (MISOSYS, Inc.)

The boot disks that `tools/make_boot_image.py` builds, and the `boot.dsk` / `boot.xfd` files attached to releases, are made from
the LS-DOS 6.3.1 Level L disks in [GmEsoft/LSDOS631L](https://github.com/GmEsoft/LSDOS631L) (`L631NEW.DSK`). Those disks are not stored in
this repository. The notice that comes with them reads:

> Copyright 1982-1984, 1986, 1990 by MISOSYS, Inc.
>
> Roy Soltoff holds the copyright to the software and documentation in the list below; notices that name other authors are outdated. Roy
> grants free permission to everyone to download and use this software and documentation and to redistribute it to others, provided this
> notice is retained. All other rights are reserved.
>
> Typed in (and enhanced) by Pete Cervasio (cervasio@airmail.net)
> Changes are copyright 1997-98 Peter W. Cervasio.
>
> Permission to do whatever you want with my changes is granted, as long as my copyright notice is left intact.
>
> [Minor edits to this file made 1-12-98 by Tim Mann.]

The disks in the releases are modified: LS-DOS BASIC, `HELP/CMD` and `DOS/HLP` are removed to make room, and the `SERIAL`, `FMOUNT`,
`FUMOUNT`, `FDRIVE`, `FLS`, `FUJIDRV` and `CONFIG` programs are added. The added programs are covered by this repository's licence
(`CONFIG` by nio-config's); LS-DOS itself is not.

## GmEsoft/LSDOS631L

The repository above (LS-DOS 6.3.1 Level L sources, disk images and keyboard drivers) is distributed under the GPL-3.0; its `LICENSE` and
`README.md` give the details. Upstream: <https://github.com/GmEsoft/LSDOS631L>.

## nio-config, fujinet-nio-lib

The release build compiles `CONFIG/CMD` from [nio-config](https://github.com/fujinet-nio/nio-config) with
[fujinet-nio-lib](https://github.com/fujinet-nio/fujinet-nio-lib). Their licences apply to `CONFIG/CMD`.

## fujinet-nio

`fujinet/` implements the wire protocol of [fujinet-nio](https://github.com/fujinet-nio/fujinet-nio) (GPL-3.0), written from its
protocol documentation. No fujinet-nio source is included.

## Not included

- The TRS-80 Model 4P ROMs (needed to run the MAME tests) and the Model 4 / TRSDOS 6 technical reference manuals are not part of this
  repository. Get them yourself; they stay under their owners' rights.
- Build tools (z88dk, sjasmplus) and MAME are used but not distributed here.
