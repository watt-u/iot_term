// ESP32-S3 sensor node (car drowsiness detector, milestone M2).
//
// Publishes car/node/motion (5 Hz + on impact) and car/node/air (1 Hz) and
// drives the buzzer and RGB LED from car/cmd/alert. See docs/mqtt_contract.md.
//
// loop() is a non-blocking millis() scheduler: no delay(). Each module keeps
// its own timing; main only decides when to publish and log.

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "alert.h"
#include "config.h"
#include "imu.h"
#include "light.h"
#include "net.h"
#include "smoke.h"

namespace {

uint32_t lastMotion = 0, lastAir = 0, lastStatus = 0;
uint32_t motionSent = 0, airSent = 0, impactsSent = 0;

void onMessage(const char *topic, const uint8_t *payload, unsigned int len) {
  if (!strcmp(topic, TOPIC_ALERT)) alert_handle(payload, len);
}

void scanI2C() {
  Serial.printf("[i2c] scan on SDA %d / SCL %d:\n", I2C_SDA_PIN, I2C_SCL_PIN);
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      const char *what = addr == 0x68 || addr == 0x69 ? " (MPU6050)"
                                                      : "";
      Serial.printf("[i2c]   0x%02X%s\n", addr, what);
      found++;
    }
  }
  if (!found) Serial.println("[i2c]   nothing found (check wiring, 3V3, GND)");
}

void publishMotion(const ImuSample &s) {
  char buf[200];
  imu_motion_json(s, buf, sizeof(buf));
  if (net_publish(TOPIC_MOTION, buf)) motionSent++;
}

void publishAir(uint32_t now) {
  char smoke[48];
  smoke_json_fields(smoke, sizeof(smoke), now);
  float pct;
  int raw;
  bool dark;
  char light[64];
  if (light_take_report(pct, raw, dark))
    snprintf(light, sizeof(light), "\"light\":%.1f,\"light_raw\":%d,\"dark\":%s", pct, raw,
             dark ? "true" : "false");
  else
    snprintf(light, sizeof(light), "\"light\":null,\"dark\":null");
  char buf[160];
  snprintf(buf, sizeof(buf), "{\"ts\":0,%s,%s}", smoke, light);
  if (net_publish(TOPIC_AIR, buf)) airSent++;
}

void printStatus(uint32_t now) {
  char imu[32], smoke[48];
  if (imu_ready()) snprintf(imu, sizeof(imu), "a_mag %.2f g", imu_latest().a_mag);
  else snprintf(imu, sizeof(imu), "%s", imu_present() ? "calibrating" : "missing");
  if (smoke_valid(now))
    snprintf(smoke, sizeof(smoke), "%.0f ppm Rs/R0 %.2f (raw %d)", smoke_ppm(), smoke_ratio(),
             smoke_raw());
  else snprintf(smoke, sizeof(smoke), "null, %s (raw %d)", smoke_phase(now), smoke_raw());

  Serial.printf(
      "[status] up %lus | wifi %s %ddBm | mqtt %s (%s) | alert %s/%s | imu %s | "
      "light %.0f%% raw %d%s | smoke %s | sent m%lu a%lu i%lu fail %lu | heap %lu\n",
      (unsigned long)(now / 1000), net_wifi_up() ? "up" : "down",
      net_wifi_up() ? (int)WiFi.RSSI() : 0, net_mqtt_up() ? "up" : "down",
      net_broker_ip().c_str(), alert_level_name(), alert_reason(), imu, light_pct(),
      light_raw(), light_dark() ? " DARK" : "", smoke,
      (unsigned long)motionSent, (unsigned long)airSent, (unsigned long)impactsSent,
      (unsigned long)net_publish_fail_count(), (unsigned long)ESP.getFreeHeap());
}

}  // namespace

void setup() {
  Serial.begin(115200);
  // Native USB CDC: wait briefly for the host so the boot log isn't lost.
  // setup() only; loop() never delays.
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) {
  }
  Serial.println();
  Serial.println("=== ESP32-S3 sensor node (car drowsiness detector) ===");
  Serial.printf("chip %s rev %d, %d MHz, flash %lu, PSRAM %lu, heap %lu\n", ESP.getChipModel(),
                ESP.getChipRevision(), (int)ESP.getCpuFreqMHz(), (unsigned long)ESP.getFlashChipSize(),
                (unsigned long)ESP.getPsramSize(), (unsigned long)ESP.getFreeHeap());

  alert_begin();

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ_HZ);
  Wire.setTimeOut(20);
  scanI2C();

  imu_begin();
  light_begin();
  smoke_begin();
  net_begin(onMessage);
}

void loop() {
  uint32_t now = millis();

  net_loop(now);
  imu_update(now);
  light_update(now);
  smoke_update(now);
  alert_update(now, net_mqtt_down_ms(now));

  ImuSample hit;
  if (imu_take_impact(hit)) {
    publishMotion(hit);  // at once, don't wait for the 5 Hz tick
    impactsSent++;
  }
  if (now - lastMotion >= MOTION_PERIOD_MS) {
    lastMotion = now;
    if (imu_ready()) publishMotion(imu_latest());
  }
  if (now - lastAir >= AIR_PERIOD_MS) {
    lastAir = now;
    publishAir(now);
  }
  if (now - lastStatus >= STATUS_PERIOD_MS) {
    lastStatus = now;
    printStatus(now);
  }
}
