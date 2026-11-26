import argparse
import statistics
import time
from pathlib import Path

import cv2

from . import camera, stream
from .detector import Detector


def main():
    ap = argparse.ArgumentParser(description="Live drowsiness detector")
    ap.add_argument("--ear-thresh", type=float, default=0.21)
    ap.add_argument("--frames", type=int, default=15, help="consecutive closed-eye frames before alert")
    ap.add_argument("--stream-port", type=int, default=0, help="serve MJPEG on this port (0 = off)")
    ap.add_argument("--calibrate", action="store_true", help="set threshold from 3 s of open eyes")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--alerts-dir", default="alerts")
    args = ap.parse_args()

    det = Detector()
    if args.stream_port:
        stream.start(args.stream_port)
        print(f"stream: http://0.0.0.0:{args.stream_port}")
    Path(args.alerts_dir).mkdir(exist_ok=True)

    thresh = args.ear_thresh
    calib = [] if args.calibrate else None
    calib_end = time.time() + 3
    if calib is not None:
        print("calibrating: look at the camera with eyes open for 3 s")

    closed = 0
    last_print = 0.0
    last_alert = 0.0
    n = 0
    t0 = time.time()

    for frame in camera.frames(fps=args.fps):
        n += 1
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

        if value is None:
            closed = 0
            status = "no face"
        elif value < thresh:
            closed += 1
            status = "closed"
        else:
            closed = 0
            status = "open"

        drowsy = closed >= args.frames
        for p in pts:
            cv2.circle(frame, p, 2, (0, 255, 0), -1)
        label = f"EAR {value:.2f}" if value is not None else "EAR --"
        color = (0, 0, 255) if drowsy else (0, 255, 0)
        cv2.putText(frame, f"{label} {status}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if drowsy:
            cv2.putText(frame, "DROWSY!", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            if time.time() - last_alert > 3:
                last_alert = time.time()
                path = Path(args.alerts_dir) / f"drowsy_{int(last_alert)}.jpg"
                cv2.imwrite(str(path), frame)
                print(f"ALERT: drowsy, saved {path}")

        if args.stream_port:
            stream.publish(frame)

        now = time.time()
        if now - last_print >= 1:
            last_print = now
            fps = n / (now - t0)
            print(f"{label} {status} thresh={thresh} fps={fps:.1f}")


if __name__ == "__main__":
    main()
