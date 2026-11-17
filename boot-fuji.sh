#!/usr/bin/env bash
# Boot a TRS-80 Model 4P from a PC-hosted fujinet-nio over the USB/serial adapter.
#
#   ./boot-fuji.sh                 # find the adapter, build the boot disk, send the loader, run fujinet-nio
#   ./boot-fuji.sh -p /dev/ttyUSB1 # pick the serial device yourself
#   ./boot-fuji.sh --no-autostart  # stop at the LS-DOS prompt instead of starting CONFIG
#   ./boot-fuji.sh --help
#
# Both the loader and fujinet-nio run in the foreground (Ctrl-C stops them). When it says so, hold Right Shift on
# the 4P and press Reset; keep Right Shift held until the loader has been sent. (The loader is locked to 8O1: the ROM
# also answers 0x55 in 8N1, but then rejects the file with "Error B", a parity error.) nioboot then waits for fujinet-nio,
# which serves the boot disk (LS-DOS with the FujiNet driver, FMOUNT/FLS/..., and CONFIG when it was built in).
#
# Environment (all optional):
#   FUJINET_NIO     the fujinet-nio binary built with the RS-232 profile
#                   (default: $NIO_WORKSPACE/repos/fujinet-nio/build/fujibus-rs232-debug/fujinet-nio)
#   FUJINET_RUN     directory fujinet-nio runs in; fujinet-data/ with the images and fujinet.yaml lives there
#                   (default: ~/dev/fujinet-run)
#   NIO_CONFIG_BIN  nio-config's trs80/build/config.bin, added to the boot disk as CONFIG/CMD when it exists
#                   (default: $NIO_WORKSPACE/repos/nio-config/trs80/build/config.bin)
#   NIO_AUTOSTART   0 to stop at the LS-DOS prompt instead of starting CONFIG (same as --no-autostart; default 1)
#   NIO_WORKSPACE   the fujinet-nio workspace (default: ~/dev/fujinet-nio-workspace)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${NIO_WORKSPACE:-$HOME/dev/fujinet-nio-workspace}"
NIO="${FUJINET_NIO:-$WS/repos/fujinet-nio/build/fujibus-rs232-debug/fujinet-nio}"
RUN="${FUJINET_RUN:-$HOME/dev/fujinet-run}"
CONFIG_BIN="${NIO_CONFIG_BIN:-$WS/repos/nio-config/trs80/build/config.bin}"
PORT=""
AUTOSTART="${NIO_AUTOSTART:-1}"

die() { echo "boot-fuji: $*" >&2; exit 1; }

usage() { sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--port) [ $# -ge 2 ] || die "$1 needs a device"; PORT="$2"; shift 2 ;;
    --no-autostart) AUTOSTART=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -x "$NIO" ] || die "fujinet-nio not found at $NIO (build it with './build.sh -cp fujibus-rs232-debug' in $WS/repos/fujinet-nio, or set FUJINET_NIO)"
cd "$HERE"

# ---- which USB serial device? --------------------------------------------------------------------------------
# A device is a candidate when it exists, is read/writable by us and no process has it open (an earlier
# fujinet-nio or loader still holding the port is the usual reason a boot attempt gets nowhere).
describe() {  # "<dev> (<by-id name>)"
  local dev="$1" link name=""
  for link in /dev/serial/by-id/*; do
    [ -e "$link" ] && [ "$(readlink -f "$link")" = "$dev" ] && name="$(basename "$link")"
  done
  echo "$dev${name:+ ($name)}"
}

holders() { fuser "$1" 2>/dev/null | tr -s ' ' | sed 's/^ //'; }

if [ -z "$PORT" ]; then
  free=(); skipped=()
  for dev in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$dev" ] || continue
    if [ ! -r "$dev" ] || [ ! -w "$dev" ]; then skipped+=("$dev: no access (is your user in the group that owns it?)"); continue; fi
    if fuser -s "$dev" 2>/dev/null; then skipped+=("$dev: in use by process $(holders "$dev")"); continue; fi
    free+=("$dev")
  done
  if [ ${#free[@]} -eq 0 ]; then
    echo "boot-fuji: no free USB serial device found." >&2
    for s in "${skipped[@]:-}"; do [ -n "$s" ] && echo "  skipped $s" >&2; done
    exit 1
  elif [ ${#free[@]} -eq 1 ]; then
    PORT="${free[0]}"
  else
    echo "Several USB serial devices are free:"
    i=1; for dev in "${free[@]}"; do echo "  $i) $(describe "$dev")"; i=$((i + 1)); done
    [ -t 0 ] || die "more than one candidate and no terminal to ask on: pass -p DEVICE"
    read -r -p "Which one is the 4P's adapter? [1-${#free[@]}] " n
    [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le ${#free[@]} ] || die "no such choice"
    PORT="${free[$((n - 1))]}"
  fi
fi
[ -e "$PORT" ] || die "$PORT does not exist"
{ [ -r "$PORT" ] && [ -w "$PORT" ]; } || die "no read/write access to $PORT"
if fuser -s "$PORT" 2>/dev/null; then
  die "$PORT is in use by process $(holders "$PORT") (stop that first)"
fi
echo "Using $(describe "$PORT")"

# ---- loader and boot disk ------------------------------------------------------------------------------------
make -s all >/dev/null || die "make failed: the loader (build/nioboot.hex) could not be built"
[ -f build/nioboot.hex ] || die "build/nioboot.hex is missing after make"

BASE="images/lsdos631l-upstream/L631NEW.DSK"
[ -f "$BASE" ] || die "$BASE is missing (the stock LS-DOS 6.3.1 disk)"
mkdir -p images
help="$(python3 tools/make_boot_image.py --help 2>&1)"
extra=()
have_config=0
if grep -q -- '--config-bin' <<<"$help"; then       # this checkout can add CONFIG/CMD
  if [ -f "$CONFIG_BIN" ]; then
    extra=(--config-bin "$CONFIG_BIN")
    have_config=1
    echo "Adding CONFIG/CMD from $CONFIG_BIN (this removes LS-DOS BASIC from the boot disk)"
  else
    extra=(--no-config)
    echo "No $CONFIG_BIN (make -C $WS/repos/nio-config/trs80 build/config.bin): booting without CONFIG"
  fi
fi
python3 tools/make_boot_image.py --base "$BASE" --out images/boot.dsk "${extra[@]}"

# fujinet-nio serves raw 256-byte-sector images from <run dir>/fujinet-data/images (boot.xfd, work.img).
python3 tools/make_nio_images.py "$RUN" >/dev/null
DATA="$RUN/fujinet-data"
if [ ! -f "$DATA/fujinet.yaml" ]; then
  cat > "$DATA/fujinet.yaml" <<YAML
fujinet:
  device_name: ""
boot:
  mode: config
  config_uri: host:/images/boot.xfd
  readonly: false
wifi:
  enabled: false
  ssid: ""
  bssid: ""
  passphrase: ""
devices:
  modem:
    enabled: false
    sniffer_enabled: false
  cpm:
    enabled: false
    ccp_image: ""
  printer:
    enabled: false
netsio:
  enabled: true
  host: localhost
  port: 9997
atari_sio:
  hsio_index: -1
  ack_gap_us: 250
  data_gap_us: 0
  window_ms: 10
  ignore_write_glitches: true
  proc_notify: false
clock:
  timezone: America/New_York
  enabled: true
channel:
  pty_path: ""
  tcp_host: 127.0.0.1
  tcp_port: 65504
  serial_port: $PORT
  uart:
    baud_rate: 19200
    data_bits: 8
    parity: odd
    stop_bits: 1
    flow_control: none
    tx_gap_us: 0
    tx_byte_gap_us: 0
    tx_chunk_size: 16
    tx_chunk_gap_us: 2000
  packet_link:
    capacity: 0
    record_timeout_ms: 0
translation:
  image:
    max_pixels: 0
hotsync:
  enabled: false
  port: 14238
  cradle: false
  root: /hotsync
  user_name: FujiNet
  backup: flagged
YAML
  echo "Wrote $DATA/fujinet.yaml"
elif ! grep -q 'config_uri: host:/images/boot.xfd' "$DATA/fujinet.yaml"; then
  echo "boot-fuji: warning: $DATA/fujinet.yaml does not boot host:/images/boot.xfd; the 4P may not find the boot disk" >&2
fi

# With CONFIG on the disk, the loader that also makes LS-DOS start it (nioboot.asm AUTO_CMD) is the one to send.
LOADER=build/nioboot.hex
if [ "$have_config" = 1 ] && [ "$AUTOSTART" = 1 ]; then
  if [ -f build/nioboot-config.hex ]; then
    LOADER=build/nioboot-config.hex
    echo "CONFIG will start by itself after LS-DOS boots (--no-autostart to stop at the prompt)"
  else
    echo "boot-fuji: this checkout has no build/nioboot-config.hex; CONFIG will not autostart (type CONFIG)" >&2
  fi
fi

# ---- go ------------------------------------------------------------------------------------------------------
echo
echo ">>> On the 4P: hold Right Shift, press Reset, and keep Right Shift held until the loader has been sent."
python3 trs80boot.py "$LOADER" -p "$PORT" --format 8O1 --entry 0x5000 --byte-delay 0.002 -y \
  || die "the loader failed (is the 4P at the ROM loader? hold Right Shift while pressing Reset, then run this again)"
echo
echo ">>> Loader sent; fujinet-nio is starting and will serve the boot disk. Ctrl-C stops it."
cd "$RUN"
FN_SERIAL_PORT="$PORT" exec "$NIO"
