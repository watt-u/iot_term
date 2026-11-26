#include "alert.h"

#include <ArduinoJson.h>

#include "config.h"

namespace {

enum class Level { Unknown, Ok, Warning, Danger, Offline };

const uint32_t PWM_FREQ_HZ = 5000;
const uint8_t PWM_BITS = 8;
// Per-channel gain to balance the KY-016 colors (green is usually brightest).
const float GAIN_R = 1.0f, GAIN_G = 0.6f, GAIN_B = 1.0f;
const uint8_t BRIGHTNESS = 255;        // external LED
const uint8_t ONBOARD_BRIGHTNESS = 30; // onboard WS2812 is very bright
const uint32_t BEEP_MS = 200;
const uint32_t BLUE_BLINK_MS = 500;
const uint32_t MQTT_DOWN_BLINK_AFTER_MS = 5000;
// server.py re-sends the alert every 2 s; no alert for this long = server gone.
const uint32_t ALERT_STALE_MS = 6000;
uint32_t lastAlertMs = 0;

Level level = Level::Unknown;
char reason[16] = "none";
uint8_t curR = 1, curG = 1, curB = 1;  // force the first write
bool buzzerOn = false;
bool blinking = false;

const char *levelName(Level l) {
  switch (l) {
    case Level::Ok: return "ok";
    case Level::Warning: return "warning";
    case Level::Danger: return "danger";
    case Level::Offline: return "offline";
    default: return "unknown";
  }
}

// r/g/b are 0/1 on-off flags; gains and brightness are applied here.
void setColor(uint8_t r, uint8_t g, uint8_t b) {
  if (r == curR && g == curG && b == curB) return;
  curR = r;
  curG = g;
  curB = b;
  ledcWrite(LED_R_PIN, r ? (uint32_t)(BRIGHTNESS * GAIN_R) : 0);
  ledcWrite(LED_G_PIN, g ? (uint32_t)(BRIGHTNESS * GAIN_G) : 0);
  ledcWrite(LED_B_PIN, b ? (uint32_t)(BRIGHTNESS * GAIN_B) : 0);
#if MIRROR_ONBOARD_RGB
  rgbLedWrite(ONBOARD_RGB_PIN, r ? ONBOARD_BRIGHTNESS : 0, g ? ONBOARD_BRIGHTNESS : 0,
              b ? ONBOARD_BRIGHTNESS : 0);
#endif
}

void setBuzzer(bool on) {
  if (on == buzzerOn) return;
  buzzerOn = on;
  digitalWrite(BUZZER_PIN, on ? HIGH : LOW);
}

}  // namespace

void alert_begin() {
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  bool ok = ledcAttach(LED_R_PIN, PWM_FREQ_HZ, PWM_BITS);
  ok &= ledcAttach(LED_G_PIN, PWM_FREQ_HZ, PWM_BITS);
  ok &= ledcAttach(LED_B_PIN, PWM_FREQ_HZ, PWM_BITS);
  if (!ok) Serial.println("[alert] LEDC attach failed");
  setColor(0, 0, 0);
  Serial.printf("[alert] LED R/G/B on GPIO %d/%d/%d, buzzer on GPIO %d\n", LED_R_PIN, LED_G_PIN,
                LED_B_PIN, BUZZER_PIN);
}

void alert_handle(const uint8_t *payload, unsigned int len) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, len);
  if (err) {
    Serial.printf("[alert] bad JSON (%s), ignored\n", err.c_str());
    return;
  }
  const char *lv = doc["level"] | "";
  Level next;
  if (!strcmp(lv, "ok")) next = Level::Ok;
  else if (!strcmp(lv, "warning")) next = Level::Warning;
  else if (!strcmp(lv, "danger")) next = Level::Danger;
  else if (!strcmp(lv, "offline")) next = Level::Offline;
  else {
    Serial.printf("[alert] unknown level \"%s\", ignored\n", lv);
    return;
  }
  const char *rs = doc["reason"] | "none";
  if (next != level || strcmp(rs, reason) != 0) {
    Serial.printf("[alert] level %s -> %s (reason %s)\n", levelName(level), levelName(next), rs);
  }
  level = next;
  strlcpy(reason, rs, sizeof(reason));
  lastAlertMs = millis();
}

void alert_update(uint32_t now, uint32_t mqttDownMs) {
  bool serverGone = level == Level::Offline ||
                    (level != Level::Unknown && now - lastAlertMs > ALERT_STALE_MS);
  if (mqttDownMs > MQTT_DOWN_BLINK_AFTER_MS || serverGone) {
    if (!blinking)
      Serial.println(serverGone ? "[alert] server offline / alerts stale: blinking blue, buzzer off"
                                : "[alert] MQTT down > 5 s: blinking blue, buzzer off");
    blinking = true;
    setBuzzer(false);
    bool on = (now / BLUE_BLINK_MS) % 2 == 0;
    setColor(0, 0, on);
    return;
  }
  blinking = false;

  switch (level) {
    case Level::Ok:
      setBuzzer(false);
      setColor(0, 1, 0);
      break;
    case Level::Warning:
      setBuzzer(false);
      setColor(1, 1, 0);
      break;
    case Level::Danger:
      setColor(1, 0, 0);
      setBuzzer((now / BEEP_MS) % 2 == 0);
      break;
    default:
      setBuzzer(false);
      setColor(0, 0, 0);
      break;
  }
}

const char *alert_level_name() { return levelName(level); }
const char *alert_reason() { return reason; }
