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
#include "co2.h"
#include "config.h"
#include "imu.h"
#include "mic.h"
#include "net.h"

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
                         : addr == 0x62               ? " (SCD40)"
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
  float sound;
  bool loud;
  mic_take_report(sound, loud);
  char co2[48];
  co2_json_fields(co2, sizeof(co2), now);
  char buf[160];
  snprintf(buf, sizeof(buf), "{\"ts\":0,%s,\"sound\":%.1f,\"loud\":%s}", co2, sound,
           loud ? "true" : "false");
  if (net_publish(TOPIC_AIR, buf)) airSent++;
}

void printStatus(uint32_t now) {
  char imu[32], co2[40];
  if (imu_ready()) snprintf(imu, sizeof(imu), "a_mag %.2f g", imu_latest().a_mag);
  else snprintf(imu, sizeof(imu), "%s", imu_present() ? "calibrating" : "missing");
  if (co2_valid(now)) snprintf(co2, sizeof(co2), "%.0f ppm", co2_ppm());
  else snprintf(co2, sizeof(co2), "null");
  if (co2_raw() >= 0) {
    size_t n = strlen(co2);
    snprintf(co2 + n, sizeof(co2) - n, " (raw %d)", co2_raw());
  }

  Serial.printf(
      "[status] up %lus | wifi %s %ddBm | mqtt %s (%s) | alert %s/%s | imu %s | "
      "sound %.1f bg %.1f%s | co2 %s | sent m%lu a%lu i%lu fail %lu | heap %lu\n",
      (unsigned long)(now / 1000), net_wifi_up() ? "up" : "down",
      net_wifi_up() ? (int)WiFi.RSSI() : 0, net_mqtt_up() ? "up" : "down",
      net_broker_ip().c_str(), alert_level_name(), alert_reason(), imu, mic_level(),
      mic_background(), mic_loud() ? " LOUD" : "", co2,
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
  Serial.printf("CO2 model: %s\n", co2_model_name());

  alert_begin();

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ_HZ);
  Wire.setTimeOut(20);
  scanI2C();

  imu_begin();
  mic_begin();
  co2_begin();
  net_begin(onMessage);
}

void loop() {
  uint32_t now = millis();

  net_loop(now);
  imu_update(now);
  mic_update(now);
  co2_update(now);
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
