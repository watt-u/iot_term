#include "net.h"

#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "src/secrets.h not found: using placeholder values from secrets.example.h. Copy it to secrets.h and fill it in."
#include "secrets.example.h"
#endif

namespace {

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
MessageHandler handler = nullptr;

char clientId[24];
IPAddress brokerIp;
bool brokerKnown = false;
bool mdnsStarted = false;

bool wifiWasUp = false;
bool mqttWasUp = false;
uint32_t lastWifiAttempt = 0;
uint32_t lastMqttAttempt = 0;
uint32_t mqttDownSince = 0;  // millis() when MQTT went down (0 = boot)
uint8_t mqttFails = 0;

uint32_t pubOk = 0, pubFail = 0, reconnects = 0;

const char *mqttStateName(int s) {
  switch (s) {
    case MQTT_CONNECTION_TIMEOUT: return "timeout";
    case MQTT_CONNECTION_LOST: return "connection lost";
    case MQTT_CONNECT_FAILED: return "connect failed (no broker?)";
    case MQTT_DISCONNECTED: return "disconnected";
    case MQTT_CONNECTED: return "connected";
    case MQTT_CONNECT_BAD_PROTOCOL: return "bad protocol";
    case MQTT_CONNECT_BAD_CLIENT_ID: return "bad client id";
    case MQTT_CONNECT_UNAVAILABLE: return "unavailable";
    case MQTT_CONNECT_BAD_CREDENTIALS: return "bad credentials";
    case MQTT_CONNECT_UNAUTHORIZED: return "unauthorized";
    default: return "?";
  }
}

void onMqttMessage(char *topic, uint8_t *payload, unsigned int len) {
  if (handler) handler(topic, payload, len);
}

// mDNS lookup of MQTT_HOST_NAME, else the fixed fallback IP. Blocks up to MDNS_TIMEOUT_MS.
void resolveBroker() {
  IPAddress ip;
  if (mdnsStarted) ip = MDNS.queryHost(MQTT_HOST_NAME, MDNS_TIMEOUT_MS);
  if (ip != IPAddress((uint32_t)0)) {
    Serial.printf("[net] mDNS: %s.local -> %s\n", MQTT_HOST_NAME, ip.toString().c_str());
  } else {
    ip.fromString(MQTT_FALLBACK_IP);
    Serial.printf("[net] mDNS lookup of %s.local failed, using fallback %s\n", MQTT_HOST_NAME,
                  ip.toString().c_str());
  }
  brokerIp = ip;
  brokerKnown = true;
  mqttFails = 0;
  mqtt.setServer(brokerIp, MQTT_PORT);
}

void wifiStart(uint32_t now) {
  lastWifiAttempt = now;
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void handleWifi(uint32_t now) {
  bool up = WiFi.status() == WL_CONNECTED;
  if (up && !wifiWasUp) {
    Serial.printf("[net] Wi-Fi up: SSID \"%s\", IP %s, RSSI %d dBm\n", WIFI_SSID,
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    if (!mdnsStarted) {
      mdnsStarted = MDNS.begin(clientId);
      if (!mdnsStarted) Serial.println("[net] MDNS.begin failed, will use the fallback IP");
    }
  } else if (!up && wifiWasUp) {
    Serial.println("[net] Wi-Fi lost, reconnecting...");
    lastWifiAttempt = now;  // let auto-reconnect try first
  }
  wifiWasUp = up;

  if (!up && now - lastWifiAttempt >= WIFI_RETRY_MS) {
    Serial.printf("[net] Wi-Fi still down (status %d), restarting connect to \"%s\"\n",
                  (int)WiFi.status(), WIFI_SSID);
    WiFi.disconnect();
    wifiStart(now);
  }
}

void handleMqtt(uint32_t now) {
  bool up = mqtt.connected();
  if (!up && mqttWasUp) {
    Serial.printf("[net] MQTT lost (%s)\n", mqttStateName(mqtt.state()));
    mqttDownSince = now;
  }
  mqttWasUp = up;
  if (up || !wifiWasUp) return;
  if (now - lastMqttAttempt < MQTT_RETRY_MS) return;
  lastMqttAttempt = now;

  if (!brokerKnown || mqttFails >= MQTT_FAILS_BEFORE_RESOLVE) resolveBroker();

  Serial.printf("[net] MQTT connecting to %s:%d as %s...\n", brokerIp.toString().c_str(),
                MQTT_PORT, clientId);
  if (mqtt.connect(clientId)) {
    mqttFails = 0;
    reconnects++;
    mqttWasUp = true;
    bool sub = mqtt.subscribe(TOPIC_ALERT, 1);
    Serial.printf("[net] MQTT connected (#%lu), subscribe %s: %s\n", (unsigned long)reconnects,
                  TOPIC_ALERT, sub ? "ok" : "FAILED");
  } else {
    mqttFails++;
    Serial.printf("[net] MQTT connect failed: %s (fail %u)\n", mqttStateName(mqtt.state()),
                  mqttFails);
  }
}

}  // namespace

void net_begin(MessageHandler onMessage) {
  handler = onMessage;
  uint64_t mac = ESP.getEfuseMac();
  // Unique per board: last 3 bytes of the MAC (efuse MAC is little-endian).
  snprintf(clientId, sizeof(clientId), "esp32-node-%02x%02x%02x", (uint8_t)(mac >> 24),
           (uint8_t)(mac >> 32), (uint8_t)(mac >> 40));

  mqtt.setBufferSize(MQTT_BUFFER_SIZE);
  mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  mqtt.setSocketTimeout(MQTT_SOCKET_TIMEOUT_S);
  mqtt.setCallback(onMqttMessage);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(clientId);
  WiFi.setAutoReconnect(true);
  Serial.printf("[net] client id %s, Wi-Fi \"%s\", broker %s.local (fallback %s):%d\n", clientId,
                WIFI_SSID, MQTT_HOST_NAME, MQTT_FALLBACK_IP, MQTT_PORT);
  wifiStart(millis());
  mqttDownSince = millis();
}

void net_loop(uint32_t now) {
  handleWifi(now);
  handleMqtt(now);
  if (mqtt.connected()) mqtt.loop();
}

bool net_wifi_up() { return WiFi.status() == WL_CONNECTED; }
bool net_mqtt_up() { return mqtt.connected(); }

uint32_t net_mqtt_down_ms(uint32_t now) { return mqtt.connected() ? 0 : now - mqttDownSince; }

bool net_publish(const char *topic, const char *payload, bool retain) {
  if (!mqtt.connected()) return false;
  bool ok = mqtt.publish(topic, payload, retain);
  if (ok) pubOk++;
  else pubFail++;
  return ok;
}

const char *net_client_id() { return clientId; }
String net_broker_ip() { return brokerKnown ? brokerIp.toString() : String("-"); }
uint32_t net_publish_count() { return pubOk; }
uint32_t net_publish_fail_count() { return pubFail; }
uint32_t net_reconnect_count() { return reconnects; }
