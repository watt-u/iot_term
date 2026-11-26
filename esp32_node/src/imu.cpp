#include "imu.h"

#include <Wire.h>

#include "config.h"

// Wiring: VCC 3V3, GND, SDA GPIO 10, SCL GPIO 9, AD0 low/floating (0x68).
// Code moved from the earlier MPU6050 test (commit f05a69a), made non-blocking.

namespace {

const uint8_t REG_SMPLRT_DIV = 0x19;
const uint8_t REG_CONFIG = 0x1A;
const uint8_t REG_GYRO_CONFIG = 0x1B;
const uint8_t REG_ACCEL_CONFIG = 0x1C;
const uint8_t REG_ACCEL_XOUT_H = 0x3B;
const uint8_t REG_PWR_MGMT_1 = 0x6B;
const uint8_t REG_WHO_AM_I = 0x75;

// +/-8 g: the old test used +/-2 g, which saturates below the 2.5 g impact threshold.
const uint8_t ACCEL_FS = 0x10;
const float ACCEL_SCALE = 4096.0f;  // LSB per g at +/-8 g
const uint8_t GYRO_FS = 0x08;
const float GYRO_SCALE = 65.5f;     // LSB per deg/s at +/-500 deg/s

// Calibration: average CAL_N samples while still; retry if it moved.
const int CAL_N = 400;                 // 400 x 5 ms = 2 s
const float CAL_MAX_SPREAD_DPS = 1.0f; // std dev allowed while "still"
const int CAL_MAX_TRIES = 5;           // then accept anyway (car may never be still)
const int MAX_READ_FAILS = 20;         // ~100 ms of failed reads -> treat as missing

enum class State { Missing, Calibrating, Running };

State state = State::Missing;
uint8_t addr = 0x68;
float gyroBias[3] = {0, 0, 0};
ImuSample latest = {};
ImuSample impactSample = {};
bool impactPending = false;
uint32_t lastImpactAt = 0;
bool impactEverSent = false;
uint32_t lastSample = 0, lastProbe = 0;
int readFails = 0;

int calCount = 0, calTries = 0;
float calSum[3], calSq[3];

bool writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, len) != len) return false;
  for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
  return true;
}

// Raw gyro (bias not removed) so calibration can use it too.
bool readMpu(float a[3], float gRaw[3], float &temp) {
  uint8_t b[14];
  if (!readRegs(REG_ACCEL_XOUT_H, b, 14)) return false;
  auto s16 = [&](int i) { return (int16_t)((b[i] << 8) | b[i + 1]); };
  for (int i = 0; i < 3; i++) a[i] = s16(i * 2) / ACCEL_SCALE;
  temp = s16(6) / 340.0f + 36.53f;
  for (int i = 0; i < 3; i++) gRaw[i] = s16(8 + i * 2) / GYRO_SCALE;
  return true;
}

void startCalibration() {
  calCount = 0;
  for (int k = 0; k < 3; k++) calSum[k] = calSq[k] = 0;
  state = State::Calibrating;
}

bool probe() {
  uint8_t id = 0;
  for (uint8_t a : {0x68, 0x69}) {
    addr = a;
    if (readRegs(REG_WHO_AM_I, &id, 1)) break;
    id = 0;
  }
  if (!id) return false;
  // Clones / MPU6500 / MPU9250 report other IDs but share these registers.
  Serial.printf("[imu] MPU at 0x%02X, WHO_AM_I 0x%02X%s\n", addr, id,
                id == 0x68 ? " (MPU6050)" : " (clone/variant, should still work)");
  bool ok = writeReg(REG_PWR_MGMT_1, 0x01);  // wake up, clock = gyro X PLL
  ok &= writeReg(REG_SMPLRT_DIV, 0x04);      // 1 kHz / (1+4) = 200 Hz
  ok &= writeReg(REG_CONFIG, 0x02);          // DLPF ~94 Hz (keeps short impact peaks)
  ok &= writeReg(REG_GYRO_CONFIG, GYRO_FS);
  ok &= writeReg(REG_ACCEL_CONFIG, ACCEL_FS);
  if (!ok) {
    Serial.println("[imu] config write failed");
    return false;
  }
  Serial.println("[imu] calibrating gyro, keep the board still (~2 s)...");
  calTries = 0;
  readFails = 0;
  startCalibration();
  return true;
}

void finishCalibrationStep() {
  float worst = 0;
  float bias[3];
  for (int k = 0; k < 3; k++) {
    float mean = calSum[k] / CAL_N;
    float sd = sqrtf(fmaxf(calSq[k] / CAL_N - mean * mean, 0));
    worst = fmaxf(worst, sd);
    bias[k] = mean;
  }
  calTries++;
  if (worst > CAL_MAX_SPREAD_DPS && calTries < CAL_MAX_TRIES) {
    Serial.printf("[imu] board moved (spread %.1f deg/s), retrying calibration (%d/%d)\n", worst,
                  calTries, CAL_MAX_TRIES);
    startCalibration();
    return;
  }
  for (int k = 0; k < 3; k++) gyroBias[k] = bias[k];
  Serial.printf("[imu] gyro bias %.2f %.2f %.2f deg/s%s\n", gyroBias[0], gyroBias[1], gyroBias[2],
                worst > CAL_MAX_SPREAD_DPS ? " (board never still; accepted anyway)" : "");
  state = State::Running;
}

}  // namespace

void imu_begin() {
  lastProbe = millis();
  if (!probe()) Serial.println("[imu] MPU6050 not found at 0x68/0x69, will retry every 5 s");
}

void imu_update(uint32_t now) {
  if (state == State::Missing) {
    if (now - lastProbe >= IMU_RETRY_MS) {
      lastProbe = now;
      probe();
    }
    return;
  }
  if (now - lastSample < IMU_SAMPLE_MS) return;
  lastSample = now;

  float a[3], g[3], t;
  if (!readMpu(a, g, t)) {
    if (++readFails >= MAX_READ_FAILS) {
      Serial.println("[imu] reads failing (loose wire?), marking IMU missing");
      state = State::Missing;
      lastProbe = now;
    }
    return;
  }
  readFails = 0;

  if (state == State::Calibrating) {
    for (int k = 0; k < 3; k++) {
      calSum[k] += g[k];
      calSq[k] += g[k] * g[k];
    }
    if (++calCount >= CAL_N) finishCalibrationStep();
    return;
  }

  ImuSample s;
  for (int k = 0; k < 3; k++) {
    s.a[k] = a[k];
    s.g[k] = g[k] - gyroBias[k];
  }
  s.temp = t;
  s.a_mag = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
  s.impact = s.a_mag > IMPACT_G;
  latest = s;

  if (s.impact) {
    if (!impactPending && (!impactEverSent || now - lastImpactAt >= IMPACT_MIN_GAP_MS)) {
      impactSample = s;
      impactPending = true;
      impactEverSent = true;
      lastImpactAt = now;
      Serial.printf("[imu] *** IMPACT a_mag %.2f g\n", s.a_mag);
    } else if (impactPending && s.a_mag > impactSample.a_mag) {
      impactSample = s;  // not sent yet: keep the peak
    }
  }
}

bool imu_present() { return state != State::Missing; }
bool imu_ready() { return state == State::Running; }
const ImuSample &imu_latest() { return latest; }

bool imu_take_impact(ImuSample &out) {
  if (!impactPending) return false;
  out = impactSample;
  impactPending = false;
  return true;
}

int imu_motion_json(const ImuSample &s, char *buf, size_t len) {
  return snprintf(buf, len,
                  "{\"ts\":0,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.2f,\"gy\":%.2f,"
                  "\"gz\":%.2f,\"a_mag\":%.3f,\"impact\":%s}",
                  s.a[0], s.a[1], s.a[2], s.g[0], s.g[1], s.g[2], s.a_mag,
                  s.impact ? "true" : "false");
}
