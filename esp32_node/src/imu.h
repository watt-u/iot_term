#pragma once
#include <Arduino.h>

// MPU6050 over raw I2C (no library). Wire must already be started.
struct ImuSample {
  float a[3];   // g
  float g[3];   // deg/s, gyro bias removed
  float a_mag;  // g
  float temp;   // deg C (die temperature, status line only)
  bool impact;  // a_mag > IMPACT_G
};

void imu_begin();
void imu_update(uint32_t now);  // reads at 200 Hz, runs calibration, retries if missing

bool imu_present();  // chip answered and reads work
bool imu_ready();    // present and gyro calibrated: OK to publish
const ImuSample &imu_latest();

// True once per impact event (rate-limited); copies the impact sample.
bool imu_take_impact(ImuSample &out);

// car/node/motion payload (docs/mqtt_contract.md). Returns length.
int imu_motion_json(const ImuSample &s, char *buf, size_t len);
