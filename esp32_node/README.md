# ESP32-S3 sensor node

The firmware for the car drowsiness detector's sensor node. It reads an MPU6050, a KY-037/038 mic and a CO₂ sensor,
publishes `car/node/motion` (5 Hz, plus at once on impact) and `car/node/air` (1 Hz), and drives a KY-016 RGB LED
and KY-012 buzzer from `car/cmd/alert`. Topics and payloads: [../docs/mqtt_contract.md](../docs/mqtt_contract.md).
Plan and steps: [PLAN.md](PLAN.md).

## Wiring (ESP32-S3 DevKitC-1 N16R8)

| Part | Pins |
|---|---|
| MPU6050 | SDA **GPIO 10**, SCL **GPIO 9**, 3V3, GND (I2C 0x68) |
| Mic KY-037/038 | AO **GPIO 4**, + 3V3, G GND |
| CO₂ MQ-135 | AO → 10k/20k divider → **GPIO 6**, VCC 5V |
| CO₂ MH-Z19 | sensor TX → **GPIO 17**, sensor RX ← **GPIO 18**, 5V |
| CO₂ SCD40 | same I2C bus as the MPU6050 (0x62), 3V3 |
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

## CO₂ model

Set `CO2_SENSOR` in `src/config.h` to `CO2_MQ135` (the default), `CO2_MHZ19` or `CO2_SCD40`. You can also override it
in `platformio.ini` with `build_flags = ... -DCO2_SENSOR=CO2_SCD40`.

- **MQ-135:** sends an estimated `co2` and `co2_raw` (ADC counts). R0 calibrates itself in the first 10 s after
  boot and assumes fresh air (420 ppm). The value is printed as `[co2] MQ-135 R0 = ...`. Put it in `MQ135_R0_KOHM`
  to make readings repeatable. Check `MQ135_RL_KOHM` (the module's load resistor) as well.
- A missing or failed sensor sends `"co2": null` and doesn't block anything.

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
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -q 1 -m '{"level":"warning","reason":"co2"}'   # yellow
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -q 1 -m '{"level":"danger","reason":"test"}'   # red + beeping

# Clear the retained alert when you're done
mosquitto_pub -h g3pi.local -t car/cmd/alert -r -n
```

- **Impact:** tap the board hard. A `car/node/motion` message with `"impact":true` shows up at once.
- **Loud:** clap near the mic. The next `car/node/air` message has `"loud":true`.
- **Fail-safe:** stop Mosquitto (`docker compose stop mosquitto` on the Pi). After 5 s the LED blinks blue and the
  buzzer stops. Start it again and the node reconnects and picks up the retained alert.

## Behavior notes

- `ts` is always `0`, because the node has no clock. `server.py` fills in the receive time.
- `sound` is the loudest 20 ms window (mean absolute deviation) of the last second, and `loud` is true if the
  loud trigger fired at any point in that second. This way a short clap isn't missed by the 1 Hz message.
- Gyro calibration takes about 2 s at boot, so keep the board still. If it keeps moving, the node accepts the bias
  after 5 tries. `car/node/motion` starts once calibration is done. A missing MPU6050 is retried every 5 s.
- Before the first alert arrives, the LED is off. The onboard RGB LED (GPIO 48) mirrors the KY-016.
