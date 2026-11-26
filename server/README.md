# On-prem server

Runs on the Pi 5 (`g3pi.local`, user `bum`, folder `~/iot_term/server`):

- **Docker Compose:** Mosquitto (MQTT, `:1883`), InfluxDB 2.7 (`:8086`, bucket `car`), Grafana (`:3000`).
- **`server.py`** on the host (uv): `car/#` → InfluxDB, alert rules → `car/cmd/alert`, AI caption for drowsy snapshots.

Contract (topics, payloads, rules, InfluxDB mapping): [../docs/mqtt_contract.md](../docs/mqtt_contract.md). Plan: [PLAN.md](PLAN.md).

| File | What it does |
|---|---|
| `docker-compose.yml` | The three services, `restart: unless-stopped`, healthchecks. Data in `./data/` (gitignored). |
| `mosquitto/mosquitto.conf` | `listener 1883`, `allow_anonymous true`, persistence in `./data/mosquitto` (keeps the retained alert). |
| `grafana/provisioning/` | InfluxDB Flux datasource (token from `.env`) and the dashboard provider. |
| `grafana/dashboards/car.json` | The dashboard (provisioned, so it survives a rebuild). |
| `server.py` | MQTT ↔ InfluxDB wiring, 250 ms rules loop, thresholds at the top of the file. |
| `rules.py` | The alert rules as pure, clock-injected logic (tested in `tests/test_rules.py`). |
| `ai_caption.py` | Background captioner: Gemini, Claude or OpenAI over plain HTTPS. |
| `systemd/server.service` | Starts `server.py` at boot. |

## 1. Setup (once, on the Pi)

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER        # log out and back in afterwards
# uv (if it isn't installed yet)
curl -LsSf https://astral.sh/uv/install.sh | sh

cd ~/iot_term/server
cp .env.example .env
nano .env    # set INFLUX_TOKEN (openssl rand -hex 32), INFLUX_ADMIN_PASSWORD, AI_PROVIDER, AI_API_KEY
docker compose up -d
docker compose ps                     # all three should become "healthy" within ~30 s
```

InfluxDB reads `DOCKER_INFLUXDB_INIT_*` only on its first start (empty `./data/influxdb`). If you change
`INFLUX_TOKEN`, `INFLUX_ORG` or `INFLUX_BUCKET` later, either change them in the InfluxDB UI too or wipe
`./data/influxdb*` (this deletes all stored data).

To copy code from the Mac to the Pi: `tools/deploy_pi.sh` (it skips `.env` and `data/`).

## 2. Run server.py

```bash
cd ~/iot_term/server
uv sync
uv run python server.py              # Ctrl+C to stop
uv run python server.py --no-ai      # without AI captions
uv run python server.py --log-level DEBUG
```

It reads `./.env`; real environment variables win. Without `INFLUX_TOKEN` it still runs the rules and
publishes alerts, but writes nothing. Without `AI_API_KEY` every caption is `unavailable`.

What it logs: alert changes (`alert ok -> danger (drowsy)`), stale sources, and one line per AI call with its
latency and the running average (`caption ok provider=gemini ... latency=1.84s avg=1.92s n=5: ...`); use the
average on the slides.

### Behavior notes

- **ts:** `ts: 0` (ESP32), a missing ts, or one more than a day away from the Pi clock is replaced with the receive time.
- **Types:** numeric fields are always written as floats (`closed_frames`, `drowsy`, `level_num` as integers), so a sender that switches between `820` and `820.5` never causes an InfluxDB type conflict. `null` fields are skipped. Fields not in the contract table (e.g. `co2_raw`) are not stored.
- **Alerts:** evaluated every 250 ms and right after each `car/vision/driver` message. `car/cmd/alert` is published retained with QoS 1 on change and every 2 s (only while connected, so no burst of old alerts after a reconnect). Only *changes* are written to the `alert` measurement, so the events table lists events, not heartbeats.
- **Stale:** a source silent > 5 s triggers nothing (no danger, no warning) and its held state (drowsy latch, impact hold, 3 s / 5 s timers) is dropped. The dashboard's *Sources* panel turns red for it.
- **Distance:** a failed read (`null`) restarts the 3 s too-close window.
- **Caption:** written to the `alert` measurement with the same time and tags as the drowsy alert event, so it lands on the same row in the events table.
- **AI providers:** `AI_PROVIDER=gemini|anthropic|openai`, `AI_MODEL` empty = default (`gemini-2.5-flash`, `claude-opus-5-5`, `gpt-4.1-mini`). The Anthropic call sends the `server-side-fallback-2026-07-01` beta (`fallbacks: "default"`), which retries a refused request on another model; remove the header and field in `ai_caption.py` if your key rejects the beta.

## 3. Start at boot (systemd)

The Docker services restart by themselves (`restart: unless-stopped`). For `server.py`:

```bash
cd ~/iot_term/server && uv sync      # the service runs with --frozen, so sync once first
sudo cp systemd/server.service /etc/systemd/system/car-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now car-server
systemctl status car-server
journalctl -u car-server -f
```

The unit expects uv at `/home/bum/.local/bin/uv` (`which uv` to check; edit `ExecStart` if it differs).

## 4. Smoke tests

Install the clients: `sudo apt install mosquitto-clients` (Pi) or `brew install mosquitto` (Mac).

```bash
# M1: broker reachable from the Mac
mosquitto_sub -h g3pi.local -t 'car/#' -v                 # Mac, leave running
mosquitto_pub -h localhost -t car/test -m hi              # Pi → the Mac prints "car/test hi"

# Current alert (retained: arrives at once)
mosquitto_sub -h g3pi.local -t car/cmd/alert -v

# Fake a drowsy driver → danger within 250 ms, back to ok 2 s after "open"
mosquitto_pub -h g3pi.local -t car/vision/driver -m '{"ts":0,"ear":0.12,"thresh":0.21,"state":"drowsy","closed_frames":30,"fps":14.8,"snapshot":null}'
mosquitto_pub -h g3pi.local -t car/vision/driver -m '{"ts":0,"ear":0.30,"thresh":0.21,"state":"open","closed_frames":0,"fps":14.8,"snapshot":null}'

# Impact → danger held 10 s (keep motion fresh, or it goes stale after 5 s)
mosquitto_pub -h g3pi.local -t car/node/motion -m '{"ts":0,"ax":2.1,"ay":1.5,"az":1.2,"gx":0,"gy":0,"gz":0,"a_mag":2.85,"impact":true}'

# Warnings
mosquitto_pub -h g3pi.local -t car/node/air -m '{"ts":0,"co2":1800,"sound":12.0,"loud":false}'
mosquitto_pub -h g3pi.local -t car/gateway/cabin -m '{"ts":0,"temp":36.5,"distance":48.0}'

# AI caption: on the Pi, with a real JPEG
mosquitto_pub -h localhost -t car/vision/driver -m '{"ts":0,"ear":0.1,"thresh":0.21,"state":"drowsy","closed_frames":30,"fps":15,"snapshot":"/home/bum/iot_term/pi_gateway/alerts/test.jpg"}'
journalctl -u car-server -n 20       # look for "caption ok ..." or "caption unavailable ..."
```

InfluxDB check: `http://g3pi.local:8086` (admin user from `.env`) → Data Explorer → bucket `car`.

## 5. Dashboard

**http://g3pi.local:3000** (anonymous viewers can open it; admin login from `.env` to edit).
The *Car drowsiness detector* dashboard is the home page and refreshes every 1 s; use the time picker for history.

- Row 1: driver state, alert level and reason, fps, CO₂, cabin temp, seconds since each source last sent data.
- Row 2: EAR with threshold, distance (red below 25 cm), accel magnitude (2.5 g line), sound, CO₂ (1500 ppm), temp (35 °C).
- Row 3: alert events with the AI caption.
- Collapsed row: live camera from `http://g3pi.local:8000` (needs the vision MJPEG stream running).

Edits made in the Grafana UI are lost when the container is recreated. To keep them: Dashboard → Share → Export →
*Save to file*, and replace `grafana/dashboards/car.json`.

## 6. Tests (Mac or Pi)

```bash
cd server
uv run pytest
docker compose --env-file .env.example config >/dev/null && echo compose OK
```
