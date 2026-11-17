# Testing the 4P against a real fujinet-nio on this PC (temporary notes)

What this sets up: the 4P boots LS-DOS with no floppy, entirely from images served by the real fujinet-nio firmware
(its POSIX build) over the serial cable (`/dev/ttyUSB0`, 19200 baud, 8 data bits, odd parity). Worked on a real 4P on 2026-11-16.

## One-time setup

1. Build fujinet-nio (about 3 minutes; needs cmake, ninja, a C++ compiler):

       git clone https://github.com/fujinet-nio/fujinet-nio ~/dev/fujinet-nio
       cd ~/dev/fujinet-nio
       git submodule update --init --depth 1 third_party/yaml-cpp third_party/cjson
       cmake --preset fujibus-rs232-debug && cmake --build build/fujibus-rs232-debug

   The program is `build/fujibus-rs232-debug/fujinet-nio`.

2. Make a run directory with the images and a config (from this repo's root; change `RUN` if you like):

       make                                   # builds build/nioboot.hex
       python3 tools/make_boot_image.py --base images/lsdos631l-upstream/L631NEW.DSK --out images/boot.dsk
       RUN=~/dev/fujinet-run
       mkdir -p $RUN/fujinet-data/images
       cp ~/dev/fujinet-nio/build/fujibus-rs232-debug/fujinet-nio $RUN/
       cp ~/dev/fujinet-nio/build/fujibus-rs232-debug/fujinet-data/fujinet.yaml $RUN/fujinet-data/   # a default config to edit
       python3 tools/make_nio_images.py $RUN        # writes boot.xfd (the 4P's boot disk) and work.img (a second disk to FMOUNT)

   Edit `$RUN/fujinet-data/fujinet.yaml` (it is YAML; these keys already exist, change the values):

       boot:
         mode: config
         config_uri: host:/images/boot.xfd     # drive 0 of the 4P (FujiNet slot 1)
         readonly: false
       clock:
         timezone: America/New_York             # the 4P shows this zone; the default is UTC
       channel:
         serial_port: /dev/ttyUSB0
         uart:
           baud_rate: 19200
           parity: odd

   Why `.xfd`: a raw `.img` needs a sector-size hint, which the boot mount cannot give. A 184,320-byte `.xfd` is recognised as
   720 sectors of 256 bytes. `host:/` means the `fujinet-data` directory under the run directory.

   Any image you want to `FMOUNT` must be a raw 256-byte-sector image like these (`trs80.lsdosfs.flat_image` makes one from a DMK).

## Each test session

1. Nothing else may have the serial port open (a leftover `fujinet-nio` or a Python script).
2. Start this, from the repo root. It waits for the 4P, sends the loader, then runs fujinet-nio in the foreground:

       RUN=~/dev/fujinet-run
       python3 trs80boot.py build/nioboot.hex -p /dev/ttyUSB0 --entry 0x5000 --byte-delay 0.002 -y && \
         (cd $RUN && FN_SERIAL_PORT=/dev/ttyUSB0 ./fujinet-nio)

3. On the 4P: hold **Right Shift**, press **RESET**, keep holding until the screen says `Ready` (plus a couple of seconds), then let go.
   The screen may say `Not Ready` for a while first; that is the ROM's floppy message and is harmless. The 4P screen then shows
   `FujiNet NIO - booting LS-DOS`, and LS-DOS boots in about 10-20 seconds to `LS-DOS Ready` with no date/time prompt.
4. **After every 4P reset you must restart step 2** (Ctrl-C the old one first): the loader is only sent once per run.

## Things to try at the LS-DOS prompt

    DIR :0                                    the boot disk, served by the FujiNet
    FLS host:/images/                         list the images
    FUJIDRV :1                                install the serial disk driver on drive 1
    FMOUNT :1 host:/images/work.img SS=256    attach an image to drive 1
    FDRIVE                                    what is mounted
    DIR :1
    FUMOUNT :1

fujinet-nio logs every request to its terminal (`fujibus: receive ...`), which shows what the 4P is asking for.

## If something goes wrong

- **Stays at `Ready` / `Not Ready`, no banner:** the ROM loader missed the transfer. Reset again with Right Shift held; keep `--byte-delay 0.002`
  (without it about a third of loads failed). If the transfer itself prints `4P says: Error`, just retry.
- **Banner shows, then `Waiting for FujiNet...`:** the 4P is not getting answers. Is fujinet-nio running and did it log `Opened /dev/ttyUSB0 at 19200 baud`?
  Is the parity `odd` in the yaml? `nioboot` keeps retrying, so you can start fujinet-nio afterwards.
- **fujinet-nio logs `Failed to mount ... boot config_uri`:** the file is missing or not 184,320 bytes with the `.xfd` name.
- **Boot hangs after the welcome screen with the drive light on:** an old `nioboot` without the "disable drives 1-7" fix (rebuild with `make`).
- **Wrong time:** the `clock.timezone` in the yaml (UTC by default), and the FujiNet's own clock.
- **Killing leftovers from a shell:** use `kill <pid>`. `pkill -f <name>` can match your own shell command line and kill the shell.

## Details worth knowing

- The 4P always boots the same way: ROM serial loader -> `nioboot` (5000h) -> LS-DOS from FujiNet slot 1 -> `FUJIDRV` driver at E000h.
- Without the real FujiNet hardware this only exercises the PC-hosted firmware; the real RS-232 FujiNet board is untested.
- More background: `README.md` (floppy-less boot section) and `docs/superpowers/specs/2026-11-16-fujinet-nio-research-findings.md`.
