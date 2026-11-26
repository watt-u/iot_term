#!/usr/bin/env bash
# Copies pi_gateway/ and server/ to the Pi at ~/iot_term/. Run from anywhere.
set -euo pipefail
HOST="${PI_HOST:-bum@g3pi.local}"
cd "$(dirname "$0")/.."
ssh "$HOST" 'mkdir -p ~/iot_term'
rsync -az --relative \
  --exclude .venv --exclude alerts --exclude __pycache__ --exclude .env --exclude data \
  ./pi_gateway ./server "$HOST:~/iot_term/"
echo "Deployed to $HOST:~/iot_term/. On the Pi:"
echo "  cd ~/iot_term/pi_gateway && uv sync    # then: sudo systemctl restart vision"
echo "  cd ~/iot_term/server && uv sync && docker compose up -d    # then: sudo systemctl restart car-server"
