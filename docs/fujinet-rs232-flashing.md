# Booting the 4P from the FujiNet RS-232 board (no laptop)

The board (ESP32-S3, `rs232-esp32-s3-wroom-1-n16r8`) runs fujinet-nio from the `feat/trs80-loader-sender` branch of
`benjamink/fujinet-nio`. It sends the 4P's ROM serial loader itself (`Trs80LoaderSender`) and then serves the boot disk
from its own flash. Design: `docs/superpowers/specs/2026-11-18-fujinet-rs232-standalone-boot-design.md`.

## Build and stage (no hardware touched)

    NIO=~/dev/fujinet-nio-workspace/repos/fujinet-nio
    make                                   # build/nioboot.cmd (the ROM-loader load module)
    python3 tools/make_boot_image.py --base images/lsdos631l-upstream/L631NEW.DSK --out images/boot.dsk --no-config
    python3 tools/stage_fujinet_flash.py --nio-repo $NIO       # --config also needs CONFIG/CMD on boot.dsk
    # in $NIO/platformio.local.ini, [fujinet]:  boot_images = trs80
    cd $NIO && ./build.sh -b && pio run -t buildfs     # firmware.bin and littlefs.bin under .pio/build/<board>/

The staged `fujinet.yaml` (flash root) sets 19200 8O1, `boot.config_uri: flash:/boot/trs80/boot.xfd`, time zone
America/New_York, Wi-Fi off, and `trs80_loader` on (probe after 10 s without a valid FujiBus frame, every 100 ms).

## Flash (ERASES the board's filesystem, including any saved Wi-Fi settings)

    cd $NIO && ./build.sh -b -u -f          # firmware, then the filesystem, over /dev/ttyACM0

Nothing else may have `/dev/ttyACM0` open.

## Try it on the 4P

1. Connect the board to the 4P's RS-232 port (null-modem as for the laptop adapter) and power both.
2. 4P: hold Right-Shift, press Reset. Within about 10 s of the board's last FujiBus frame it starts probing; the
   loader banner appears, then `LS-DOS Ready`.
3. `DIR :0`, `FUJIDRV :1`, `FMOUNT`, `FDRIVE`, `TIME`.
4. Leave LS-DOS idle at the prompt for over a minute (probes active), then `DIR :0` and `FMOUNT` again.
5. Reset the 4P again with Right-Shift: it reloads by itself.

If stray probe bytes upset LS-DOS (step 4), switch the sender to a boot window (probe only during the first 60 s after
power-up); see the design's fallback.

## Results

(To be filled in after the real-4P run.)
