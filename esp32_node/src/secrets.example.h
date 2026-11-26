#pragma once
// Copy this file to src/secrets.h and fill in your values.
// src/secrets.h is gitignored (see the repo's root .gitignore).

#define WIFI_SSID "your-hotspot-ssid"
#define WIFI_PASS "your-hotspot-password"

// The broker (Mosquitto on the Pi). The node looks up MQTT_HOST_NAME over mDNS
// ("g3pi" -> g3pi.local) and falls back to MQTT_FALLBACK_IP if that fails.
#define MQTT_HOST_NAME "g3pi"
#define MQTT_FALLBACK_IP "192.168.1.100"
#define MQTT_PORT 1883
