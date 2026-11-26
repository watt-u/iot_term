# On-prem server — plan (milestones M1, M4, M5)

Runs on the Pi 5 next to the gateway programs:

- **Docker Compose:** Mosquitto (MQTT broker), InfluxDB 2 (time-series database), Grafana (dashboard).
- **`server.py`** on the host (uv): subscribes to `car/#`, writes every message to InfluxDB, applies the alert rules,
  publishes `car/cmd/alert`, and gets an AI caption for each drowsy snapshot.

Topics, payloads, rules and the InfluxDB mapping: [../docs/mqtt_contract.md](../docs/mqtt_contract.md).

## Planned files

```
server/
  docker-compose.yml
  .env.example            # INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET, AI_API_KEY (copy to .env; .env is gitignored)
  mosquitto/mosquitto.conf
  grafana/provisioning/   # datasource + dashboard provisioning
  grafana/dashboards/car.json
  pyproject.toml          # paho-mqtt, influxdb-client, the AI provider's SDK
  server.py               # rules engine + Influx writer + AI caption
  ai_caption.py
  systemd/server.service
```

## M1 — Backbone (Thu 26 – Fri 27)

1. [ ] Put the Pi, ESP32 and Mac on the phone hotspot. Check that `ping g3pi.local` works from the Mac.
2. [ ] Install Docker on the Pi: `curl -fsSL https://get.docker.com | sh`, then `sudo usermod -aG docker $USER`.
3. [x] Write `docker-compose.yml` with pinned image tags:
   - `eclipse-mosquitto:2`: port 1883; config has `listener 1883` and `allow_anonymous true`.
   - `influxdb:2.7`: port 8086, a volume for data, and `DOCKER_INFLUXDB_INIT_*` env to create the org, bucket `car` and token.
   - `grafana/grafana-oss` (pin a version): port 3000, with InfluxDB as a provisioned datasource (Flux).
   - `restart: unless-stopped` on all three, so they come back after a reboot.
4. [ ] Smoke test: on the Pi, run `mosquitto_pub -t car/test -m hi`. The Mac sees it with `mosquitto_sub -h g3pi.local -t 'car/#' -v`.
   Grafana opens at `http://g3pi.local:3000`, and InfluxDB at `:8086`.

## M4 — server.py and dashboard (Sat 28)

1. [x] **Writer:** subscribe to `car/#` and map each topic to a measurement (contract table). Use batched writes (`WriteOptions(batch_size=50, flush_interval=1000)`).
2. [x] **Rules:** keep the latest value from each source. Every 250 ms, compute `level` and `reason` with the contract rules.
   Publish `car/cmd/alert` (retained, QoS 1) on change and every 2 s. Also write it to the `alert` measurement.
3. [x] **Stale data:** if a source has been silent for more than 5 s, mark it offline in the dashboard. A silent source never triggers `danger`.
4. [x] **Grafana dashboard** (refresh 1 s for live, plus the time picker for history):
   - Row 1, now: driver state (stat panel: green, yellow, red), alert level, fps, smoke, cabin temp.
   - Row 2, time series: EAR with the threshold line, distance, accel magnitude, cabin light, smoke and temp.
   - Row 3, events: a table of alerts (time, level, reason, AI caption) from the `alert` measurement.
   - Optional: the live annotated camera from `http://g3pi.local:8000` in a text panel (needs `disable_sanitize_html`).
5. [x] Export the dashboard JSON to `grafana/dashboards/car.json` so it is provisioned and survives a rebuild.

*Check:* close your eyes and the LED turns red within 1 s. Grafana's last-24-h view still shows yesterday's test data.

## M5 — AI caption (Sun 29)

1. [x] When `car/vision/driver` arrives with a `snapshot` path, read the JPEG and send it to the vision AI API in a background thread, so the rules loop never waits.
   Prompt: *"This is a driver-facing car camera frame. In one sentence, describe the driver's alertness (eyes, head pose, yawning, phone use)."*
2. [x] Write the caption to InfluxDB (`alert` measurement, `caption` field) so it shows in the events table.
3. [x] On no internet or an API error, log it and store `caption = "unavailable"`. The local alert must never depend on the cloud.
4. [x] Note how long each call takes. The slides use the average AI latency.

## Done when
- `docker compose ps` shows 3 healthy services after a Pi reboot, and `server.py` starts by itself (systemd).
- The full demo loop works: eyes closed → red LED and buzzer → event row with caption in Grafana.
