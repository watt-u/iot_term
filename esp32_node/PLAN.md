# ESP32 sensor node — plan (milestone M2)

The sensor node reads 3 sensors (MPU6050, MQ-2, LDR), publishes them over MQTT, and drives the buzzer and LED from `car/cmd/alert`.
Topics and payloads: [../docs/mqtt_contract.md](../docs/mqtt_contract.md). Build and flash commands: [../AGENTS.md](../AGENTS.md).

## Wiring (ESP32-S3 DevKitC-1 N16R8)

| Part | Module pin | ESP32 pin | Notes |
|---|---|---|---|
| MPU6050 | VCC / GND | 3V3 / GND | |
| | SDA / SCL | **GPIO 10 / GPIO 9** | I2C address 0x68 (AD0 low). Already working. |
| LDR light module | VCC / GND | 3V3 / GND | 3V3 keeps AO under 3.3 V, no divider needed |
| | AO | **GPIO 4** (ADC1) | DO unused |
| Smoke (MQ-2) | VCC / GND | 5V / GND | Heater needs 5 V (~150 mA) and a warm-up; 24 h burn-in for stable readings |
| | AO | **GPIO 6** (ADC1) through a 10k/20k divider | AO can reach 5 V; the ESP32 ADC takes max 3.3 V. DO unused |
| Buzzer KY-012 | S / − | **GPIO 12** / GND | Active buzzer: HIGH = sound. If it's quiet, drive it from 5 V through an NPN transistor. |
| RGB LED KY-016 | R / G / B / − | **GPIO 13 / 14 / 21** / GND | Common cathode. Yellow = R + G. Use `ledcWrite` (PWM) to balance colors. |

Pins to avoid on this board: **19 and 20** (native USB, which carries the serial port), **26–37** (flash and octal PSRAM),
**0, 3, 45, 46** (strapping). **ADC2 pins don't work while Wi-Fi is on**, so analog inputs must use ADC1 (GPIO 1–10).

## Firmware structure

Keep it in a few small files under `src/`:

| File | Job |
|---|---|
| `main.cpp` | `setup()` and the `loop()` scheduler: non-blocking `millis()` timers, no `delay()` |
| `net.cpp/.h` | Wi-Fi connect and reconnect, mDNS lookup of `g3pi.local`, PubSubClient connect, subscribe, publish |
| `imu.cpp/.h` | MPU6050 raw I2C (move the code out of the current `main.cpp`), `a_mag`, impact flag |
| `light.cpp/.h` | LDR module: light %, dark flag with hysteresis |
| `smoke.cpp/.h` | MQ-2: warm-up, R0 calibration, smoke ppm estimate |
| `alert.cpp/.h` | Parse `car/cmd/alert` with ArduinoJson; set the LED color and buzzer pattern |
| `secrets.h` | Wi-Fi SSID, password, fallback broker IP. **Gitignored.** Commit a `secrets.example.h`. |
| `config.h` | Pins, rates and thresholds |

Libraries for `lib_deps`: `knolleary/PubSubClient`, `bblanchon/ArduinoJson@^7`. (MPU6050 stays raw I2C, no library.)

## Steps

1. [x] **Wi-Fi and MQTT.** Connect to the phone hotspot, find the broker, publish `{"hello":1}` to `car/node/air`.
   *Implemented, untested on hardware* (`net.cpp`). No separate hello message: the normal 1 Hz `car/node/air` message is the first thing you see.
   *Check:* `mosquitto_sub -h g3pi.local -t 'car/#' -v` shows it.
2. [x] **IMU.** Move the MPU6050 code into `imu.cpp`. Publish `car/node/motion` at 5 Hz.
   *Implemented, untested on hardware* (`imu.cpp`). Accel range is now ±8 g (±2 g could never reach the 2.5 g impact threshold).
   *Check:* tap the board hard; `impact: true` shows up.
3. [x] **Light (LDR).** Add `light`, `light_raw` and `dark` to `car/node/air`. (Replaced the microphone on 2026-11-26.)
   *Implemented, untested on hardware* (`light.cpp`).
   *Check:* cover the LDR; `dark: true` shows up.
4. [x] **Smoke (MQ-2).** Add `smoke` and `smoke_raw`. (Replaced the CO₂ sensor on 2026-11-26.)
   *Implemented, untested on hardware* (`smoke.cpp`).
   *Check:* after the 30 s warm-up, a blown-out match or unlit lighter gas near it makes `smoke` rise.
5. [x] **Alert subscriber.** Subscribe to `car/cmd/alert`. Green = ok, yellow = warning, red and beeping (200 ms on / 200 ms off) = danger.
   *Check:* `mosquitto_pub -h g3pi.local -t car/cmd/alert -r -m '{"level":"danger","reason":"test"}'`.
   *Implemented, untested on hardware* (`alert.cpp`, also mirrored on the onboard RGB LED).
6. [x] **Fail-safe.** If MQTT has been down for more than 5 s, blink blue and keep retrying. Serial prints each reconnect.
   *Check:* stop Mosquitto; the LED blinks blue; start it again and it recovers.
   *Implemented, untested on hardware.*

## Done when
- Both publish topics arrive at their rates for 10 minutes without a reset (watch with `serial_capture.py`).
- All three alert levels show correctly from a manual `mosquitto_pub`.
