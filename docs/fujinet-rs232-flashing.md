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
`EST5EDT,M3.2.0,M11.1.0` (a POSIX TZ string; the ESP32 has no zoneinfo, so an Olson name would mean UTC), Wi-Fi off, and `trs80_loader` on (probe after 10 s without a valid FujiBus frame, every 100 ms).

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

## Known limitation: the clock

With Wi-Fi off the board never gets network time (SNTP starts only once Wi-Fi has an address), so `TIME` on the 4P is
wrong until Wi-Fi is configured (set `wifi: {enabled: true, ssid: ..., passphrase: ...}` in the board's `fujinet.yaml`;
the staged file deliberately carries no credentials). Everything else is independent of the clock.

## Results

Real 4P, 2026-11-18, ESP32-S3 RS-232 board, firmware from `feat/trs80-loader-sender`: all of the following passed.

1. Right-Shift + Reset: the board sent the loader by itself and the 4P reached `LS-DOS Ready` (laptop not on the serial line).
2. `DIR :0`, `FUJIDRV :1`, `FDRIVE`, `FMOUNT`/`DIR :1`, correct `TIME` (Wi-Fi + SNTP + POSIX time zone).
3. LS-DOS idle at the prompt for over a minute with the sender probing, then `DIR :0` and `FMOUNT`: no errors.
4. Second Right-Shift + Reset: reloaded and booted by itself.

### Gotcha: an SD card wins over flash

The config store prefers the SD card's `fujinet.yaml` (flash is only the mirror), and `fujinet-runtime-mounts.tsv` on the SD
remounts old drives at start-up (drive 0 would beat the boot disk). With an SD card in the board, put the TRS-80 settings
in the SD card's `fujinet.yaml` (`boot.config_uri: flash:/boot/trs80/boot.xfd`, `channel.uart.parity: odd`,
`clock.timezone: EST5EDT,M3.2.0,M11.1.0`, the `trs80_loader` block) and move the runtime-mounts file aside. The board's USB
port (`/dev/ttyACM0`, 115200) prints its log, including `trs80loader: TRS-80 loader sender on: ...` and
`uart_ch: ... parity=odd` when the config is right.

Going back to Amiga work: restore `fujinet.yaml.amiga` and `fujinet-runtime-mounts.tsv.amiga` (kept on the SD card and in
`~/dev/fujinet-yaml-backups/`, which holds the Wi-Fi passphrase and stays out of git).
