#!/usr/bin/env python3
"""Pi cabin sensors -> car/gateway/cabin at 1 Hz.

- DS18B20 (KY-001) on GPIO 4 through the kernel 1-Wire driver
  (dtoverlay=w1-gpio), read from /sys/bus/w1/devices/28-*/w1_slave.
- HC-SR04 ultrasonic: TRIG GPIO 23, ECHO GPIO 24 (through a 1k/2k divider).

Run with the SYSTEM python3 on the Pi (not the uv venv):
    sudo apt install python3-gpiozero python3-lgpio python3-paho-mqtt
    /usr/bin/python3 sensors.py

A failed read is sent as null; the program never crashes on a sensor or
broker error. gpiozero and paho are imported lazily, so the file also runs on
a Mac for tests: python3 sensors.py --w1-dir /tmp/fake_w1 --no-mqtt --once
"""
import argparse
import glob
import json
import os
import re
import signal
import sys
import time

TOPIC = "car/gateway/cabin"
W1_DIR = "/sys/bus/w1/devices"
# 85.000 C is the DS18B20 power-on reset value; it shows up after a brown-out
# or a bad conversion, so treat it as a failed read.
POWER_ON_RESET_MILLI_C = 85000

_T_RE = re.compile(r"t=(-?\d+)")


def parse_w1_slave(text):
    """Parses w1_slave contents. Returns degrees C, or None on a CRC/format error.

    Example:
        72 01 4b 46 7f ff 0e 10 57 : crc=57 YES
        72 01 4b 46 7f ff 0e 10 57 t=23125
    """
    lines = text.strip().splitlines()
    if len(lines) < 2 or not lines[0].strip().endswith("YES"):
        return None
    m = _T_RE.search(lines[1])
    if not m:
        return None
    milli = int(m.group(1))
    if milli == POWER_ON_RESET_MILLI_C:
        return None
    return round(milli / 1000.0, 2)


def find_w1_slave(w1_dir=W1_DIR):
    """Path of the first DS18B20 (family 28) w1_slave file, or None."""
    paths = sorted(glob.glob(os.path.join(w1_dir, "28-*", "w1_slave")))
    return paths[0] if paths else None


def read_temp(w1_dir=W1_DIR, retries=1):
    """Reads the DS18B20 in degrees C, retrying `retries` times. None if it fails."""
    path = find_w1_slave(w1_dir)
    if path is None:
        return None
    for _ in range(1 + retries):
        try:
            with open(path) as f:
                value = parse_w1_slave(f.read())
        except OSError:
            value = None
        if value is not None:
            return value
    return None


def make_distance_sensor(echo=24, trigger=23, max_distance=2.0):
    """Returns a gpiozero DistanceSensor, or None if gpiozero or the GPIO is unavailable."""
    try:
        from gpiozero import DistanceSensor
    except ImportError:
        print("sensors: gpiozero not installed, distance will be null", flush=True)
        return None
    try:
        # gpiozero samples in a background thread (every ~60 ms) and reports
        # the median of the last queue_len readings: median of 5.
        return DistanceSensor(echo=echo, trigger=trigger, max_distance=max_distance, queue_len=5)
    except Exception as e:
        print(f"sensors: HC-SR04 unavailable ({e}), distance will be null", flush=True)
        return None


def read_distance(sensor):
    """Distance in cm (median of the last 5 samples), or None."""
    if sensor is None:
        return None
    try:
        meters = sensor.distance
    except Exception:
        return None
    if meters is None:
        return None
    return round(meters * 100.0, 1)


def build_payload(ts, temp, distance):
    return {"ts": float(ts), "temp": temp, "distance": distance}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Pi cabin sensors -> " + TOPIC)
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--no-mqtt", action="store_true", help="print payloads only")
    ap.add_argument("--w1-dir", default=W1_DIR, help="1-Wire devices folder (for tests)")
    ap.add_argument("--no-distance", action="store_true", help="skip the HC-SR04")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between publishes")
    ap.add_argument("--once", action="store_true", help="read and print once, then exit")
    ap.add_argument("--quiet", action="store_true", help="don't print every payload")
    return ap.parse_args(argv)


def make_publisher(host, port):
    try:
        # pi_gateway/drowsiness/mqtt.py has no heavy imports, so the system
        # python3 can reuse it (sys.path[0] is this folder).
        from drowsiness.mqtt import Publisher
        return Publisher(host, port, client_id="sensors", name="mqtt")
    except Exception as e:
        print(f"sensors: MQTT unavailable ({e}), printing only", flush=True)
        return None


def main(argv=None):
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if find_w1_slave(args.w1_dir) is None:
        print(f"sensors: no DS18B20 under {args.w1_dir} (check dtoverlay=w1-gpio), temp will be null",
              flush=True)
    sensor = None if args.no_distance else make_distance_sensor()
    pub = None if (args.no_mqtt or args.once) else make_publisher(args.mqtt_host, args.mqtt_port)

    next_t = time.monotonic()
    try:
        while True:
            try:
                payload = build_payload(time.time(), read_temp(args.w1_dir), read_distance(sensor))
            except Exception as e:  # belt and braces: never die on a read
                print(f"sensors: read error {e}", flush=True)
                payload = build_payload(time.time(), None, None)
            if pub is not None:
                pub.publish(TOPIC, payload)
            if args.once or not args.quiet:
                print(json.dumps(payload), flush=True)
            if args.once:
                return 0
            next_t += args.interval
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:  # fell behind (slow read); don't try to catch up
                next_t = time.monotonic()
    except KeyboardInterrupt:
        return 0
    finally:
        if pub is not None:
            pub.close()
        if sensor is not None:
            try:
                sensor.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
