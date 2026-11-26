# Pi 5 gateway

Two programs run on the Pi and publish to Mosquitto on the same Pi
(topics and payloads: [../docs/mqtt_contract.md](../docs/mqtt_contract.md)):

| Program | Runs with | Publishes | Rate |
|---|---|---|---|
| **vision** (`drowsiness/`) | uv venv, Python 3.11, MediaPipe | `car/vision/driver` | 2 Hz, plus at once on a state change |
| **sensors** (`sensors.py`) | system `/usr/bin/python3` | `car/gateway/cabin` | 1 Hz |

vision: `rpicam-vid` MJPEG pipe -> OpenCV -> MediaPipe Face Mesh -> eye aspect ratio (EAR).
The state is `open`, `closed` (EAR below the threshold), `drowsy` (closed for `--frames`
frames in a row) or `no_face`. The message where the state becomes `drowsy` carries the
absolute path of the saved JPEG in `snapshot`.

## Wiring (Raspberry Pi 5 header)

| Part | Module pin | Pi pin | Notes |
|---|---|---|---|
| Pi Camera | ribbon | CAM/DISP 0 | |
| KY-001 (DS18B20) | + / − | 3V3 (pin 1) / GND (pin 9) | The KY-001 board has the 4.7k pull-up |
| | S | **GPIO 4** (pin 7) | Needs `dtoverlay=w1-gpio` (below) |
| HC-SR04 | VCC / GND | 5V (pin 2) / GND (pin 6) | |
| | TRIG | **GPIO 23** (pin 16) | 3.3 V is enough to trigger |
| | ECHO | **GPIO 24** (pin 18) through a **1k / 2k divider** | see warning |

> **Warning: the HC-SR04 ECHO pin outputs 5 V. Pi GPIOs are 3.3 V only.**
> Wire ECHO -> 1 kΩ -> GPIO 24, and GPIO 24 -> 2 kΩ -> GND
> (5 V × 2k / 3k ≈ 3.3 V). Connecting ECHO straight to the Pi can damage it.

## Setup on the Pi (once)

1. 1-Wire for the DS18B20: add this line to `/boot/firmware/config.txt` (under `[all]`), then reboot:

       dtoverlay=w1-gpio

   Check: `ls /sys/bus/w1/devices/` shows a `28-xxxxxxxxxxxx` folder, and
   `cat /sys/bus/w1/devices/28-*/w1_slave` ends in `t=<milli °C>`.
   (GPIO 4 is the overlay's default pin; for another pin use `dtoverlay=w1-gpio,gpiopin=N`.)

2. System packages for `sensors.py`:

       sudo apt update
       sudo apt install python3-gpiozero python3-lgpio python3-paho-mqtt

   The user `bum` must be in the `gpio` and `video` groups (the Pi OS default user is).

3. Python env for vision (needs `uv`; it fetches Python 3.11 itself). From the Mac, deploy:

       ../tools/deploy_pi.sh

   Then on the Pi:

       cd ~/iot_term/pi_gateway
       uv sync

   Run `uv sync` again after every deploy that changes `pyproject.toml` / `uv.lock`.

## Run by hand

    cd ~/iot_term/pi_gateway

    # vision: calibrate, stream on :8000, publish to the local broker
    uv run python -u -m drowsiness.main --calibrate --stream-port 8000 --mqtt-host localhost

    # sensors
    /usr/bin/python3 sensors.py

    # watch both topics (Mac or Pi)
    mosquitto_sub -h g3pi.local -t 'car/vision/#' -t 'car/gateway/#' -v

Annotated video: http://g3pi.local:8000

### vision options
- `--calibrate` set the threshold from 3 s of open eyes (look at the camera right after start)
- `--ear-thresh 0.21` fixed threshold (used when not calibrating)
- `--frames 15` consecutive closed frames before `drowsy`
- `--stream-port 8000` enable the web view; leave it out (or add `--no-stream`) to turn it off, e.g. for clean fps tests
- `--mqtt-host localhost`, `--mqtt-port 1883`, `--no-mqtt` (print only)
- `--alerts-dir alerts` where drowsy JPEGs are saved (one on the change to `drowsy`, then every 3 s while drowsy)
- The console prints the rolling fps (last 30 frames) and the average since start once a second.

### sensors options
- `--mqtt-host localhost`, `--mqtt-port 1883`, `--no-mqtt`
- `--once` read once, print the JSON and exit (quick wiring check)
- `--no-distance` skip the HC-SR04; `--w1-dir DIR` read a fake 1-Wire folder (tests); `--quiet`

A failed read is sent as `null`. If the broker is down, both programs keep running,
drop messages, and reconnect on their own.

## Start on boot (systemd)

    cd ~/iot_term/pi_gateway
    sudo cp systemd/vision.service systemd/sensors.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now vision.service sensors.service

    systemctl status vision sensors          # are they running?
    journalctl -u vision -f                  # live log (Ctrl-C to stop)
    sudo systemctl restart vision            # after a deploy
    sudo systemctl disable --now vision      # stop using it on boot

vision runs `/home/bum/.local/bin/uv run --frozen ...`, so run `uv sync` once by hand first.
Stop the service before running vision by hand: only one program can use the camera.

## Tests (Mac or Pi)

    uv run pytest

The tests cover the driver state machine, rolling fps, payload building, the MQTT
publisher (no broker, and a stub broker), and `w1_slave` parsing. They import only pure
code (`drowsiness/logic.py`, `drowsiness/mqtt.py`, `sensors.py`), not the camera or MediaPipe.
