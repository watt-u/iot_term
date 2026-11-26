#!/usr/bin/env bash
# Run from iot_term/v1/. Copies the project to the Pi.
set -euo pipefail
HOST="${PI_HOST:-bum@g3pi.local}"
cd "$(dirname "$0")/.."
ssh "$HOST" 'mkdir -p ~/iot_term/v1'
rsync -az --exclude .venv --exclude alerts --exclude __pycache__ ./ "$HOST:~/iot_term/v1/"
echo "Deployed. On the Pi:"
echo "  cd ~/iot_term/v1 && uv sync && uv run python -u -m drowsiness.main --calibrate --stream-port 8000"
