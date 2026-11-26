# /// script
# requires-python = ">=3.11"
# dependencies = ["influxdb-client>=1.40"]
# ///
"""fps statistics for 9.1a from InfluxDB (measurement `driver`, field `fps`).

Connection comes from env vars (or the matching flags):
    INFLUX_URL (default http://g3pi.local:8086), INFLUX_ORG, INFLUX_BUCKET (default car), INFLUX_TOKEN

Examples:
    uv run tools/eval/fps_report.py --last 5m
    uv run tools/eval/fps_report.py --start 2026-11-30T14:00 --stop 2026-11-30T14:05 \
        --setup "Vision only, no MJPEG stream"
Naive --start/--stop times are taken as local time.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from datetime import datetime, timezone


def flux_time(value: str) -> str:
    """Turn '5m', '-5m', 'now()' or an ISO time into a Flux range() argument."""
    v = value.strip()
    if v == "now()":
        return v
    if re.fullmatch(r"-?\d+(ms|s|m|h|d|w)", v):
        return v if v.startswith("-") else f"-{v}"
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"bad time {value!r}: use ISO (2026-11-30T14:00) or a duration like 5m")
    if dt.tzinfo is None:
        dt = dt.astimezone()  # assume local time
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not sorted_vals:
        return math.nan
    k = (len(sorted_vals) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mean / min / p5 fps of the vision pipeline from InfluxDB.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--last", help="relative range, e.g. 5m, 30s, 1h")
    g.add_argument("--start", help="range start (ISO time, local if no zone, or a duration like 10m)")
    p.add_argument("--stop", default="now()", help="range stop, used with --start (default now())")
    p.add_argument("--setup", help="if given, also print a markdown row for the fps table with this setup name")
    p.add_argument("--resolution", default="640×480", help="resolution column for the markdown row (default 640×480)")
    p.add_argument("--include-zero", action="store_true", help="keep fps == 0 samples (dropped by default)")
    p.add_argument("--url", default=os.environ.get("INFLUX_URL", "http://g3pi.local:8086"))
    p.add_argument("--org", default=os.environ.get("INFLUX_ORG"))
    p.add_argument("--bucket", default=os.environ.get("INFLUX_BUCKET", "car"))
    p.add_argument("--token", default=os.environ.get("INFLUX_TOKEN"), help="default $INFLUX_TOKEN")
    args = p.parse_args(argv)

    if not args.org or not args.token:
        print("error: set INFLUX_ORG and INFLUX_TOKEN (or pass --org / --token)", file=sys.stderr)
        return 1

    start = flux_time(args.last if args.last else args.start)
    stop = "now()" if args.last else flux_time(args.stop)
    query = f'''
from(bucket: "{args.bucket}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "driver" and r._field == "fps")
  |> keep(columns: ["_time", "_value"])
'''

    from influxdb_client import InfluxDBClient  # imported here so --help works fast

    with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=20_000) as client:
        tables = client.query_api().query(query)
    vals = [float(rec.get_value()) for t in tables for rec in t.records if rec.get_value() is not None]
    dropped = 0
    if not args.include_zero:
        dropped = sum(1 for v in vals if v <= 0)
        vals = [v for v in vals if v > 0]

    print(f"range: {start} -> {stop}   bucket: {args.bucket}")
    if not vals:
        print("no fps samples in that range (is vision publishing and server.py writing to InfluxDB?)")
        return 1
    vals.sort()
    mean = sum(vals) / len(vals)
    print(f"samples: {len(vals)}" + (f"  (dropped {dropped} zero samples)" if dropped else ""))
    print(f"mean fps: {mean:.2f}")
    print(f"min fps:  {vals[0]:.2f}")
    print(f"p5 fps:   {percentile(vals, 5):.2f}")
    print(f"max fps:  {vals[-1]:.2f}")
    if args.setup:
        print()
        print(f"| {args.setup} | {args.resolution} | {mean:.1f} | {vals[0]:.1f} | |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
