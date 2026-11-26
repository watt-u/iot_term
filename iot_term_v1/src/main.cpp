#include <Arduino.h>
#include <Wire.h>

// MPU6050 test (GY-521 board), raw I2C, no library needed.
//
// Wiring:
//   MPU6050 VCC -> ESP32 3V3
//   MPU6050 GND -> ESP32 GND
//   MPU6050 SCL -> GPIO 9
//   MPU6050 SDA -> GPIO 10
//   AD0 / INT / XDA / XCL: leave unconnected (AD0 floating/low = address 0x68)
//
// At boot: scans the I2C bus, checks the chip ID, then calibrates the gyro
// (keep the board STILL, LED blue; it restarts calibration if it moves).
// Then prints 10x per second:
//   accel in g, gyro in deg/s, temperature, and pitch/roll angles.

#define RGB_PIN 48
#define SDA_PIN 10
#define SCL_PIN 9

const uint32_t PRINT_EVERY_MS = 100;

// MPU6050 registers
const uint8_t REG_SMPLRT_DIV = 0x19;
const uint8_t REG_CONFIG = 0x1A;
const uint8_t REG_GYRO_CONFIG = 0x1B;
const uint8_t REG_ACCEL_CONFIG = 0x1C;
const uint8_t REG_ACCEL_XOUT_H = 0x3B;
const uint8_t REG_PWR_MGMT_1 = 0x6B;
const uint8_t REG_WHO_AM_I = 0x75;

const float ACCEL_SCALE = 16384.0;  // LSB per g at +/-2 g
const float GYRO_SCALE = 131.0;     // LSB per deg/s at +/-250 deg/s

uint8_t mpuAddr = 0x68;
float gyroBias[3] = {0, 0, 0};
float pitch = 0, roll = 0;
uint32_t lastUpdate = 0, lastPrint = 0;

bool writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(mpuAddr, len) != len) return false;
  for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
  return true;
}

// ax..az in g, gx..gz in deg/s (bias removed), temp in C
bool readMpu(float a[3], float g[3], float &temp) {
  uint8_t b[14];
  if (!readRegs(REG_ACCEL_XOUT_H, b, 14)) return false;
  auto s16 = [&](int i) { return (int16_t)((b[i] << 8) | b[i + 1]); };
  for (int i = 0; i < 3; i++) a[i] = s16(i * 2) / ACCEL_SCALE;
  temp = s16(6) / 340.0 + 36.53;
  for (int i = 0; i < 3; i++) g[i] = s16(8 + i * 2) / GYRO_SCALE - gyroBias[i];
  return true;
}

void scanI2C() {
  Serial.println("I2C scan:");
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  found device at 0x%02X\n", addr);
      found++;
    }
  }
  if (!found) Serial.println("  nothing found - check wiring (SDA=8, SCL=9, 3V3, GND)");
}

// When the MPU isn't found: the GY-521 has pull-up resistors on SDA/SCL, so a
// powered, connected module makes its pins read HIGH even with the ESP32's
// pull-down on. Use that to find which pins it's really on, then try I2C there.
void diagnoseWiring() {
  Wire.end();
  const uint8_t pins[] = {1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
                          17, 18, 21, 38, 39, 40, 41, 42, 47};
  uint8_t high[sizeof(pins)];
  int nHigh = 0;
  Serial.println("Wiring check (pins pulled HIGH by the module's resistors):");
  for (uint8_t p : pins) {
    pinMode(p, INPUT_PULLDOWN);
    delay(2);
    if (digitalRead(p)) high[nHigh++] = p;
  }
  pinMode(SDA_PIN, INPUT_PULLDOWN);
  pinMode(SCL_PIN, INPUT_PULLDOWN);
  delay(2);
  Serial.printf("  GPIO %d (SDA): %s\n", SDA_PIN,
                digitalRead(SDA_PIN) ? "HIGH - module seen" : "LOW - no module on this pin");
  Serial.printf("  GPIO %d (SCL): %s\n", SCL_PIN,
                digitalRead(SCL_PIN) ? "HIGH - module seen" : "LOW - no module on this pin");
  if (nHigh == 0) {
    Serial.println("  No pin is pulled high -> module has no power (VCC/GND) or "
                   "isn't connected / header not soldered.");
    return;
  }
  Serial.print("  Pins pulled high:");
  for (int i = 0; i < nHigh; i++) Serial.printf(" %d", high[i]);
  Serial.println();

  for (int i = 0; i < nHigh; i++) {
    for (int j = 0; j < nHigh; j++) {
      if (i == j) continue;
      Wire.begin(high[i], high[j], 100000);
      for (uint8_t addr : {0x68, 0x69}) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
          Serial.printf("  >>> MPU found at 0x%02X with SDA=GPIO %d, SCL=GPIO %d\n",
                        addr, high[i], high[j]);
        }
      }
      Wire.end();
    }
  }
}

void halt(const char *msg) {
  Serial.println(msg);
  while (true) {  // blink red forever
    rgbLedWrite(RGB_PIN, 40, 0, 0); delay(300);
    rgbLedWrite(RGB_PIN, 0, 0, 0);  delay(300);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nMPU6050 test");

  Wire.begin(SDA_PIN, SCL_PIN, 400000);
  scanI2C();

  // Find the MPU at 0x68 (AD0 low) or 0x69 (AD0 high).
  uint8_t id = 0;
  for (uint8_t addr : {0x68, 0x69}) {
    mpuAddr = addr;
    if (readRegs(REG_WHO_AM_I, &id, 1)) break;
    id = 0;
  }
  if (!id) {
    diagnoseWiring();
    halt("MPU6050 not responding at 0x68/0x69.");
  }
  // Real MPU6050 = 0x68. Clones / MPU6500 / MPU9250 often report other IDs
  // but the registers we use are the same, so just warn.
  Serial.printf("MPU at 0x%02X, WHO_AM_I = 0x%02X%s\n", mpuAddr, id,
                id == 0x68 ? " (MPU6050)" : " (clone/variant - should still work)");

  writeReg(REG_PWR_MGMT_1, 0x01);   // wake up, clock = gyro X PLL
  delay(100);
  writeReg(REG_SMPLRT_DIV, 0x07);   // 1 kHz / (1+7) = 125 Hz
  writeReg(REG_CONFIG, 0x03);       // low-pass filter ~44 Hz (less jitter)
  writeReg(REG_GYRO_CONFIG, 0x00);  // +/-250 deg/s
  writeReg(REG_ACCEL_CONFIG, 0x00); // +/-2 g

  // Gyro calibration: average while still.
  Serial.println("Calibrating gyro - keep the board still...");
  rgbLedWrite(RGB_PIN, 0, 0, 40);
  // Repeat until the board was still the whole time (low spread on all axes).
  const int N = 400;
  const float MAX_SPREAD_DPS = 1.0;  // std dev allowed while "still"
  float a[3], g[3], t;
  while (true) {
    float sum[3] = {0, 0, 0}, sq[3] = {0, 0, 0};
    for (int i = 0; i < N; i++) {
      if (!readMpu(a, g, t)) halt("Read failed during calibration.");
      for (int k = 0; k < 3; k++) { sum[k] += g[k]; sq[k] += g[k] * g[k]; }
      delay(5);
    }
    float worst = 0;
    for (int k = 0; k < 3; k++) {
      float mean = sum[k] / N;
      float sd = sqrtf(fmaxf(sq[k] / N - mean * mean, 0));
      worst = fmaxf(worst, sd);
      gyroBias[k] = mean;
    }
    if (worst <= MAX_SPREAD_DPS) break;
    Serial.printf("  board moved (spread %.1f deg/s) - hold still, retrying...\n",
                  worst);
  }
  rgbLedWrite(RGB_PIN, 0, 0, 0);
  Serial.printf("Gyro bias: %.2f %.2f %.2f deg/s\n", gyroBias[0], gyroBias[1],
                gyroBias[2]);

  // Start angles from the accelerometer.
  readMpu(a, g, t);
  pitch = atan2f(-a[0], sqrtf(a[1] * a[1] + a[2] * a[2])) * RAD_TO_DEG;
  roll = atan2f(a[1], a[2]) * RAD_TO_DEG;
  lastUpdate = micros();
}

void loop() {
  float a[3], g[3], temp;
  if (!readMpu(a, g, temp)) {
    Serial.println("Read failed - loose wire?");
    delay(500);
    return;
  }

  // Complementary filter: gyro for fast/smooth changes, accel to stop drift.
  uint32_t now = micros();
  float dt = (now - lastUpdate) / 1e6f;
  lastUpdate = now;
  float accPitch = atan2f(-a[0], sqrtf(a[1] * a[1] + a[2] * a[2])) * RAD_TO_DEG;
  float accRoll = atan2f(a[1], a[2]) * RAD_TO_DEG;
  pitch = 0.98f * (pitch + g[1] * dt) + 0.02f * accPitch;
  roll = 0.98f * (roll + g[0] * dt) + 0.02f * accRoll;

  // LED: green when flat, shifts to red as it tilts.
  float tilt = constrain(max(fabsf(pitch), fabsf(roll)), 0.0f, 45.0f);
  uint8_t r = tilt / 45.0f * 50, gr = 50 - r;
  rgbLedWrite(RGB_PIN, r, gr, 0);

  if (millis() - lastPrint >= PRINT_EVERY_MS) {
    lastPrint = millis();
    Serial.printf(
        "acc g: %5.2f %5.2f %5.2f | gyro dps: %7.1f %7.1f %7.1f | %4.1fC | "
        "pitch:%6.1f roll:%6.1f\n",
        a[0], a[1], a[2], g[0], g[1], g[2], temp, pitch, roll);
  }
  delay(5);
}
