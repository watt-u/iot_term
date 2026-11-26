# Slides and video — plan (milestone M7, criteria 14–15)

**Due in myCourseVille: Wed Dec 2, 2026, 09:00.** Target upload: Tue Dec 1, 22:00.

## Slide outline (about 14 slides)

| # | Slide | Content | Criterion |
|---|---|---|---|
| 1 | Title | Project name, team, course | — |
| 2 | Problem | Drowsy driving and road deaths (cite a WHO or Thai road-safety figure) | 14.1 |
| 3 | Objectives and SDGs | 3 objectives. **SDG 3.6** (halve road traffic deaths), **SDG 11.2** (safe transport), **SDG 9** (innovation) | 14.1 |
| 4 | System architecture | The diagram from the artifact, with the alert path highlighted | 14.2 |
| 5 | Hardware | Photo of the rig. Sensor node vs. gateway sensors, and the I2C bus | 1–5 |
| 6 | Inputs and outputs | Table: each sensor → what it measures → which rule it feeds. Outputs: buzzer, LED, dashboard, AI caption | 14.3 |
| 7 | MQTT topics | The 5 topics and the purpose of each (from `mqtt_contract.md`) | 10 |
| 8 | Image processing | Face Mesh landmarks → EAR formula → threshold, 15 frames → drowsy. Screenshot with landmarks | 6, 7.1, 8 |
| 9 | AI service | A snapshot with its AI caption. Why a cloud model: a second opinion and a human-readable log | 7.2 |
| 10 | Server, database, dashboard | Mosquitto → server.py → InfluxDB → Grafana. Live and history screenshots | 11–13 |
| 11 | Evaluation: numbers | fps table, accuracy table, latency | 9.1 |
| 12 | Evaluation: cases | 3 successes and 3 failures, with images | 9.2 |
| 13 | Strengths and limitations | Strengths: low cost, works offline, context from several sensors. Limitations: no IR, sunglasses, MQ-135 is approximate, single camera | 14.4 |
| 14 | Commercial comparison | Table below | 14.5 |
| 15 | Conclusion and future work | IR camera, yawn detection, head pose, phone push alerts | — |

### Commercial comparison (check each claim against the maker's page before putting it on a slide)

| System | How it detects | Cost / availability | Compared with ours |
|---|---|---|---|
| Mercedes-Benz ATTENTION ASSIST | Steering-input patterns over time | Built into new cars | No camera. Ours sees the eyes directly but needs light. |
| Subaru DriverFocus | Infrared camera, face recognition | Built into new cars | IR works at night. Ours has no IR. |
| Volvo Driver Alert Control | Camera on lane-keeping behavior | Built into new cars | Indirect. Ours watches the driver. |
| Aftermarket dash cams with DMS | Infrared camera, eye/face AI | Paid aftermarket device | Similar idea. Ours adds cabin air, heat, crash and history. |

## Video storyboard (about 5 min)

| Time | Shot | What to show |
|---|---|---|
| 0:00–0:20 | Hook | A sleepy driver close-up → buzzer sounds, red LED |
| 0:20–0:50 | Problem and goal | Voice-over and title cards, SDG icons |
| 0:50–1:40 | Hardware tour | Close-ups of the ESP32 with its sensors and the Pi with the camera; label each part on screen |
| 1:40–2:20 | Architecture | Animated or annotated diagram; follow one alert through the topics |
| 2:20–3:30 | Live demo | Split screen: driver camera + Grafana. Close eyes → alert. Breathe on CO₂ → warning. Tap the IMU → impact. Lean in → too close |
| 3:30–4:00 | AI caption | Grafana events table showing the caption |
| 4:00–4:40 | Evaluation | fps and accuracy numbers, success and failure clips |
| 4:40–5:00 | Wrap-up | Strengths, limitations, team |

**Quality checklist (15.2):** record at 1080p; use a clip-on or phone mic for the voice-over (not the laptop mic);
record the screen with Grafana in full screen at 100% zoom; add captions for key numbers.
Record raw demo footage on **Sun Nov 29**, not on the last day.

## Submission checklist
- [ ] Slides exported to PDF and uploaded to myCourseVille
- [ ] Video uploaded (check the file size limit, or use an unlisted YouTube link if allowed)
- [ ] Both uploaded before Dec 2, 09:00 (target: Dec 1, 22:00)
- [ ] Repo tagged `v1.0-submission`
