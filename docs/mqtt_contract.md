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
| `car/node/air` | ESP32 | server.py | 1 Hz | no | Cabin air quality (CO₂) and noise level |
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
{"ts": 0, "co2": 820, "sound": 14.2, "loud": false}
```
- `co2` in ppm. For an MQ-135, it's an estimate; also send `co2_raw` (ADC counts).
- `sound` = mean absolute deviation of the mic ADC over a 20 ms window (same as commit `f567fad`).
- `loud` = the existing loud-trigger result (5× background).

### `car/gateway/cabin`
```json
{"ts": 1764140000.1, "temp": 31.4, "distance": 48.0}
```
- `temp` in °C (DS18B20), `distance` in cm (HC-SR04). Send `null` for a failed read.

### `car/vision/driver`
```json
{"ts": 1764140000.5, "ear": 0.27, "thresh": 0.21, "state": "open", "closed_frames": 0, "fps": 14.6, "snapshot": null}
```
- `state`: `open` | `closed` | `drowsy` | `no_face`.
- `snapshot`: absolute path on the Pi of the saved JPEG, only on the message where `state` becomes `drowsy`; otherwise `null`.

### `car/cmd/alert`
```json
{"ts": 1764140000.6, "level": "danger", "reason": "drowsy"}
```
- `level`: `ok` | `warning` | `danger`.
- `reason`: `none` | `drowsy` | `impact` | `co2` | `heat` | `too_close` | `no_face`.

## Alert rules (implemented in server.py)

| Level | LED | Buzzer | Triggers |
|---|---|---|---|
| `danger` | red | on (beeping) | `state == "drowsy"` · `impact == true` (hold 10 s) |
| `warning` | yellow | off | `co2 > 1500` ppm · `temp > 35` °C · `distance < 25` cm for 3 s · `no_face` for 5 s |
| `ok` | green | off | none of the above |

- The highest level wins. `reason` names the trigger with the highest level; if two triggers tie, `drowsy` wins.
- `danger` from `drowsy` clears 2 s after vision reports `open` again.
- Thresholds go at the top of `server.py` as constants, so they're easy to tune and show on a slide.

## InfluxDB mapping (bucket `car`)

| Topic | Measurement | Fields | Tags |
|---|---|---|---|
| `car/node/motion` | `motion` | ax, ay, az, gx, gy, gz, a_mag, impact | `source=esp32` |
| `car/node/air` | `air` | co2, sound, loud | `source=esp32` |
| `car/gateway/cabin` | `cabin` | temp, distance | `source=pi` |
| `car/vision/driver` | `driver` | ear, thresh, closed_frames, fps, drowsy (0/1) | `source=pi`, `state` |
| `car/cmd/alert` | `alert` | level_num (0/1/2), caption | `level`, `reason` |
