#include "co2.h"

#include "config.h"

namespace {
float ppm = 0;
bool haveReading = false;
uint32_t lastGood = 0;
uint32_t lastRead = 0;

void setReading(float v, uint32_t now) {
  ppm = v;
  haveReading = true;
  lastGood = now;
}
}  // namespace

bool co2_valid(uint32_t now) { return haveReading && now - lastGood < CO2_STALE_MS; }
float co2_ppm() { return ppm; }

// =============================================================================
#if CO2_SENSOR == CO2_MQ135
// MQ-135: AO (up to 5 V) -> 10k/20k divider -> GPIO 6. It is an air-quality
// sensor, so the ppm is only an estimate. Needs 5 V and a long heater burn-in.

namespace {
int raw = -1;
float r0 = MQ135_R0_KOHM;
uint32_t bootAt = 0;
double calSum = 0;
int calCount = 0;
bool warnedBad = false;
}  // namespace

const char *co2_model_name() { return "MQ-135"; }
int co2_raw() { return raw; }

void co2_begin() {
  analogSetPinAttenuation(CO2_AO_PIN, ADC_11db);
  pinMode(CO2_AO_PIN, INPUT);
  bootAt = millis();
  if (r0 > 0)
    Serial.printf("[co2] MQ-135 on GPIO %d, R0 = %.2f kOhm (fixed)\n", CO2_AO_PIN, r0);
  else
    Serial.printf("[co2] MQ-135 on GPIO %d, auto-calibrating R0 for %lu ms (assumes %.0f ppm air)\n",
                  CO2_AO_PIN, (unsigned long)MQ135_CAL_MS, MQ135_CAL_PPM);
}

void co2_update(uint32_t now) {
  if (now - lastRead < CO2_READ_MS) return;
  lastRead = now;

  const int N = 16;
  uint32_t rawSum = 0, mvSum = 0;
  for (int i = 0; i < N; i++) {
    rawSum += analogRead(CO2_AO_PIN);
    mvSum += analogReadMilliVolts(CO2_AO_PIN);
  }
  raw = rawSum / N;
  float vAdc = mvSum / (float)N / 1000.0f;
  float vAo = vAdc * MQ135_DIVIDER;

  // Pin at ~0 V or at the ADC limit: unplugged, no heater power, or no divider.
  if (vAo < 0.05f || vAdc > 3.2f) {
    if (!warnedBad) {
      Serial.printf("[co2] MQ-135 reading out of range (%.2f V at ADC), sending null\n", vAdc);
      warnedBad = true;
    }
    return;
  }
  warnedBad = false;
  float rs = MQ135_RL_KOHM * (MQ135_VC - vAo) / vAo;

  if (r0 <= 0) {
    calSum += rs;
    calCount++;
    if (now - bootAt >= MQ135_CAL_MS) {
      // ppm = A * (Rs/R0)^B  ->  R0 = Rs / (ppm/A)^(1/B)
      r0 = (calSum / calCount) / powf(MQ135_CAL_PPM / MQ135_A, 1.0f / MQ135_B);
      Serial.printf("[co2] MQ-135 R0 = %.2f kOhm (set MQ135_R0_KOHM to this to skip calibration)\n",
                    r0);
    }
    return;
  }
  float est = MQ135_A * powf(rs / r0, MQ135_B);
  setReading(constrain(est, 0.0f, 10000.0f), now);
}

// =============================================================================
#elif CO2_SENSOR == CO2_MHZ19
// MH-Z19B/C: UART 9600 8N1. 5 V power, 3.3 V logic. ESP RX=17 <- TX, ESP TX=18 -> RX.

namespace {
const uint8_t CMD_READ[9] = {0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79};
uint8_t frame[9];
int frameLen = 0;
bool warnedSilent = false;
}  // namespace

const char *co2_model_name() { return "MH-Z19"; }
int co2_raw() { return -1; }

void co2_begin() {
  Serial1.begin(9600, SERIAL_8N1, CO2_RX_PIN, CO2_TX_PIN);
  Serial.printf("[co2] MH-Z19 on UART1 RX %d / TX %d (needs ~3 min warm-up)\n", CO2_RX_PIN,
                CO2_TX_PIN);
}

void co2_update(uint32_t now) {
  while (Serial1.available()) {
    uint8_t b = Serial1.read();
    if (frameLen == 0 && b != 0xFF) continue;
    if (frameLen == 1 && b != 0x86) {
      frameLen = (b == 0xFF) ? 1 : 0;
      continue;
    }
    frame[frameLen++] = b;
    if (frameLen == 9) {
      frameLen = 0;
      uint8_t sum = 0;
      for (int i = 1; i < 8; i++) sum += frame[i];
      if ((uint8_t)(0xFF - sum + 1) == frame[8]) {
        setReading(frame[2] * 256 + frame[3], now);
        warnedSilent = false;
      }
    }
  }

  if (now - lastRead < CO2_READ_MS) return;
  lastRead = now;
  if (!warnedSilent && now > CO2_STALE_MS && !co2_valid(now)) {
    Serial.println("[co2] MH-Z19 not answering, sending null");
    warnedSilent = true;
  }
  frameLen = 0;
  while (Serial1.available()) Serial1.read();  // drop stale bytes
  Serial1.write(CMD_READ, sizeof(CMD_READ));
}

// =============================================================================
#elif CO2_SENSOR == CO2_SCD40
// Sensirion SCD40/41 on the shared I2C bus (0x62), raw I2C. Periodic mode
// gives a new value every 5 s. Every step is a small non-blocking state.
#include <Wire.h>

namespace {
const uint8_t ADDR = 0x62;
const uint16_t CMD_START = 0x21B1;
const uint16_t CMD_STOP = 0x3F86;
const uint16_t CMD_READY = 0xE4B8;
const uint16_t CMD_READ = 0xEC05;
const uint32_t CMD_WAIT_MS = 2;    // command -> read (datasheet: 1 ms)
const uint32_t STOP_WAIT_MS = 500;

enum class St { Missing, Stopping, Idle, WaitReady, WaitData };
St st = St::Missing;
uint32_t stAt = 0;
bool everFound = false;

uint8_t crc8(const uint8_t *d, int n) {
  uint8_t crc = 0xFF;
  for (int i = 0; i < n; i++) {
    crc ^= d[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : crc << 1;
  }
  return crc;
}

bool sendCmd(uint16_t cmd) {
  Wire.beginTransmission(ADDR);
  Wire.write(cmd >> 8);
  Wire.write(cmd & 0xFF);
  return Wire.endTransmission() == 0;
}

// Reads n 16-bit words (each followed by a CRC byte).
bool readWords(uint16_t *w, int n) {
  uint8_t len = n * 3;
  if (Wire.requestFrom(ADDR, len) != len) return false;
  bool ok = true;
  for (int i = 0; i < n; i++) {
    uint8_t b[3] = {(uint8_t)Wire.read(), (uint8_t)Wire.read(), (uint8_t)Wire.read()};
    if (crc8(b, 2) != b[2]) ok = false;
    w[i] = (b[0] << 8) | b[1];
  }
  return ok;
}

void lost(uint32_t now, const char *why) {
  Serial.printf("[co2] SCD40 %s, sending null and retrying every %lu s\n", why,
                (unsigned long)(CO2_RETRY_MS / 1000));
  st = St::Missing;
  stAt = now;
}

void tryInit(uint32_t now) {
  // Stop first in case it is still measuring from before a reset.
  if (sendCmd(CMD_STOP)) {
    st = St::Stopping;
  } else {
    st = St::Missing;
    if (!everFound) Serial.println("[co2] SCD40 not found at 0x62");
  }
  stAt = now;
}
}  // namespace

const char *co2_model_name() { return "SCD40"; }
int co2_raw() { return -1; }

void co2_begin() {
  Serial.println("[co2] SCD40 on I2C 0x62");
  tryInit(millis());
}

void co2_update(uint32_t now) {
  switch (st) {
    case St::Missing:
      if (now - stAt >= CO2_RETRY_MS) tryInit(now);
      break;
    case St::Stopping:
      if (now - stAt < STOP_WAIT_MS) break;
      if (!sendCmd(CMD_START)) return lost(now, "start failed");
      everFound = true;
      Serial.println("[co2] SCD40 periodic measurement started (first value in ~5 s)");
      st = St::Idle;
      lastRead = now;
      break;
    case St::Idle:
      if (now - lastRead < CO2_READ_MS) break;
      lastRead = now;
      if (!sendCmd(CMD_READY)) return lost(now, "not answering");
      st = St::WaitReady;
      stAt = now;
      break;
    case St::WaitReady: {
      if (now - stAt < CMD_WAIT_MS) break;
      uint16_t w;
      if (!readWords(&w, 1)) return lost(now, "ready-status read failed");
      if ((w & 0x07FF) == 0) {  // no new data yet
        st = St::Idle;
        break;
      }
      if (!sendCmd(CMD_READ)) return lost(now, "not answering");
      st = St::WaitData;
      stAt = now;
      break;
    }
    case St::WaitData: {
      if (now - stAt < CMD_WAIT_MS) break;
      uint16_t w[3];  // CO2 ppm, temperature, humidity
      bool ok = readWords(w, 3);
      st = St::Idle;
      if (!ok) {
        Serial.println("[co2] SCD40 CRC/read error, skipping sample");
        break;
      }
      if (w[0] > 0) setReading(w[0], now);
      break;
    }
  }
}

#else
#error "CO2_SENSOR must be CO2_MQ135, CO2_MHZ19 or CO2_SCD40"
#endif

int co2_json_fields(char *buf, size_t len, uint32_t now) {
  int n = co2_valid(now) ? snprintf(buf, len, "\"co2\":%.0f", ppm)
                         : snprintf(buf, len, "\"co2\":null");
  if (co2_raw() >= 0 && n > 0 && (size_t)n < len)
    n += snprintf(buf + n, len - n, ",\"co2_raw\":%d", co2_raw());
  return n;
}
