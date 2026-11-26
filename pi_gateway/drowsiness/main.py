import argparse
import signal
import statistics
import sys
import time
from pathlib import Path

import cv2

from . import camera, stream
from .detector import Detector
from .logic import DROWSY, TOPIC, DriverState, RollingFps, Throttle, build_payload


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Live drowsiness detector")
    ap.add_argument("--ear-thresh", type=float, default=0.21)
    ap.add_argument("--frames", type=int, default=15, help="consecutive closed-eye frames before alert")
    ap.add_argument("--stream-port", type=int, default=0, help="serve MJPEG on this port (0 or omitted = off)")
    ap.add_argument("--no-stream", action="store_true", help="turn the MJPEG stream off even if --stream-port is set")
    ap.add_argument("--calibrate", action="store_true", help="set threshold from 3 s of open eyes")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--alerts-dir", default="alerts")
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--no-mqtt", action="store_true", help="don't publish car/vision/driver")
    ap.add_argument("--publish-period", type=float, default=0.5, help="seconds between periodic publishes (2 Hz)")
    args = ap.parse_args(argv)
    if args.no_stream:
        args.stream_port = 0
    return args


def main(argv=None):
    args = parse_args(argv)
    # systemd stops us with SIGTERM; turn it into SystemExit so cleanup runs.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    det = Detector()
    if args.stream_port:
        stream.start(args.stream_port)
        print(f"stream: http://0.0.0.0:{args.stream_port}")
    alerts_dir = Path(args.alerts_dir).resolve()
    alerts_dir.mkdir(parents=True, exist_ok=True)

    pub = None
    if not args.no_mqtt:
        from .mqtt import Publisher
        pub = Publisher(args.mqtt_host, args.mqtt_port, client_id="vision", name="mqtt")
        print(f"mqtt: publishing {TOPIC} to {args.mqtt_host}:{args.mqtt_port}")

    thresh = args.ear_thresh
    calib = [] if args.calibrate else None
    calib_end = time.time() + 3
    if calib is not None:
        print("calibrating: look at the camera with eyes open for 3 s")

    driver = DriverState(args.frames)
    rolling = RollingFps(30)
    throttle = Throttle(args.publish_period)
    last_print = 0.0
    last_alert = 0.0
    n = 0
    t0 = time.time()

    try:
        for frame in camera.frames(fps=args.fps):
            n += 1
            fps = rolling.tick(time.time())
            value, pts = det.process(frame)

            if calib is not None:
                if value is not None:
                    calib.append(value)
                if time.time() >= calib_end:
                    if calib:
                        thresh = round(statistics.median(calib) * 0.75, 3)
                        print(f"calibrated threshold: {thresh}")
                    else:
                        print(f"no face seen, keeping threshold {thresh}")
                    calib = None
                continue

            state, changed, became_drowsy = driver.update(value, thresh)
            drowsy = state == DROWSY
            # Clean copy for the AI caption (the overlay would bias it).
            raw = frame.copy() if drowsy else None

            for p in pts:
                cv2.circle(frame, p, 2, (0, 255, 0), -1)
            label = f"EAR {value:.2f}" if value is not None else "EAR --"
            color = (0, 0, 255) if drowsy else (0, 255, 0)
            cv2.putText(frame, f"{label} {state}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            snapshot = None
            if drowsy:
                cv2.putText(frame, "DROWSY!", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
                # Always save on the transition (its path goes in the payload),
                # then every 3 s while the driver stays drowsy.
                if became_drowsy or time.time() - last_alert > 3:
                    last_alert = time.time()
                    path = alerts_dir / f"drowsy_{int(last_alert * 1000)}.jpg"
                    raw_path = path.with_name(path.stem + "_raw.jpg")
                    if cv2.imwrite(str(path), frame) and cv2.imwrite(str(raw_path), raw):
                        print(f"ALERT: drowsy, saved {path}")
                        if became_drowsy:
                            snapshot = str(raw_path.resolve())
                    else:
                        print(f"ALERT: drowsy, could not save {path}")

            now = time.time()
            if pub is not None and throttle.due(now, changed):
                payload = build_payload(now, value, thresh, state, driver.closed_frames, fps, snapshot)
                pub.publish(TOPIC, payload)

            if args.stream_port:
                stream.publish(frame)

            if now - last_print >= 1:
                last_print = now
                avg = n / (now - t0)
                print(f"{label} {state} thresh={thresh} fps={fps:.1f} avg_fps={avg:.1f}")
    except KeyboardInterrupt:
        pass
    finally:
        if pub is not None:
            pub.close()


if __name__ == "__main__":
    main()
