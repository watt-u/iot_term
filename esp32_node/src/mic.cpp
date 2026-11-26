#include "mic.h"

#include "config.h"

// Wiring: + -> 3V3, G -> GND, AO -> GPIO 4 (ADC1). DO is not used.
//
// - Every 20 ms window: level = mean absolute deviation of the AO samples.
// - background = slow running average of level (rises slowly, falls faster),
//   frozen while triggered so the loud event doesn't become the new normal.
// - TRIGGER when level > background * LOUD_FACTOR (and >= MIN_LEVEL), then a cooldown.

namespace {

const int MAX_SAMPLES = 1024;
const int MIN_SAMPLES = 8;            // fewer than this: skip the window
const uint32_t MAX_WINDOW_MS = 60;    // loop was blocked (e.g. MQTT connect): drop window

uint16_t samples[MAX_SAMPLES];
int nSamples = 0;
long sampleSum = 0;
uint32_t windowStart = 0;
bool windowOpen = false;

uint32_t bootAt = 0;
bool learning = true;
float learnSum = 0;
int learnCount = 0;

float level = 0, background = 0;
bool triggered = false;
uint32_t trigStart = 0, lastEnd = 0;
float peakRatio = 0;

float reportPeak = 0;
bool reportLoud = false;

void processWindow(float lvl, uint32_t now, uint32_t windowMs) {
  level = lvl;
  if (lvl > reportPeak) reportPeak = lvl;

  if (learning) {
    learnSum += lvl;
    learnCount++;
    if (now - bootAt >= MIC_LEARN_MS && learnCount > 0) {
      background = learnSum / learnCount;
      learning = false;
      Serial.printf("[mic] background %.1f, trigger above %.1f (x%.1f)\n", background,
                    background * MIC_LOUD_FACTOR, MIC_LOUD_FACTOR);
    }
    return;
  }

  float ratio = background > 0.1f ? lvl / background : 0;
  bool above = lvl > background * MIC_LOUD_FACTOR && lvl >= MIC_MIN_LEVEL;

  if (!triggered) {
    float sec = lvl > background ? MIC_BG_RISE_SEC : MIC_BG_FALL_SEC;
    float alpha = fminf((windowMs / 1000.0f) / sec, 1.0f);
    background += (lvl - background) * alpha;

    if (above && now - lastEnd > MIC_COOLDOWN_MS) {
      triggered = true;
      reportLoud = true;
      trigStart = now;
      peakRatio = ratio;
      Serial.printf("[mic] *** LOUD level %.1f = x%.1f background (%.1f)\n", lvl, ratio,
                    background);
    }
  } else {
    if (ratio > peakRatio) peakRatio = ratio;
    // End once it drops under half the trigger level (hysteresis).
    if (lvl < background * (1 + (MIC_LOUD_FACTOR - 1) / 2)) {
      triggered = false;
      lastEnd = now;
      Serial.printf("[mic]     loud ended (%lu ms, peak x%.1f)\n",
                    (unsigned long)(now - trigStart), peakRatio);
    }
  }
}

void closeWindow(uint32_t now) {
  uint32_t windowMs = now - windowStart;
  windowOpen = false;
  if (nSamples < MIN_SAMPLES || windowMs > MAX_WINDOW_MS) return;
  float mean = (float)sampleSum / nSamples;
  float dev = 0;
  for (int i = 0; i < nSamples; i++) dev += fabsf(samples[i] - mean);
  processWindow(dev / nSamples, now, windowMs);
}

}  // namespace

void mic_begin() {
  analogReadResolution(12);
  analogSetPinAttenuation(MIC_AO_PIN, ADC_11db);
  pinMode(MIC_AO_PIN, INPUT);
  bootAt = millis();
  Serial.printf("[mic] KY-037/038 on GPIO %d, learning background (%lu ms)\n", MIC_AO_PIN,
                (unsigned long)MIC_LEARN_MS);
}

void mic_update(uint32_t now) {
  if (!windowOpen) {
    windowOpen = true;
    windowStart = now;
    nSamples = 0;
    sampleSum = 0;
  }
  uint32_t t0 = micros();
  while (micros() - t0 < MIC_SAMPLE_BUDGET_US && nSamples < MAX_SAMPLES &&
         millis() - windowStart < MIC_WINDOW_MS) {
    uint16_t v = analogRead(MIC_AO_PIN);
    samples[nSamples++] = v;
    sampleSum += v;
  }
  uint32_t t = millis();
  if (t - windowStart >= MIC_WINDOW_MS || nSamples >= MAX_SAMPLES) closeWindow(t);
}

float mic_level() { return level; }
float mic_background() { return background; }
bool mic_loud() { return triggered; }

void mic_take_report(float &sound, bool &loud) {
  sound = reportPeak;
  loud = reportLoud || triggered;
  reportPeak = 0;
  reportLoud = false;
}
