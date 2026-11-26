# AGENTS.md — iot_term

Car drowsiness detector (IoT term project). **Start with `PLAN.md`** (milestones, requirement map, decisions).
The MQTT topics and payloads in `docs/mqtt_contract.md` are the contract between all parts.

- `esp32_node/` — ESP32-S3 sensor node firmware (PlatformIO, Arduino framework). **Most of this file is about this part.** Plan: `esp32_node/PLAN.md`.
- `pi_gateway/` — Raspberry Pi 5 gateway: camera drowsiness detection (Python, uv) and Pi sensors. See `pi_gateway/README.md` and `pi_gateway/PLAN.md`.
- `server/` — On-prem server on the Pi: Docker (Mosquitto, InfluxDB, Grafana) and `server.py`. Plan: `server/PLAN.md`.
- `docs/` — MQTT contract, evaluation, slides and video plans.
- `tools/` — `serial_capture.py` (ESP32 serial) and `deploy_pi.sh` (rsyncs `pi_gateway/` and `server/` to `bum@g3pi.local:~/iot_term/`).

## Hardware

- Board: **ESP32-S3-DevKitC-1, N16R8** (16 MB flash, 8 MB octal PSRAM). Verified on boot: `PSRAM: 8388608`, `Flash: 16777216`.
- Connected to the Mac through the chip's **native USB** (USB-Serial/JTAG, VID:PID `303A:1001`), not a CP210x/CH340 bridge.
- Serial port: `/dev/cu.usbmodem2101` (the number can change if the cable goes into another USB port; check with `pio device list`).
- Onboard RGB LED: `RGB_PIN 48` in `src/main.cpp` (some DevKitC revisions use 38).

## PlatformIO

- `pio` is **not on PATH**. Always call it by its full path:
  `~/.platformio/penv/bin/pio`
- PlatformIO Core 6.2.0, platform `espressif32`, env `esp32-s3-devkitc-1`.
- Key `platformio.ini` settings — don't remove these, or PSRAM/flash/serial break:
  - `board_upload.flash_size = 16MB`, `board_build.partitions = default_16MB.csv`
  - `board_build.arduino.memory_type = qio_opi` (octal PSRAM)
  - `-DBOARD_HAS_PSRAM`
  - `-DARDUINO_USB_CDC_ON_BOOT=1` (so `Serial` goes out the native USB port; without it you see no output)
  - `monitor_speed = 115200`

## Dev cycle

Run these from `esp32_node/`:

```bash
~/.platformio/penv/bin/pio run                    # build
~/.platformio/penv/bin/pio run -t upload          # build + flash
~/.platformio/penv/bin/pio run -t uploadfs        # flash data/ to LittleFS/SPIFFS (if a data/ folder exists)
~/.platformio/penv/bin/pio run -t clean           # clean build
~/.platformio/penv/bin/pio test                   # Unity tests in test/
~/.platformio/penv/bin/pio pkg install -l "author/Lib@^x.y"   # add a library to lib_deps
```

### Reading serial output (agents)

`pio device monitor` never exits, so don't run it in the foreground. Use the helper instead. It reads for a fixed time and then exits:

```bash
~/.platformio/penv/bin/python ../tools/serial_capture.py --seconds 8 --reset
```

- `--reset` reboots the board first so you capture the boot log. Leave it out to just listen.
- `--port` defaults to the first `/dev/cu.usbmodem*`; `--baud` defaults to 115200.
- It uses PlatformIO's Python, because that one already has pyserial.
- Only one program can hold the port at a time. Close any open monitor (including one in VS Code or a Terminal tab) before uploading or capturing.

For a live view the user can watch, open `pio device monitor` in a Terminal tab instead.

Typical loop: edit `src/` → `pio run` → fix errors → `pio run -t upload` → `serial_capture.py --reset` → check the output.

## Troubleshooting

- **Upload can't connect / port busy:** close other serial monitors first. If it still fails, ask the user to hold **BOOT**, tap **RESET**, then release BOOT, and retry the upload. After a manual-boot flash, the user may need to tap RESET to run the new firmware.
- **Port disappears after a flash or crash:** with native USB, the port re-enumerates on reset. Wait a second and re-check `pio device list`.
- **No serial output:** check that `ARDUINO_USB_CDC_ON_BOOT=1` is still in `build_flags`, and add a `delay(1000)` after `Serial.begin` so early prints aren't lost.
- **PSRAM reports 0:** `memory_type` must be `qio_opi` for N16R8.
- **Boot loop:** capture with `--reset` and read the panic/backtrace; decode addresses with `monitor_filters = esp32_exception_decoder` in `platformio.ini`.

## Limits

- Agents can't see the LED, display, or wiring. Verify through serial prints, or ask the user what they see.
- Flashing changes the physical device. Build freely; flash when the task calls for it.
