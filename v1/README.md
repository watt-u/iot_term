# Pi 5 drowsiness detector (v1)

Live video: `rpicam-vid` MJPEG pipe -> OpenCV -> MediaPipe Face Mesh -> eye aspect ratio (EAR).
Alerts when EAR stays below a threshold for N consecutive frames.

## Setup
From this folder on the Mac:

    ./scripts/deploy.sh

On the Pi (needs `uv`; it fetches Python 3.11 itself):

    cd ~/iot_term/v1
    uv sync
    uv run python -u -m drowsiness.main --calibrate --stream-port 8000

Watch the annotated stream at http://g3pi.local:8000

## Options
- `--calibrate` set the threshold from 3 s of open eyes
- `--ear-thresh 0.21` fixed threshold
- `--frames 15` consecutive closed frames before an alert
- `--stream-port 8000` enable the web view
- Alert frames are saved to `alerts/`
