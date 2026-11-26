# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2"]
# ///
"""Measure drowsy -> danger alert latency over MQTT (vision -> server.py hop).

Subscribes to car/vision/driver and car/cmd/alert. Each time vision's state
changes to "drowsy", it waits for the next car/cmd/alert with level "danger" and
prints two latencies:
  - ts:    alert.ts - vision.ts   (both stamped on the Pi clock by the publishers)
  - local: receive time of the alert - receive time of the vision message (this Mac)
Press Ctrl-C to stop and print mean ± SD.

This covers the software path only (drowsy published -> alert published). The full
eyes-closed -> buzzer latency still needs the 60 fps phone video in docs/evaluation.md.

Examples:
    uv run tools/eval/latency.py
    uv run tools/eval/latency.py --broker g3pi.local --timeout 5 --csv docs/eval_data/latency.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

VISION = "car/vision/driver"
ALERT = "car/cmd/alert"


class Tracker:
    def __init__(self, timeout: float, csv_path: Path | None):
        self.lock = threading.Lock()
        self.timeout = timeout
        self.csv_path = csv_path
        self.prev_state: str | None = None
        self.pending: dict | None = None  # {"ts": vision ts, "recv": local time}
        self.ts_lat: list[float] = []
        self.local_lat: list[float] = []
        self.missed = 0

    def on_vision(self, data: dict, recv: float):
        state = data.get("state")
        with self.lock:
            if state == "drowsy" and self.prev_state != "drowsy":
                if self.pending:
                    self._miss("a new drowsy event started first")
                self.pending = {"ts": data.get("ts"), "recv": recv}
                print(f"[{_clock()}] drowsy (vision ts={data.get('ts')}) ... waiting for danger alert", flush=True)
            self.prev_state = state

    def on_alert(self, data: dict, recv: float, retained: bool):
        if retained or data.get("level") != "danger":
            return
        with self.lock:
            if not self.pending:
                return
            local = recv - self.pending["recv"]
            v_ts, a_ts = self.pending["ts"], data.get("ts")
            ts_lat = None
            if isinstance(v_ts, (int, float)) and isinstance(a_ts, (int, float)) and v_ts > 0 and a_ts > 0:
                ts_lat = a_ts - v_ts
                self.ts_lat.append(ts_lat)
            self.local_lat.append(local)
            n = len(self.local_lat)
            ts_txt = "n/a" if ts_lat is None else f"{ts_lat * 1000:7.1f} ms"
            print(f"[{_clock()}] event {n}: ts latency {ts_txt}   local latency {local * 1000:7.1f} ms   "
                  f"(reason={data.get('reason')})", flush=True)
            self._write(n, ts_lat, local, data.get("reason"))
            self.pending = None

    def check_timeout(self):
        with self.lock:
            if self.pending and time.time() - self.pending["recv"] > self.timeout:
                self._miss(f"no danger alert within {self.timeout:g} s")

    def _miss(self, why: str):
        self.missed += 1
        print(f"[{_clock()}] MISSED: {why}", flush=True)
        self._write(None, None, None, "missed")
        self.pending = None

    def _write(self, n, ts_lat, local, reason):
        if not self.csv_path:
            return
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "event", "ts_latency_s", "local_latency_s", "reason"])
            w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), n or "",
                        "" if ts_lat is None else f"{ts_lat:.4f}", "" if local is None else f"{local:.4f}", reason])

    def summary(self) -> str:
        lines = [f"events: {len(self.local_lat)}   missed: {self.missed}"]
        for name, vals in (("ts", self.ts_lat), ("local", self.local_lat)):
            lines.append(f"{name:>5} latency: {mean_sd(vals)}")
        return "\n".join(lines)


def mean_sd(vals: list[float]) -> str:
    if not vals:
        return "n/a"
    m = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return f"{m:.3f} ± {sd:.3f} s (n={len(vals)}, min {min(vals):.3f}, max {max(vals):.3f})"


def _clock() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure drowsy -> danger alert latency over MQTT. Ctrl-C to finish.")
    p.add_argument("--broker", default="g3pi.local", help="MQTT broker host (default g3pi.local)")
    p.add_argument("--port", type=int, default=1883, help="MQTT broker port (default 1883)")
    p.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for the alert before counting a miss (default 5)")
    p.add_argument("--csv", type=Path, help="also append each event to this CSV")
    args = p.parse_args(argv)

    tracker = Tracker(args.timeout, args.csv)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe([(VISION, 0), (ALERT, 1)])
            print(f"connected to {args.broker}:{args.port}; listening on {VISION} and {ALERT}. Ctrl-C to stop.")
        else:
            print(f"connect failed: {reason_code}", file=sys.stderr)

    def on_message(client, userdata, msg):
        recv = time.time()
        try:
            data = json.loads(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(data, dict):
            return
        if msg.topic == VISION:
            tracker.on_vision(data, recv)
        elif msg.topic == ALERT:
            tracker.on_alert(data, recv, bool(msg.retain))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"eval-latency-{random.randint(0, 99999)}")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(args.broker, args.port, keepalive=30)
    client.loop_start()
    try:
        while True:
            time.sleep(0.2)
            tracker.check_timeout()
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    print("\n" + tracker.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
