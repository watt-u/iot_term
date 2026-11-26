"""Frame source: rpicam-vid MJPEG piped over stdout, decoded with OpenCV.

picamera2 is not used because the system bindings target Python 3.13 while
MediaPipe needs the uv-managed Python 3.11 venv.
"""
import subprocess

import cv2
import numpy as np

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


def frames(width=640, height=480, fps=15, extra_args=None):
    cmd = [
        "rpicam-vid", "-t", "0", "--nopreview",
        "--codec", "mjpeg",
        "--width", str(width), "--height", str(height),
        "--framerate", str(fps),
        "--autofocus-mode", "continuous",
        "-o", "-",
    ] + (extra_args or [])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                raise RuntimeError("rpicam-vid stopped producing data")
            buf += chunk
            while True:
                start = buf.find(SOI)
                if start < 0:
                    buf = b""
                    break
                end = buf.find(EOI, start + 2)
                if end < 0:
                    buf = buf[start:]
                    break
                jpg, buf = buf[start:end + 2], buf[end + 2:]
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    yield img
    finally:
        proc.terminate()
        proc.wait()
