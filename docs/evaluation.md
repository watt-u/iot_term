# Evaluation — plan and results (milestone M6, criterion 9)

Fill the tables in as you go. Keep the raw logs and frames in `docs/eval_data/`, and don't commit large video files.

## 9.1a — Speed (fps and latency)

**Method:** vision reports rolling fps in `car/vision/driver`, which is stored in InfluxDB. Run each setup for 5 minutes,
then read the mean and minimum from Grafana (or query InfluxDB).

| Setup | Resolution | Mean fps | Min fps | Pi CPU % (htop) |
|---|---|---|---|---|
| Vision only, no MJPEG stream | 640×480 | | | |
| Vision + MJPEG stream | 640×480 | | | |
| Full system (vision + stream + Docker + server.py + sensors.py) | 640×480 | | | |

**Alert latency** (eyes closed → buzzer sounds): film the face and the buzzer together with a phone at 60 fps,
and count frames from eyes shut to buzzer on. The design expects about 1.0 s (15 frames at 15 fps) plus under 0.2 s of MQTT hops.

| Trial | Latency (s) |
|---|---|
| 1–10 | |
| **Mean ± SD** | |

**AI caption latency:** the mean and max time per API call, from the `server.py` log.

## 9.1b — Accuracy

**Trial:** a 10-second window. The ground truth is what the subject was told to do. The detector "fires" if it publishes `drowsy` in the window.

- **Positive trials:** eyes closed for 3 s, either still or with the head slowly dropping.
- **Negative trials:** normal driving with blinks, a 2 s glance at the side mirror, talking, a quick nod.

**Plan:** 2+ subjects × 5 conditions × (10 positive + 10 negative) = 200+ trials.

| Condition | TP | FN | FP | TN | Accuracy | Precision | Recall |
|---|---|---|---|---|---|---|---|
| Good light, no glasses | | | | | | | |
| Dim light (cabin at dusk) | | | | | | | |
| Clear glasses | | | | | | | |
| Sunglasses | | | | | | | |
| Head turned about 30° | | | | | | | |
| **All** | | | | | | | |

Formulas: accuracy = (TP + TN) / all, precision = TP / (TP + FP), recall = TP / (TP + FN).

Also report the **calibrated EAR threshold** for each subject (from `--calibrate`) and the effect of changing `--frames`
(for example 10 vs. 15 vs. 20: fewer frames means faster alerts and more false alarms).

## 9.1c — Sensor sanity checks (short, one row each)

| Sensor | Test | Expected | Result |
|---|---|---|---|
| MPU6050 | Drop the board onto a cushion from 20 cm | `impact: true`, `a_mag` > 2.5 g | |
| Microphone | Clap 30 cm away | `loud: true` | |
| CO₂ | Breathe on it for 5 s | Clear rise above baseline | |
| KY-001 | Hold it in your hand for 30 s | Rises toward 30+ °C | |
| Ultrasonic | Hand at 20 / 40 / 60 cm (ruler) | Within ±2 cm | |

## 9.2 — Qualitative cases

Pick frames from `pi_gateway/alerts/` and screenshots of the MJPEG stream with landmarks drawn.

| # | Case | Result | Why | Image |
|---|---|---|---|---|
| S1 | Good light, eyes closed | ✅ detected | Clear landmarks, EAR well below the threshold | |
| S2 | Head dropping forward | ✅ detected | | |
| S3 | Clear glasses | ✅ / ❌ | | |
| F1 | Sunglasses | ❌ expected miss | The eyes can't be seen | |
| F2 | Dark cabin | ❌ expected miss | No IR; the face isn't found | |
| F3 | Looking at the mirror | ⚠️ possible false alarm | EAR drops when the eyes look sideways or down | |

These failures go into the slides' limitations section, with fixes as future work: an IR camera, a yawn (mouth aspect ratio) check, and head-pose estimation.
