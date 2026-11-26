#include "light.h"

#include "config.h"

// Wiring: VCC -> 3V3, GND -> G, AO -> GPIO 4 (ADC1). DO is not used.
// Powered from 3V3, so AO never goes above 3.3 V and needs no divider.

namespace {
uint32_t lastRead = 0;
int raw = 0;
float pct = 0;
bool dark = false;
bool started = false;

float sumPct = 0;
long sumRaw = 0;
int count = 0;

float toPct(int adc) {
  float p = adc * 100.0f / 4095.0f;
#if LDR_DARK_IS_HIGH
  p = 100.0f - p;
#endif
  return constrain(p, 0.0f, 100.0f);
}
}  // namespace

void light_begin() {
  analogReadResolution(12);
  analogSetPinAttenuation(LDR_AO_PIN, ADC_11db);
  pinMode(LDR_AO_PIN, INPUT);
  Serial.printf("[light] LDR module on GPIO %d (%s)\n", LDR_AO_PIN,
                LDR_DARK_IS_HIGH ? "AO high = dark" : "AO high = bright");
}

void light_update(uint32_t now) {
  if (started && now - lastRead < LIGHT_READ_MS) return;
  lastRead = now;

  const int N = 8;
  uint32_t s = 0;
  for (int i = 0; i < N; i++) s += analogRead(LDR_AO_PIN);
  raw = s / N;
  pct = toPct(raw);

  if (!started) {
    dark = pct < LIGHT_DARK_ENTER_PCT;
    started = true;
  } else if (!dark && pct < LIGHT_DARK_ENTER_PCT) {
    dark = true;
    Serial.printf("[light] dark (%.0f %%)\n", pct);
  } else if (dark && pct > LIGHT_DARK_EXIT_PCT) {
    dark = false;
    Serial.printf("[light] light again (%.0f %%)\n", pct);
  }

  sumPct += pct;
  sumRaw += raw;
  count++;
}

float light_pct() { return pct; }
int light_raw() { return raw; }
bool light_dark() { return dark; }

bool light_take_report(float &outPct, int &outRaw, bool &outDark) {
  if (count == 0) return false;
  outPct = sumPct / count;
  outRaw = sumRaw / count;
  outDark = dark;
  sumPct = 0;
  sumRaw = 0;
  count = 0;
  return true;
}
