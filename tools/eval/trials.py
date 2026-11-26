# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2"]
# ///
"""Interactive accuracy-trial runner for 9.1b in docs/evaluation.md.

For each trial it shows what the subject must do, counts down, then listens to
car/vision/driver for a 10 s window. The trial "fires" if any message in the
window has state == "drowsy". If no message arrives at all (broker down or
vision not running), the trial is marked invalid (valid=0) and report.py skips it.

Rows are appended to docs/eval_data/trials.csv:
    timestamp, subject, condition, label, fired, min_ear, frames_seen, valid
(frames_seen = number of car/vision/driver messages received in the window.)

Examples:
    uv run tools/eval/trials.py                              # asks for everything, 10 pos + 10 neg, shuffled
    uv run tools/eval/trials.py --subject alice --condition dim -n 5
    uv run tools/eval/trials.py --order PNNPPN --broker 192.168.1.20
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO / "docs" / "eval_data" / "trials.csv"
TOPIC = "car/vision/driver"
FIELDS = ["timestamp", "subject", "condition", "label", "fired", "min_ear", "frames_seen", "valid"]

# Keep in sync with tools/eval/report.py.
CONDITIONS: dict[str, str] = {
    "good": "Good light, no glasses",
    "dim": "Dim light (cabin at dusk)",
    "glasses": "Clear glasses",
    "sunglasses": "Sunglasses",
    "head30": "Head turned about 30°",
}

INSTRUCTIONS = {
    "pos": "POSITIVE: at GO, close your eyes for 3 s (still, or let the head drop slowly), then open.",
    "neg": "NEGATIVE: at GO, drive normally: blink, glance at the side mirror ~2 s, talk, a quick nod.",
}


class Listener:
    """Collects car/vision/driver payloads while `recording` is set."""

    def __init__(self, host: str, port: int):
        self.lock = threading.Lock()
        self.msgs: list[dict] = []
        self.recording = False
        self.connected = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"eval-trials-{random.randint(0, 99999)}")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(TOPIC, qos=0)
            self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(data, dict):
            return
        with self.lock:
            if self.recording:
                self.msgs.append(data)

    def start(self):
        with self.lock:
            self.msgs = []
            self.recording = True

    def stop(self) -> list[dict]:
        with self.lock:
            self.recording = False
            return list(self.msgs)

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def ask(prompt: str, default: str | None = None, choices: list[str] | None = None) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        ans = input(f"{prompt}{suffix}: ").strip() or (default or "")
        if ans and (choices is None or ans in choices):
            return ans
        if choices:
            print(f"  choose one of: {', '.join(choices)}")


def make_order(n: int, order: str | None, seed: int | None) -> list[str]:
    if order:
        out = []
        for ch in order.upper():
            if ch == "P":
                out.append("pos")
            elif ch == "N":
                out.append("neg")
            elif ch not in " ,":
                raise SystemExit(f"--order: unexpected character {ch!r} (use P and N)")
        return out
    labels = ["pos"] * n + ["neg"] * n
    random.Random(seed).shuffle(labels)
    return labels


def countdown(seconds: int):
    for i in range(seconds, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(1)
    print("  GO!", flush=True)


def run_window(listener: Listener, window: float) -> list[dict]:
    listener.start()
    end = time.monotonic() + window
    while (left := end - time.monotonic()) > 0:
        print(f"\r  recording... {left:4.1f} s left ", end="", flush=True)
        time.sleep(min(0.1, left))
    print("\r  recording... done          ")
    return listener.stop()


def summarize(msgs: list[dict]) -> tuple[bool, float | None, int]:
    fired = any(m.get("state") == "drowsy" for m in msgs)
    ears = [m["ear"] for m in msgs if isinstance(m.get("ear"), (int, float))]
    return fired, (min(ears) if ears else None), len(msgs)


def append_row(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run drowsiness accuracy trials and append results to trials.csv.",
        epilog="Conditions: " + ", ".join(f"{k} = {v}" for k, v in CONDITIONS.items()),
    )
    p.add_argument("--subject", help="subject name or ID (asked if missing)")
    p.add_argument("--condition", choices=list(CONDITIONS), help="test condition (asked if missing)")
    p.add_argument("-n", type=int, default=10, help="number of positive AND of negative trials (default 10)")
    p.add_argument("--order", help="scripted order instead of shuffling, e.g. PNPNNP (P=positive, N=negative)")
    p.add_argument("--seed", type=int, help="random seed for the shuffled order")
    p.add_argument("--window", type=float, default=10.0, help="listening window in seconds (default 10)")
    p.add_argument("--countdown", type=int, default=3, help="countdown seconds before each window (default 3)")
    p.add_argument("--broker", default="g3pi.local", help="MQTT broker host (default g3pi.local)")
    p.add_argument("--port", type=int, default=1883, help="MQTT broker port (default 1883)")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV, help=f"output CSV (default {DEFAULT_CSV.relative_to(REPO)})")
    args = p.parse_args(argv)

    subject = args.subject or ask("Subject")
    if args.condition:
        condition = args.condition
    else:
        for k, v in CONDITIONS.items():
            print(f"  {k:<11} {v}")
        condition = ask("Condition", choices=list(CONDITIONS))
    labels = make_order(args.n, args.order, args.seed)
    if not labels:
        print("no trials to run", file=sys.stderr)
        return 1

    listener = Listener(args.broker, args.port)
    print(f"Connecting to {args.broker}:{args.port} ...")
    if not listener.connected.wait(5):
        print("WARNING: not connected to the broker yet. Trials without messages will be marked invalid.")

    print(f"\n{len(labels)} trials for {subject} / {CONDITIONS[condition]}. Writing to {args.csv}")
    print("At each prompt: Enter = start, s = skip, q = quit.\n")
    done = invalid = 0
    i = 0
    try:
        while i < len(labels):
            label = labels[i]
            print(f"--- Trial {i + 1}/{len(labels)}: {INSTRUCTIONS[label]}")
            cmd = input("  ready? ").strip().lower()
            if cmd == "q":
                break
            if cmd == "s":
                i += 1
                continue
            countdown(args.countdown)
            msgs = run_window(listener, args.window)
            fired, min_ear, n = summarize(msgs)
            valid = n > 0
            if not valid:
                invalid += 1
                state = "connected" if listener.connected.is_set() else "NOT connected"
                print(f"  WARNING: no {TOPIC} messages in the window (broker {state}; is vision running?). Marked invalid.")
            else:
                ok = fired == (label == "pos")
                print(f"  fired={fired}  min_ear={min_ear}  messages={n}  -> {'correct' if ok else 'WRONG'}")
            append_row(args.csv, {
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "subject": subject,
                "condition": condition,
                "label": label,
                "fired": int(fired),
                "min_ear": "" if min_ear is None else f"{min_ear:.4f}",
                "frames_seen": n,
                "valid": int(valid),
            })
            done += 1
            i += 1
            print()
    except (KeyboardInterrupt, EOFError):
        print("\nstopped.")
    finally:
        listener.close()

    print(f"Saved {done} trials ({invalid} invalid) to {args.csv}. Run tools/eval/report.py for the table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
