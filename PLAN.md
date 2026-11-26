# Car Drowsiness Detector — Grand Plan

**Goal:** A camera on a Raspberry Pi 5 watches the driver's eyes. When the driver gets drowsy, the system
sounds a buzzer, turns a status LED red, logs the event, and stores an AI description of the snapshot.
Sensors on an ESP32-S3 and the Pi add context: crash, air quality, cabin heat, cabin noise, and driver posture.

**Deadline:** slides and video are due in myCourseVille by **Wed Dec 2, 2026, 09:00**.
The internal target is **Tue Dec 1, 22:00**, so there is a night of slack.

**Architecture diagram:** https://claude.ai/artifact/5wnFq5haWgxH43k8uGPspP

---

## Repo layout

| Folder | What it is | Plan |
|---|---|---|
| `esp32_node/` | ESP32-S3 sensor node firmware (PlatformIO) | [esp32_node/PLAN.md](esp32_node/PLAN.md) |
| `pi_gateway/` | Pi 5 gateway: camera drowsiness detection (`drowsiness/`) and Pi sensors | [pi_gateway/PLAN.md](pi_gateway/PLAN.md) |
| `server/` | On-prem server on the Pi: Docker (Mosquitto, InfluxDB, Grafana) and `server.py` | [server/PLAN.md](server/PLAN.md) |
| `docs/` | Shared contract, evaluation, slides and video | see below |
| `tools/` | `serial_capture.py` (ESP32 serial), `deploy_pi.sh` (rsync to the Pi) | — |

Shared docs:
- [docs/mqtt_contract.md](docs/mqtt_contract.md): topics, payloads and alert rules. **Every part follows this contract.**
- [docs/evaluation.md](docs/evaluation.md): fps, accuracy and qualitative cases (criterion 9).
- [docs/presentation.md](docs/presentation.md): slide outline, video storyboard, submission checklist (14–15).

---

## Milestones

Each milestone has a "done when" test you can check in a few minutes.
M2 and M3 only depend on M1, so two people can do them at the same time.

| # | When | Milestone | Done when |
|---|---|---|---|
| **M0** | Thu Nov 26 | **Plan and repo layout** | This file and the part plans exist. CO₂ sensor model confirmed. |
| **M1** | Thu 26 – Fri 27 | **Backbone:** network, broker, database and dashboard running on the Pi | `mosquitto_sub -h g3pi.local -t 'car/#' -v` on the Mac shows a test message. Grafana opens at `http://g3pi.local:3000`. |
| **M2** | Fri 27 | **ESP32 node:** sensors publish, alerts drive the buzzer and LED | `car/node/motion` and `car/node/air` arrive at the expected rates. `mosquitto_pub -t car/cmd/alert -m '{"level":"danger"}'` makes the buzzer sound and the LED turn red. |
| **M3** | Fri 27 – Sat 28 | **Pi gateway:** vision and Pi sensors publish | `car/vision/driver` shows EAR, state and fps. `car/gateway/cabin` shows temp and distance. |
| **M4** | Sat Nov 28 | **Server and dashboard:** storage, rules and Grafana | Closing your eyes turns the LED red within 1 s. Grafana shows live panels and the last 24 h. |
| **M5** | Sun Nov 29 | **AI caption and full integration** | A drowsy event shows an AI caption in Grafana's events table. The full demo runs for 10 min with no restarts. Raw demo footage recorded. |
| **M6** | Mon Nov 30 | **Evaluation** | The tables in `docs/evaluation.md` are filled in, and 3 success and 3 failure frames are picked. |
| **M7** | Tue Dec 1 | **Slides and video** | Slides cover 14.1–14.5. The video is about 5 min. Both are uploaded before 22:00. |

### Order of work inside each milestone
- **M1:** network decision (below) → Docker install on the Pi → `server/docker-compose.yml` → smoke test.
- **M2:** Wi-Fi and MQTT → MPU6050 (reuse the current test) → mic (reuse the code from commit `f567fad`) → CO₂ → alert subscriber → buzzer and LED.
- **M3:** MQTT publish inside `drowsiness/main.py` → wire the DS18B20 and ultrasonic → `sensors.py`.
- **M4:** `server.py` writing to InfluxDB → rules → `car/cmd/alert` → Grafana dashboard (exported to JSON in `server/grafana/`).
- **M5:** AI caption → end-to-end test → mount the rig (car or desk mock-up) → record footage.

---

## Requirement map (25 points)

| # | Requirement | How we meet it | Milestone |
|---|---|---|---|
| 1 | ≥ 5 sensor types | Camera, IMU, sound, CO₂, temperature, ultrasonic (6) | M2, M3 |
| 2 | ≥ 1 I2C sensor | MPU6050 on the ESP32 (SDA 10 / SCL 9) | M2 |
| 3 | ≥ 2 sensor-node sensors | ESP32: MPU6050, microphone, CO₂ | M2 |
| 4 | ≥ 2 gateway sensors | Pi: camera, KY-001 temperature, ultrasonic | M3 |
| 5 | ≥ 1 actuator | KY-012 buzzer and KY-016 RGB LED (see risks) | M2 |
| 6 | Camera / video stream | Pi camera through `rpicam-vid`, MJPEG stream on :8000 | done |
| 7.1 | OpenCV / pretrained model | MediaPipe Face Mesh landmarks → eye aspect ratio | done |
| 7.2 | AI service | Cloud vision API describes each drowsy snapshot | M5 |
| 8 | Image output changes behavior | Drowsy → `car/cmd/alert` → buzzer and red LED, logged to InfluxDB | M4 |
| 9.1 | fps and accuracy | `docs/evaluation.md` trials | M6 |
| 9.2 | Success and failure cases | Saved alert frames, picked cases | M6 |
| 10 | MQTT, ≥ 3 topics, explained | 5 topics in `docs/mqtt_contract.md` | M1–M4 |
| 11 | On-prem or cloud server | `server.py` and Mosquitto on the Pi | M4 |
| 12 | Time-series DB | InfluxDB 2 | M1, M4 |
| 13 | Dashboard, live and history | Grafana (refresh every 1–5 s, plus time range picker) | M4 |
| 14 | Slides | `docs/presentation.md` | M7 |
| 15 | Video about 5 min | `docs/presentation.md` storyboard | M5, M7 |

---

## Decisions

- **Network: a phone hotspot for everything.** The Pi, ESP32 and laptop all join one phone hotspot. This works in a car and gives the AI call internet. The Pi can't easily be a hotspot and a Wi-Fi client at once.
- **Broker address:** the ESP32 finds the Pi by mDNS (`g3pi.local`) and falls back to a fixed IP set in `secrets.h`.
- **Server runs on the Pi** (on-premise). Mosquitto, InfluxDB and Grafana run in Docker. `server.py` runs on the host with `uv`.
- **Alert decisions happen only in `server.py`.** The ESP32 and `vision.py` report data. Only the server publishes `car/cmd/alert`, so all rules live in one place.
- **Mic is a KY-037/038 analog module** on GPIO 4 (found in commit `f567fad`).

## Open questions

- [ ] **CO₂ sensor model:** MQ-135 (analog, 5 V heater, estimates only), MH-Z19 (UART), or SCD40/SCD41 (I2C)? This sets the wiring and code in M2.
- [ ] **AI provider:** Gemini, Claude or OpenAI vision. Pick whichever the team already has an API key for.
- [ ] **Demo setting:** a real parked car, or a desk mock-up with a steering wheel prop?
- [ ] **Team split:** who owns ESP32, Pi gateway, server and dashboard, and slides and video?

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Graders don't count a buzzer as an actuator ("motor, pump, etc.") | −1 point | Ask the TA early. Backup: a cheap vibration motor (a seat or wheel buzz) with a transistor. |
| Pi CPU is overloaded by MediaPipe plus Docker | Low fps | Keep the camera at 640×480 and 15 fps, turn the MJPEG stream off during fps tests, and watch `htop`. |
| Dark cabin, sunglasses | Missed detections | Record these as qualitative failures (9.2). Mention NoIR camera plus IR LEDs as future work. |
| MQ-135 isn't a true CO₂ sensor | Weak data | Call it an "air quality index" on the slides and list it as a limitation. |
| Wi-Fi drops in the car | No alerts | The ESP32 reconnects automatically. On loss of MQTT for 5 s, the LED blinks blue. |
| Running out of time | Missed deadline | Record raw footage on M5 (Sun), not on the last day. Slides start in parallel on M6. |
