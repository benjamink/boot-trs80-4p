# FujiNet RS-232 Standalone Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The FujiNet ESP32-S3 RS-232 board sends the 4P's ROM-loader load module itself and then serves the boot disk, so the laptop is no longer needed.

**Architecture:** A `Trs80LoaderSender` in fujinet-nio decorates the UART `Channel` and implements `IBusLineCoordinator`. It probes with 0x55 only after ~10 s without a valid FujiBus frame, sniffs the ROM's "Found Baud Rate" reply while passing all bytes through to the FujiBus transport, then sends 0xFF and streams a ready-made load module from flash. This repo builds that module and stages the flash assets.

**Tech Stack:** C++17 / doctest / CMake / PlatformIO ESP32-S3 (fujinet-nio); Python 3 + sjasmplus (this repo).

**Spec:** `docs/superpowers/specs/2026-11-18-fujinet-rs232-standalone-boot-design.md`

## Global Constraints

- ROM loader line format: 19200 baud, 8 data bits, **odd** parity, 1 stop bit.
- Handshake: 0x55 repeated until the ROM answers "Found Baud Rate", then 0xFF, ROM answers "Loading ", then the load module. Byte pacing 2 ms (`--byte-delay 0.002` on the laptop). On "Error" go back to probing.
- Probe interval 100 ms; idle threshold 10 s since the last valid FujiBus frame (both configurable, these are the defaults).
- Load module entry point 0x5000; record size 16 data bytes (as `trs80boot.py`).
- Sender is **off unless configured**; no behavior change for any other board or build.
- Board/build: `rs232-esp32-s3-wroom-1-n16r8`, `build_board = fujibus-gpio-rs232-uart-log-s3-wroom-1-n16r8` (already in `platformio.local.ini`); flashed over the USB-JTAG port `/dev/ttyACM0` (user is in `uucp`).
- Flash assets live in `distfiles/esp32-data/boot/trs80/` (`nioboot.cmd`, `boot.xfd`); generated files are not committed.
- fujinet-nio work goes on a branch of the owner's fork (`origin` = `benjamink/fujinet-nio`); the checkout at `~/dev/fujinet-nio-workspace/repos/fujinet-nio` is on a detached HEAD at `1d4de69`: create `feat/trs80-loader-sender` from it first. No upstream PR.
- No Claude attribution in commits, PRs or releases (the owner's standing rule overrides the default trailers).
- Flashing the board and anything touching the real 4P: ask the owner first.

## Review Focus

1. A running 4P sends a FujiBus request while the sender is probing: the request must still be served (probing passes bytes through; only "Found Baud Rate" is consumed). Test in Task 2.
2. A probe byte must never land inside a response frame being written: probes are written only from `poll()`, never between a request being received and its response being sent. Test in Task 2.
3. ROM answers "Error" (or nothing) mid-transfer: back to probing, no wedge, no partial state kept. Test in Task 2.
4. After a completed send, nioboot needs a few seconds before its first request: the sender must not re-probe inside the idle window that starts at completion. Test in Task 2.
5. Loader file missing or unreadable at startup: log once, sender disabled, FujiBus serving unaffected. Test in Task 3.

---

### Task 1: Load module and flash-asset build (this repo)

**Files:**
- Create: `tools/make_loader_cmd.py`, `tools/stage_fujinet_flash.py`, `tests/test_make_loader_cmd.py`
- Modify: `Makefile` (add `build/nioboot.cmd`, `build/nioboot-config.cmd`, include them in `all`)

**Interfaces:**
- Produces: `build/nioboot.cmd` and `build/nioboot-config.cmd`, byte-identical to what `trs80boot.py <hex> --entry 0x5000` sends (`build_lmf(segs, 0x5000, 16)`). `tools/make_loader_cmd.py IN.hex OUT.cmd [--entry 0x5000]`. `tools/stage_fujinet_flash.py --nio-repo PATH [--config]` copies the chosen `.cmd` to `<nio>/distfiles/esp32-data/boot/trs80/nioboot.cmd`, converts `images/boot.dsk` via the existing `tools/make_nio_images.py` logic to `boot.xfd` there, and writes the staged `fujinet.yaml` (Task 4 defines its contents).

- [ ] **Step 1: Write failing test** `test_cmd_matches_what_trs80boot_sends`: for `build/nioboot.hex`, `make_loader_cmd` output equals `build_lmf(*parse_hex(hex)[0:1], 0x5000, 16)`; and `test_entry_override` / `test_no_entry_record_uses_flag`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_make_loader_cmd.py -v` (or the repo's runner); expect FAIL (module missing).
- [ ] **Step 3: Implement** `make_loader_cmd.py` using `trs80.lmf.build_lmf` / `parse_hex`; add the two Makefile rules.
- [ ] **Step 4: Run** the test and `make build/nioboot.cmd build/nioboot-config.cmd`; expect PASS and both files non-empty.
- [ ] **Step 5: Implement `stage_fujinet_flash.py`**; check by running it against a temp directory (`--nio-repo /tmp/...`) and listing the produced files.
- [ ] **Step 6: Commit** (this repo).

### Task 2: `Trs80LoaderSender` state machine (fujinet-nio)

**Files:**
- Create: `include/fujinet/io/trs80_loader_sender.h`, `src/lib/trs80_loader_sender.cpp`, `tests/test_trs80_loader_sender.cpp`
- Modify: `CMakeLists_posix.cmake` (add source next to `src/lib/stream_session.cpp`); check `src/CMakeLists.txt` for how ESP32 collects `src/lib` and add it if sources are listed.

**Interfaces:**
- Produces:
  ```cpp
  struct Trs80LoaderOptions {
      std::vector<std::uint8_t> module;          // load module, streamed as-is
      std::chrono::milliseconds probeInterval{100};
      std::chrono::milliseconds idleThreshold{10000};
      std::chrono::milliseconds byteGap{2};
      std::chrono::milliseconds replyTimeout{2000};
  };
  class Trs80LoaderSender : public Channel, public IBusLineCoordinator {
  public:
      using Clock = std::function<std::chrono::steady_clock::time_point()>;
      Trs80LoaderSender(Channel& inner, Trs80LoaderOptions opts, Clock now);
      void poll();   // drive from the main loop; non-blocking
      enum class State { Idle, Probing, Syncing, Sending };
      State state() const;
      // Channel: delegate everything to `inner`; read() also feeds the reply matcher.
      // IBusLineCoordinator: frame_received(true) resets the idle timer; line_idle() returns false.
  };
  ```
  Also forward `packet_io()`, `connection_epoch()`, `supports_readable_wait()`, `wait_for_readable()`; grep for `dynamic_cast` on the channel (e.g. `BaudControl`) in `setup_transports` and the main files and keep those working.

- [ ] **Step 1: Write failing tests** with a fake inner `Channel` (scripted ROM) and a manual clock. Test names and what they assert:
  - `idle_before_threshold_writes_nothing`: 9.9 s with no frames: no bytes written.
  - `probes_every_100ms_after_threshold`: after 10 s, 0x55 bytes appear at 100 ms spacing.
  - `valid_frame_stops_and_resets_probing`: `frame_received(true)` while probing returns to Idle and restarts the 10 s window.
  - `rom_reply_leads_to_ff_then_module_with_2ms_gaps`: ROM sends "Found Baud Rate", sender writes 0xFF, ROM sends "Loading ", module bytes follow one per 2 ms, final state Idle.
  - `probing_passes_bytes_through_and_serves_requests` (Review Focus 1): a FujiBus-looking byte sequence arriving while Probing is returned by `read()` unchanged and does not advance the state.
  - `no_probe_between_request_and_response` (Review Focus 2): probe bytes are written only by `poll()`; writes made through `Channel::write` are passed unchanged and never interleaved with a probe.
  - `error_reply_returns_to_probing` and `reply_timeout_returns_to_probing` (Review Focus 3).
  - `no_reprobe_within_idle_window_after_send` (Review Focus 4).
- [ ] **Step 2: Run** `cmake --preset fujibus-rs232-debug && cmake --build build/fujibus-rs232-debug --target fujinet-nio-tests && build/fujibus-rs232-debug/tests/fujinet-nio-tests -tc="*loader*"`; expect FAIL to compile/link.
- [ ] **Step 3: Implement** the class; the clock and the inner channel are injected so no sleeping occurs; reply matching scans a rolling window of bytes read for the ASCII "Found" prefix and "Error"; "Loading " is awaited after 0xFF.
- [ ] **Step 4: Run** the loader tests plus the whole `fujinet-nio-tests`; expect all PASS.
- [ ] **Step 5: Commit** on `feat/trs80-loader-sender`.

### Task 3: Config block and wiring (fujinet-nio)

**Files:**
- Modify: `include/fujinet/config/fuji_config.h` (add `Trs80LoaderConfig { bool enabled{false}; std::string path; int probeIntervalMs{100}; int idleSeconds{10}; }` and `FujiConfig::trs80Loader`), `src/lib/fuji_config_yaml_store.cpp` (read and write key `trs80_loader` with `enabled`, `path`, `probe_interval_ms`, `idle_seconds`), `src/app/main_posix.cpp` and `src/app/main_esp32.cpp` (when enabled: read `path` through `StorageManager`, build the sender around `channel`, pass it to `setup_transports` in place of the raw channel and as the line coordinator when hotsync gives none, call `sender->poll()` each loop iteration next to the existing ingress polls).
- Test: extend the yaml-store test file (find it with `ls tests | grep yaml`), add `tests/test_trs80_loader_config.cpp` if none fits.

**Interfaces:** Consumes `Trs80LoaderSender(Channel&, Trs80LoaderOptions, Clock)` from Task 2.

- [ ] **Step 1: Write failing tests:** `trs80_loader_defaults_off`; `trs80_loader_yaml_round_trip` (all four keys); `missing_loader_file_disables_sender_without_error` (Review Focus 5; put the file-reading into a small helper `std::optional<std::vector<std::uint8_t>> load_loader_module(StorageManager&, const std::string&)` so it is testable with `tests/fake_fs.h`).
- [ ] **Step 2: Run** the tests; expect FAIL.
- [ ] **Step 3: Implement** config fields, yaml parse/emit, the helper, and the wiring in both mains.
- [ ] **Step 4: Run** the full `fujinet-nio-tests`; expect PASS. Build `fujibus-rs232-debug` and run the POSIX binary with the sender enabled against a pty or the fake ROM to see it probe in the log.
- [ ] **Step 5: Build the ESP32 firmware** (`./build.sh -cp fujibus-gpio-rs232-uart-log-s3-wroom-1-n16r8` per `boot-fuji.sh`'s hint; confirm the exact invocation in `build.sh --help`); expect a clean build. Do not flash yet.
- [ ] **Step 6: Commit.**

### Task 4: Flash defaults and packaging

**Files:**
- Modify: `tools/stage_fujinet_flash.py` (this repo), `pio-build` staging only if `stage-fs-data.py` does not already copy a root-level `fujinet.yaml` from `distfiles/esp32-data/`.
- Create (generated, not committed): `distfiles/esp32-data/boot/trs80/nioboot.cmd`, `boot.xfd`, and the staged `fujinet.yaml`.

**Interfaces:** the staged `fujinet.yaml` contains `boot: {mode: config, config_uri: flash:/boot/trs80/boot.xfd, readonly: false}`, `clock.timezone: America/New_York`, `channel.uart: {baud_rate: 19200, data_bits: 8, parity: odd, stop_bits: 1, tx_chunk_size: 16, tx_chunk_gap_us: 2000}`, `trs80_loader: {enabled: true, path: flash:/boot/trs80/nioboot.cmd, probe_interval_ms: 100, idle_seconds: 10}`, `wifi.enabled: false` (Wi-Fi is not part of this task; `FLS` against `host:`-style paths is replaced by flash paths, see Task 5).

- [ ] **Step 1:** Run `./build.sh -f` dry (or the `boot_images` staging step alone) with `boot_images = trs80` and confirm the staged image lists the three files and fits the 4 MiB partition (the build already stops if not).
- [ ] **Step 2:** Confirm the staged `fujinet.yaml` reaches the flash filesystem root; if not, adjust staging so it does, keeping it out of git (`.gitignore` entry for the trs80 boot directory).
- [ ] **Step 3: Commit** the tooling changes only.

### Task 5: Flash and real-4P verification (owner present)

**Files:** none (procedure and results go into a short `docs/fujinet-rs232-flashing.md` in this repo, replacing nothing in `docs/fujinet-nio-testing.md`).

- [ ] **Step 1: Ask the owner for go-ahead**, then flash firmware and filesystem over `/dev/ttyACM0` (`./build.sh -f` and the firmware upload, using the commands confirmed in Task 3/4). Expected: the board boots and logs on its console; nothing else on the laptop holds the port.
- [ ] **Step 2:** Connect the board to the 4P's RS-232 port; power both. Hold Right-Shift, press Reset: expect the loader banner, then `LS-DOS Ready` (or CONFIG) with no laptop process open on a serial port.
- [ ] **Step 3:** Run `DIR :0`, `FUJIDRV :1`, `FMOUNT`/`FDRIVE`, and check the clock/time zone.
- [ ] **Step 4:** Leave LS-DOS idle at the prompt for over a minute, then `DIR :0` and `FMOUNT`: no errors, no garbage. If stray 0x55 bytes cause trouble, record it and switch the sender to a boot window (spec fallback: probing only for the first 60 s after startup).
- [ ] **Step 5:** Reset the 4P again with Right-Shift: it reloads by itself. Record the outcome of all steps in `docs/fujinet-rs232-flashing.md` and commit it.
