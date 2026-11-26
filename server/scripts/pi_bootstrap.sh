#!/usr/bin/env bash
# One-time root setup on the Pi. Run: sudo bash ~/iot_term/server/scripts/pi_bootstrap.sh
# Installs Docker, starts Mosquitto/InfluxDB/Grafana, and installs + starts
# the car-server and vision systemd services. Safe to run again.
set -euo pipefail
USER_NAME="${SUDO_USER:-bum}"
HOME_DIR="/home/$USER_NAME/iot_term"

if ! command -v docker >/dev/null; then
  echo "== Installing Docker (get.docker.com)"
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$USER_NAME"

echo "== Starting Mosquitto, InfluxDB, Grafana"
cd "$HOME_DIR/server"
docker compose up -d

echo "== Installing systemd services"
cp "$HOME_DIR/server/systemd/server.service" /etc/systemd/system/car-server.service
cp "$HOME_DIR/pi_gateway/systemd/vision.service" /etc/systemd/system/vision.service
systemctl daemon-reload
systemctl enable --now car-server vision

docker compose ps
systemctl --no-pager --lines=0 status car-server vision || true
echo "== Done. Grafana: http://$(hostname).local:3000"
