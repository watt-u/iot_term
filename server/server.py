"""On-prem server: MQTT -> InfluxDB, alert rules, car/cmd/alert, AI captions.

Contract (topics, payloads, rules, InfluxDB mapping): ../docs/mqtt_contract.md

    uv run python server.py            # reads ./.env (see .env.example)
    uv run python server.py --no-ai    # skip the cloud caption

- Subscribes to car/#, writes every sensor message to InfluxDB (batched).
- Every 250 ms (and right away on each vision message) evaluates the rules in
  rules.py and publishes car/cmd/alert (retained, QoS 1) on change and every 2 s.
  Each change is also written to the `alert` measurement.
- When car/vision/driver carries a snapshot path, ai_caption.py captions it in a
  background thread and the caption is written to the `alert` measurement on the
  same row as the drowsy alert event.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable

from rules import ALERT_OK, TOPIC_SOURCE, Alert, RulesEngine, Thresholds

# ============================================================================
# Thresholds (docs/mqtt_contract.md -> "Alert rules"). Tune here.
# ============================================================================
CO2_WARN_PPM = 1500  # warning: co2 > 1500 ppm
TEMP_WARN_C = 35  # warning: cabin temp > 35 °C
DISTANCE_WARN_CM = 25  # warning: head-to-wheel distance < 25 cm ...
DISTANCE_HOLD_S = 3  # ... for 3 s
NO_FACE_HOLD_S = 5  # warning: no face for 5 s
IMPACT_HOLD_S = 10  # danger: held 10 s after an impact
DROWSY_CLEAR_S = 2  # danger from drowsy clears 2 s after vision reports "open"
STALE_S = 5  # a source silent > 5 s is stale (never triggers danger)

TICK_S = 0.25  # rules evaluation period
REPUBLISH_S = 2.0  # car/cmd/alert heartbeat

THRESHOLDS = Thresholds(
    co2_ppm=CO2_WARN_PPM,
    temp_c=TEMP_WARN_C,
    distance_cm=DISTANCE_WARN_CM,
    distance_hold_s=DISTANCE_HOLD_S,
    no_face_hold_s=NO_FACE_HOLD_S,
    impact_hold_s=IMPACT_HOLD_S,
    drowsy_clear_s=DROWSY_CLEAR_S,
    stale_s=STALE_S,
)

ALERT_TOPIC = "car/cmd/alert"
# Retained "offline" alert: set as the last will (broker sends it if server.py dies)
# and published on clean shutdown, so the ESP32 never keeps showing a stale level.
OFFLINE_PAYLOAD = '{"ts": 0, "level": "offline", "reason": "server_offline"}'
SUBSCRIBE_TOPIC = "car/#"
MAX_CLOCK_SKEW_S = 86400  # a sender ts further than this from our clock is replaced

log = logging.getLogger("server")

# ============================================================================
# InfluxDB mapping (docs/mqtt_contract.md -> "InfluxDB mapping")
# ============================================================================
FLOAT, INT, BOOL = "float", "int", "bool"

MEASUREMENTS: dict[str, tuple[str, dict[str, str], dict[str, str]]] = {
    # topic: (measurement, tags, {field: type})
    "car/node/motion": (
        "motion",
        {"source": "esp32"},
        {"ax": FLOAT, "ay": FLOAT, "az": FLOAT, "gx": FLOAT, "gy": FLOAT, "gz": FLOAT, "a_mag": FLOAT, "impact": BOOL},
    ),
    "car/node/air": ("air", {"source": "esp32"}, {"co2": FLOAT, "sound": FLOAT, "loud": BOOL}),
    "car/gateway/cabin": ("cabin", {"source": "pi"}, {"temp": FLOAT, "distance": FLOAT}),
    "car/vision/driver": (
        "driver",
        {"source": "pi"},
        {"ear": FLOAT, "thresh": FLOAT, "closed_frames": INT, "fps": FLOAT},
    ),
}
DRIVER_STATES = ("open", "closed", "drowsy", "no_face")


def _cast(value: Any, kind: str) -> Any:
    """Cast to a fixed Influx field type (a field's type can never change), or None."""
    if value is None:
        return None
    if kind == BOOL:
        return value if isinstance(value, bool) else None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(round(f)) if kind == INT else f


def point_time(payload: dict, recv_ts: float) -> float:
    """Sender ts, or the receive time when ts is 0 / missing / nonsense (ESP32 sends 0)."""
    ts = payload.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or ts <= 0:
        return recv_ts
    if abs(ts - recv_ts) > MAX_CLOCK_SKEW_S:
        return recv_ts
    return float(ts)


def to_point(topic: str, payload: dict, recv_ts: float) -> dict | None:
    """Map one MQTT message to an InfluxDB point dict, or None if the topic isn't stored."""
    spec = MEASUREMENTS.get(topic)
    if spec is None:
        return None
    measurement, tags, field_types = spec
    tags = dict(tags)
    fields = {}
    for name, kind in field_types.items():
        v = _cast(payload.get(name), kind)
        if v is not None:
            fields[name] = v
    if measurement == "driver":
        state = payload.get("state")
        tags["state"] = state if state in DRIVER_STATES else "unknown"
        fields["drowsy"] = 1 if state == "drowsy" else 0
    if not fields:
        return None
    return {"measurement": measurement, "tags": tags, "fields": fields, "time": _ms(point_time(payload, recv_ts))}


def alert_point(alert: Alert, ts: float, caption: str | None = None) -> dict:
    fields: dict[str, Any] = {"level_num": alert.level_num}
    if caption is not None:
        fields["caption"] = caption
    return {
        "measurement": "alert",
        "tags": {"level": alert.level, "reason": alert.reason},
        "fields": fields,
        "time": _ms(ts),
    }


def alert_payload(alert: Alert, ts: float) -> dict:
    return {"ts": round(ts, 3), "level": alert.level, "reason": alert.reason}


def _ms(ts: float) -> int:
    return int(round(ts * 1000))


# ============================================================================
# Server core (no network code here, so tests can drive it)
# ============================================================================
class Server:
    def __init__(
        self,
        publish: Callable[[str, str, int, bool], bool],
        write: Callable[[dict], None],
        captioner: Any | None = None,
        engine: RulesEngine | None = None,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ):
        """
        publish(topic, payload, qos, retain) -> True if sent.
        write(point_dict) queues one InfluxDB point.
        captioner: object with submit(path, on_done(caption, latency)), or None.
        """
        self.publish = publish
        self.write = write
        self.captioner = captioner
        self.wall = wall
        self.mono = mono
        self.engine = engine or RulesEngine(THRESHOLDS, clock=mono)
        self.lock = threading.RLock()
        self.current: Alert | None = None
        self.current_since: float = 0.0  # wall time of the last change (= alert event row time)
        self.last_publish: float | None = None  # monotonic
        self.force_publish = False
        self.stale: list[str] = []

    # --------------------------------------------------------------- inbound
    def on_message(self, topic: str, raw: bytes) -> None:
        if topic == ALERT_TOPIC or topic not in TOPIC_SOURCE:
            return  # our own alert echo, car/test, etc.
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("bad JSON on %s: %r", topic, raw[:120])
            return
        if not isinstance(payload, dict):
            log.warning("payload on %s is not an object: %r", topic, raw[:120])
            return

        recv = self.wall()
        point = to_point(topic, payload, recv)
        if point is not None:
            self.write(point)

        source = TOPIC_SOURCE[topic]
        with self.lock:
            self.engine.update(source, payload)
            if source == "driver":
                self.tick()  # fast path: a drowsy state reaches the LED without waiting for the tick
                snapshot = payload.get("snapshot")
                if isinstance(snapshot, str) and snapshot and self.captioner is not None:
                    self._request_caption(snapshot, recv)

    # -------------------------------------------------------------- rules
    def tick(self) -> Alert:
        """Evaluate the rules; publish on change or every REPUBLISH_S."""
        with self.lock:
            now = self.mono()
            alert = self.engine.evaluate(now)
            stale = self.engine.stale_sources(now)
            if stale != self.stale:
                log.info("stale sources: %s", ", ".join(stale) or "none")
                self.stale = stale

            changed = alert != self.current
            if changed:
                ts = self.wall()
                log.info(
                    "alert %s -> %s (%s)",
                    self.current.level if self.current else "-", alert.level, alert.reason,
                )
                self.current = alert
                self.current_since = ts
                self.write(alert_point(alert, ts))

            due = self.last_publish is None or now - self.last_publish >= REPUBLISH_S
            if changed or due or self.force_publish:
                msg = json.dumps(alert_payload(alert, self.wall()))
                if self.publish(ALERT_TOPIC, msg, 1, True):
                    self.last_publish = now
                    self.force_publish = False
            return alert

    def on_connected(self) -> None:
        with self.lock:
            self.force_publish = True

    # ------------------------------------------------------------- caption
    def _request_caption(self, path: str, recv: float) -> None:
        if self.current is not None and self.current.reason == "drowsy":
            event, event_ts = self.current, self.current_since
        else:  # e.g. vision says drowsy while its source was considered stale
            event, event_ts = Alert("danger", "drowsy"), recv
        log.info("captioning %s", path)

        def done(caption: str, latency: float) -> None:
            self.write(alert_point(event, event_ts, caption=caption))

        self.captioner.submit(path, done)


# ============================================================================
# Wiring: .env, MQTT, InfluxDB
# ============================================================================
def load_env(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def make_influx_writer():
    """Returns (write(point), close()) for InfluxDB, or no-ops when INFLUX_TOKEN is unset."""
    token = os.getenv("INFLUX_TOKEN", "")
    if not token:
        log.warning("INFLUX_TOKEN not set: not writing to InfluxDB")
        return (lambda point: None), (lambda: None)

    from influxdb_client import InfluxDBClient, WriteOptions, WritePrecision

    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    org = os.getenv("INFLUX_ORG", "iot")
    bucket = os.getenv("INFLUX_BUCKET", "car")
    client = InfluxDBClient(url=url, token=token, org=org)
    last_err = [0.0]

    def on_error(conf, data, exc):
        if time.monotonic() - last_err[0] > 10:  # don't flood the log while Influx is down
            last_err[0] = time.monotonic()
            log.warning("InfluxDB write failed: %s", exc)

    write_api = client.write_api(
        write_options=WriteOptions(
            batch_size=50, flush_interval=1000, max_retries=3, retry_interval=2000, max_retry_time=30000
        ),
        error_callback=on_error,
    )
    log.info("InfluxDB %s org=%s bucket=%s", url, org, bucket)

    def write(point: dict) -> None:
        write_api.write(bucket=bucket, org=org, record=point, write_precision=WritePrecision.MS)

    def close() -> None:
        write_api.close()  # flushes the batch
        client.close()

    return write, close


def make_mqtt(server_ref: list):
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="car-server")
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.will_set(ALERT_TOPIC, OFFLINE_PAYLOAD, qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("MQTT connect failed: %s", reason_code)
            return
        log.info("MQTT connected, subscribing %s", SUBSCRIBE_TOPIC)
        c.subscribe(SUBSCRIBE_TOPIC, qos=0)
        server_ref[0].on_connected()

    def on_disconnect(c, userdata, flags, reason_code, properties):
        log.warning("MQTT disconnected: %s", reason_code)

    def on_message(c, userdata, msg):
        try:
            server_ref[0].on_message(msg.topic, msg.payload)
        except Exception:  # noqa: BLE001 - one bad message must not kill the loop
            log.exception("error handling %s", msg.topic)

    def on_connect_fail(c, userdata):
        log.warning("MQTT broker unreachable, retrying")

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    def publish(topic: str, payload: str, qos: int, retain: bool) -> bool:
        if not client.is_connected():
            return False  # don't queue stale alerts; the heartbeat resends when we're back
        info = client.publish(topic, payload, qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    return client, publish


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", type=Path, default=here / ".env", help="env file (default: ./.env)")
    ap.add_argument("--no-ai", action="store_true", help="don't caption snapshots")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # While InfluxDB is down these libraries log every retry; our error callback logs a throttled summary.
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("influxdb_client").setLevel(logging.CRITICAL)
    load_env(args.env)

    write, close_influx = make_influx_writer()

    captioner = None
    if not args.no_ai:
        from ai_caption import Captioner

        captioner = Captioner()
        if not captioner.api_key:
            log.warning("AI_API_KEY not set: captions will be 'unavailable'")
        else:
            log.info("AI captions via %s (%s)", captioner.provider, captioner.model_name)

    server_ref: list = [None]
    mqtt_client, publish = make_mqtt(server_ref)
    server = Server(publish=publish, write=write, captioner=captioner)
    server_ref[0] = server

    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    log.info("MQTT broker %s:%d", host, port)
    mqtt_client.connect_async(host, port, keepalive=30)
    mqtt_client.loop_start()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    next_tick = time.monotonic()
    try:
        while not stop.is_set():
            try:
                server.tick()
            except Exception:  # noqa: BLE001
                log.exception("rules tick failed")
            next_tick += TICK_S
            delay = next_tick - time.monotonic()
            if delay < 0:  # we fell behind (e.g. laptop sleep): don't try to catch up
                next_tick = time.monotonic()
                delay = 0
            stop.wait(delay)
    finally:
        log.info("shutting down")
        if mqtt_client.is_connected():
            mqtt_client.publish(ALERT_TOPIC, OFFLINE_PAYLOAD, qos=1, retain=True).wait_for_publish(2)
        mqtt_client.disconnect()
        mqtt_client.loop_stop()
        close_influx()


if __name__ == "__main__":
    main()
