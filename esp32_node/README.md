# ESP32-S3 sensor node

The firmware for the car drowsiness detector's sensor node. It reads an MPU6050, an MQ-2 smoke sensor and an LDR light module,
publishes `car/node/motion` (5 Hz, plus at once on impact) and `car/node/air` (1 Hz), and drives a KY-016 RGB LED
and KY-012 buzzer from `car/cmd/alert`. Topics and payloads: [../docs/mqtt_contract.md](../docs/mqtt_contract.md).
Plan and steps: [PLAN.md](PLAN.md).

## Wiring (ESP32-S3 DevKitC-1 N16R8)

| Part | Pins |
|---|---|
| MPU6050 | SDA **GPIO 10**, SCL **GPIO 9**, 3V3, GND (I2C 0x68) |
| LDR light module | AO **GPIO 4**, VCC 3V3, GND (DO unused) |
| Smoke MQ-2 | AO → 10k → **GPIO 6**, GPIO 6 → 20k → GND, VCC 5V (DO unused) |
| Buzzer KY-012 | S **GPIO 12** (HIGH = sound) |
| RGB LED KY-016 | R **GPIO 13**, G **GPIO 14**, B **GPIO 21**, − GND (common cathode) |

All pins are in `src/config.h`.

## Secrets

```bash
cp src/secrets.example.h src/secrets.h   # gitignored
```

Fill in `WIFI_SSID`, `WIFI_PASS` and `MQTT_FALLBACK_IP` (the Pi's IP on the hotspot). The node looks up
`MQTT_HOST_NAME` (`g3pi`) over mDNS first and uses the fallback IP if that fails. Without `secrets.h`, the build
still works. It prints a `#warning` and uses the placeholder values, so the board won't connect.

## Sensors

- **MQ-2 (smoke):** the heater warms up for 20 s, then R0 is calibrated for 10 s, assuming clean air
  (Rs/R0 = 9.83). Until then `smoke` is `null`, but `smoke_raw` (ADC counts) is already sent. The value is printed
  as `[smoke] MQ-2 R0 = ...`; put it in `MQ2_R0_KOHM` to skip calibration and make readings repeatable. Check
  `MQ2_RL_KOHM` (the module's load resistor, often 1k "102") too. Out-of-range signal (unplugged, no 5 V, no
  divider) sends `"smoke": null` and doesn't block anything. The MQ-2 needs a few minutes (best: 24 h burn-in)
  before it is stable.
- **LDR module:** `light` is 0–100 % (0 = dark), averaged over each second, and `dark` flips below 15 % and back
  above 25 %. Most LM393 boards give a high AO in the dark; if your `light` goes *down* when you shine a torch on
  it, set `LDR_DARK_IS_HIGH` to 0 in `src/config.h`.

## Build and flash

Run these from `esp32_node/` (`pio` isn't on PATH):

```bash
~/.platformio/penv/bin/pio run                    # build
~/.platformio/penv/bin/pio run -t upload          # build + flash
~/.platformio/penv/bin/python ../tools/serial_capture.py --seconds 15 --reset   # boot log
```

The serial log runs at 115200. It prints boot info, an I2C scan, Wi-Fi and MQTT connect and reconnect messages,
and a `[status]` line every 5 s.

## Manual tests

```bash
# Watch everything the node sends
mosquitto_sub -h g3pi.local -t 'car/#' -v

# Alert levels (retained, like server.py sends them)
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -q 1 -m '{"level":"ok","reason":"none"}'       # green
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -q 1 -m '{"level":"warning","reason":"smoke"}' # yellow
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -q 1 -m '{"level":"danger","reason":"test"}'   # red + beeping

# Clear the retained alert when you're done
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -n
```

- **Impact:** tap the board hard. A `car/node/motion` message with `"impact":true` shows up at once.
- **Light:** cover the LDR with your hand. Within a second `light` drops and `dark` becomes `true`.
- **Smoke:** after warm-up, hold a just-blown-out match or an unlit lighter (press the gas) near the MQ-2. `smoke` rises.
- **Fail-safe:** stop Mosquitto (`docker compose stop mosquitto` on the Pi). After 5 s the LED blinks blue and the
  buzzer stops. Start it again and the node reconnects and picks up the retained alert.

## Behavior notes

- `ts` is always `0`, because the node has no clock. `server.py` fills in the receive time.
- `smoke` is read once a second (16-sample average); `light` is sampled at 5 Hz and averaged into the 1 Hz message.
- Gyro calibration takes about 2 s at boot, so keep the board still. If it keeps moving, the node accepts the bias
  after 5 tries. `car/node/motion` starts once calibration is done. A missing MPU6050 is retried every 5 s.
- Before the first alert arrives, the LED is off. The onboard RGB LED (GPIO 48) mirrors the KY-016.
