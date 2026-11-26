# MQTT contract

Every part follows this file. If you change a topic or a field, change it here first.

- **Broker:** Mosquitto on the Pi, `g3pi.local:1883`, no TLS (local hotspot only).
- **Payloads:** JSON, UTF-8. Every message has `ts` (Unix seconds, float) set by the sender.
  The ESP32 has no real clock, so it sends `ts: 0`. `server.py` replaces 0 with its own receive time.
- **QoS 0** for sensor data (drops are fine), **QoS 1** for `car/cmd/alert`.

## Topics

| Topic | Publisher | Subscriber | Rate | Retain | Purpose |
|---|---|---|---|---|---|
| `car/node/motion` | ESP32 | server.py | 5 Hz, plus immediately on impact | no | Crash or hard-braking detection from the IMU |
| `car/node/air` | ESP32 | server.py | 1 Hz | no | Cabin smoke/gas (MQ-2) and cabin light (LDR) |
| `car/gateway/cabin` | sensors.py (Pi) | server.py | 1 Hz | no | Cabin heat and driver posture (head-to-wheel distance) |
| `car/vision/driver` | vision (Pi) | server.py | 2 Hz, plus immediately on a state change | no | Drowsiness result from the camera |
| `car/cmd/alert` | server.py | ESP32 | on change, plus every 2 s | **yes** | Tells the ESP32 what to show on the buzzer and LED |

`car/cmd/alert` is retained, so a rebooted ESP32 gets the current level right away.

## Payloads

### `car/node/motion`
```json
{"ts": 0, "ax": 0.01, "ay": -0.02, "az": 1.00, "gx": 0.4, "gy": -0.1, "gz": 0.0, "a_mag": 1.00, "impact": false}
```
- `a*` in g, `g*` in deg/s. `a_mag` = √(ax² + ay² + az²).
- `impact` = true when `a_mag` > 2.5 g. On impact, publish at once and don't wait for the 5 Hz tick.

### `car/node/air`
```json
{"ts": 0, "smoke": 42, "smoke_raw": 512, "light": 63.5, "light_raw": 1495, "dark": false}
```
- `smoke` = MQ-2 smoke estimate in ppm (smoke curve of the datasheet, R0 calibrated in clean air at boot). It's an estimate: the MQ-2 also reacts to LPG, propane, H₂ and alcohol. `null` during the first ~30 s (heater warm-up + calibration) or when the signal is out of range.
- `smoke_raw` = MQ-2 ADC counts (0–4095, after the 10k/20k divider). Always sent once the first read is done.
- `light` = cabin light from the LDR module, 0–100 % (0 = dark), averaged over the last second. `light_raw` = ADC counts.
- `dark` = true when `light` < 15 %, and false again above 25 % (hysteresis). `light`/`dark` are `null` only if no sample was taken.

### `car/gateway/cabin`
```json
{"ts": 1764140000.1, "temp": 31.4, "distance": 48.0}
```
- `temp` in °C (DS18B20), `distance` in cm (HC-SR04). Send `null` for a failed read. A DS18B20 reading of exactly 85.0 °C is its power-on reset value and is sent as `null`.

### `car/vision/driver`
```json
{"ts": 1764140000.5, "ear": 0.27, "thresh": 0.21, "state": "open", "closed_frames": 0, "fps": 14.6, "snapshot": null}
```
- `state`: `open` | `closed` | `drowsy` | `no_face`. `ear` is `null` when `state` is `no_face`.
- `snapshot`: absolute path on the Pi of the saved JPEG **without** the on-screen overlay (`*_raw.jpg`), only on the message where `state` becomes `drowsy`; otherwise `null`.

### `car/cmd/alert`
```json
{"ts": 1764140000.6, "level": "danger", "reason": "drowsy"}
```
- `level`: `ok` | `warning` | `danger` | `offline`.
- `reason`: `none` | `drowsy` | `impact` | `smoke` | `heat` | `too_close` | `no_face` | `server_offline`.
- **Change vs. heartbeat:** server.py publishes on every change and re-sends the current level every 2 s. Only changes are written to InfluxDB.
- **Offline:** server.py sets a retained last will `{"level": "offline", "reason": "server_offline"}` on this topic and publishes it on a clean shutdown. The ESP32 blinks blue (buzzer off) on `offline`, and also when no alert has arrived for 6 s.

## Alert rules (implemented in server.py)

| Level | LED | Buzzer | Triggers |
|---|---|---|---|
| `danger` | red | on (beeping) | `state == "drowsy"` · `impact == true` (hold 10 s) |
| `warning` | yellow | off | `smoke > 300` ppm · `temp > 35` °C · `distance < 25` cm for 3 s · `no_face` for 5 s |
| `ok` | green | off | none of the above |

- The highest level wins. `reason` names the trigger with the highest level; if two triggers tie, `drowsy` wins.
- `danger` from `drowsy` clears 2 s after vision reports `open` again.
- Thresholds go at the top of `server.py` (in `rules.py`) as constants, so they're easy to tune and show on a slide.
- A source silent for more than 5 s is **stale**: it triggers nothing (not even a warning), and its held state (drowsy latch, impact hold, 3 s / 5 s timers) is dropped.

## InfluxDB mapping (bucket `car`)

| Topic | Measurement | Fields | Tags |
|---|---|---|---|
| `car/node/motion` | `motion` | ax, ay, az, gx, gy, gz, a_mag, impact | `source=esp32` |
| `car/node/air` | `air` | smoke, smoke_raw, light, light_raw, dark | `source=esp32` |
| `car/gateway/cabin` | `cabin` | temp, distance | `source=pi` |
| `car/vision/driver` | `driver` | ear, thresh, closed_frames, fps, drowsy (0/1) | `source=pi`, `state` |
| `car/cmd/alert` | `alert` | level_num (0/1/2), caption | `level`, `reason` |
