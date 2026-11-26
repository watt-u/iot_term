#include "smoke.h"

#include "config.h"

// MQ-2: VCC -> 5V (heater, ~150 mA), GND -> G, AO -> 10k -> GPIO 6, GPIO 6 -> 20k -> G.
// AO can reach 5 V, so it always goes through the divider. DO is not used.
//
// Rs = RL * (Vc - Vao) / Vao. R0 = Rs in clean air / 9.83 (datasheet), measured
// after the heater warm-up. Then ppm = A * (Rs/R0)^B on the smoke curve.

namespace {
float ppm = 0;
float ratio = 0;
bool haveReading = false;
uint32_t lastGood = 0;
uint32_t lastRead = 0;

int raw = -1;
float r0 = MQ2_R0_KOHM;
uint32_t bootAt = 0;
double calSum = 0;
int calCount = 0;
bool badSignal = false;
}  // namespace

bool smoke_valid(uint32_t now) { return haveReading && now - lastGood < SMOKE_STALE_MS; }
float smoke_ppm() { return ppm; }
float smoke_ratio() { return ratio; }
int smoke_raw() { return raw; }

const char *smoke_phase(uint32_t now) {
  if (badSignal) return "no signal";
  if (r0 > 0) return "ok";
  return now - bootAt < MQ2_WARMUP_MS ? "warm-up" : "calibrating";
}

void smoke_begin() {
  analogReadResolution(12);
  analogSetPinAttenuation(SMOKE_AO_PIN, ADC_11db);
  pinMode(SMOKE_AO_PIN, INPUT);
  bootAt = millis();
  if (r0 > 0)
    Serial.printf("[smoke] MQ-2 on GPIO %d, R0 = %.2f kOhm (fixed)\n", SMOKE_AO_PIN, r0);
  else
    Serial.printf("[smoke] MQ-2 on GPIO %d, warm-up %lu s, then R0 calibration %lu s (keep clean air)\n",
                  SMOKE_AO_PIN, (unsigned long)(MQ2_WARMUP_MS / 1000),
                  (unsigned long)(MQ2_CAL_MS / 1000));
}

void smoke_update(uint32_t now) {
  if (now - lastRead < SMOKE_READ_MS) return;
  lastRead = now;

  const int N = 16;
  uint32_t rawSum = 0, mvSum = 0;
  for (int i = 0; i < N; i++) {
    rawSum += analogRead(SMOKE_AO_PIN);
    mvSum += analogReadMilliVolts(SMOKE_AO_PIN);
  }
  raw = rawSum / N;
  float vAdc = mvSum / (float)N / 1000.0f;
  float vAo = vAdc * MQ2_DIVIDER;

  // Pin at ~0 V or at the ADC limit: unplugged, no heater power, or no divider.
  if (vAo < 0.05f || vAdc > 3.2f) {
    if (!badSignal) {
      Serial.printf("[smoke] MQ-2 reading out of range (%.2f V at ADC), sending null\n", vAdc);
      badSignal = true;
    }
    return;
  }
  if (badSignal) Serial.println("[smoke] MQ-2 signal back");
  badSignal = false;
  float rs = MQ2_RL_KOHM * (MQ2_VC - vAo) / vAo;

  if (r0 <= 0) {
    if (now - bootAt < MQ2_WARMUP_MS) return;  // heater still warming up
    calSum += rs;
    calCount++;
    if (now - bootAt >= MQ2_WARMUP_MS + MQ2_CAL_MS) {
      r0 = (calSum / calCount) / MQ2_CLEAN_AIR_RATIO;
      Serial.printf("[smoke] MQ-2 R0 = %.2f kOhm (set MQ2_R0_KOHM to this to skip calibration)\n",
                    r0);
    }
    return;
  }
  ratio = rs / r0;
  float est = MQ2_A * powf(ratio, MQ2_B);
  ppm = constrain(est, 0.0f, 10000.0f);
  haveReading = true;
  lastGood = now;
}

int smoke_json_fields(char *buf, size_t len, uint32_t now) {
  int n = smoke_valid(now) ? snprintf(buf, len, "\"smoke\":%.0f", ppm)
                           : snprintf(buf, len, "\"smoke\":null");
  if (raw >= 0 && n > 0 && (size_t)n < len)
    n += snprintf(buf + n, len - n, ",\"smoke_raw\":%d", raw);
  return n;
}
