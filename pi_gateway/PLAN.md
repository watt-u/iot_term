# Pi 5 gateway — plan (milestone M3)

The gateway runs two programs that publish to the broker on the same Pi:

- **vision** (`drowsiness/`, already working): camera → MediaPipe Face Mesh → EAR → `car/vision/driver`.
- **sensors** (`sensors.py`, new): DS18B20 temperature and HC-SR04 distance → `car/gateway/cabin`.

Topics and payloads: [../docs/mqtt_contract.md](../docs/mqtt_contract.md). Deploy: `tools/deploy_pi.sh` from the Mac.

## Wiring (Raspberry Pi 5 header)

| Part | Module pin | Pi pin | Notes |
|---|---|---|---|
| Pi Camera | ribbon | CAM/DISP 0 | Already working with `rpicam-vid` |
| KY-001 (DS18B20) | + / − | 3V3 (pin 1) / GND (pin 9) | The KY-001 board has the 4.7k pull-up |
| | S | **GPIO 4** (pin 7) | Add `dtoverlay=w1-gpio` to `/boot/firmware/config.txt` and reboot |
| HC-SR04 | VCC / GND | 5V (pin 2) / GND (pin 6) | |
| | TRIG | **GPIO 23** (pin 16) | 3.3 V output is enough to trigger |
| | ECHO | **GPIO 24** (pin 18) **through a 1k / 2k divider** | ECHO is 5 V. Without the divider, it can damage the Pi. |

## Steps — vision (`drowsiness/`)

1. [ ] Add `paho-mqtt>=2` to `pyproject.toml`, and add `drowsiness/mqtt.py`, a small publisher that reconnects by itself.
2. [ ] In `main.py`, publish `car/vision/driver` at 2 Hz and at once on every state change (`open` / `closed` / `drowsy` / `no_face`).
3. [ ] Compute a **rolling fps** (last 30 frames) as well as the overall average, and send it in the payload.
   The current code prints only the average since startup.
4. [ ] When the state becomes `drowsy`, save the JPEG as now and put its absolute path in `snapshot`.
5. [ ] Add `--mqtt-host` (default `localhost`) and `--no-stream` (for clean fps tests).
6. [ ] Add a `systemd` unit (`pi_gateway/systemd/vision.service`) so the program starts on boot for the demo.

*Check:* `mosquitto_sub -t car/vision/driver -v` shows `drowsy` within about 1 s (15 frames at 15 fps) of closing your eyes.

## Steps — sensors (`sensors.py`)

Run this with the **system Python** (`/usr/bin/python3`), not the uv venv, so the Pi 5 GPIO libraries from apt just work:

```bash
sudo apt install python3-gpiozero python3-lgpio python3-paho-mqtt
```

1. [ ] DS18B20: read `/sys/bus/w1/devices/28-*/w1_slave` (no library needed). Retry once on a CRC error.
2. [ ] HC-SR04: `gpiozero.DistanceSensor(echo=24, trigger=23, max_distance=2)`. Use the median of 5 readings.
3. [ ] Publish `car/gateway/cabin` at 1 Hz. Send `null` for a failed read so the program never crashes.
4. [ ] Add a `systemd` unit (`pi_gateway/systemd/sensors.service`).

*Check:* hold the sensor in your hand and the temperature rises. Move a hand toward the ultrasonic and the distance drops.

## Done when
- Both topics flow for 10 minutes with the server stack running alongside.
- vision's fps with MQTT on is within 1 fps of before the change (so MQTT doesn't slow detection).
