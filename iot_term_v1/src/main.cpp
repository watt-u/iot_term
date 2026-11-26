#include <Arduino.h>

// Sound sensor: trigger on sudden, really loud sounds, even in a loud room.
// (KY-037 / KY-038 style module: AO, G, +, DO)
//
// Wiring:
//   Module +   -> ESP32 3V3
//   Module G   -> ESP32 GND
//   Module AO  -> GPIO 4  (ADC1, analog loudness)
//   Module DO  -> GPIO 5  (not needed here, shown for reference)
//
// How it works:
//   - Every 20 ms: measure how much AO wiggles (mean absolute deviation).
//   - "background" = slow running average of that level. It keeps following
//     the room, so a constantly loud room becomes the new normal.
//     It rises slowly (a short bang barely moves it) and falls faster.
//   - TRIGGER when the current level > background * LOUD_FACTOR.
//   - One line when it triggers, one when it ends. Then a short cooldown.

#define RGB_PIN 48     // onboard RGB LED (try 38 if nothing lights up)
#define MIC_AO_PIN 4   // ADC1_CH3
#define MIC_DO_PIN 5

// ---- Tuning ---------------------------------------------------------------
const float LOUD_FACTOR = 5.0;        // trigger at N x the room's background
const float MIN_LEVEL = 5.0;          // also require level >= this (0 = off)
const uint32_t MIN_LOUD_MS = 0;       // must stay loud this long (0 = any bang)
const uint32_t COOLDOWN_MS = 1000;    // ignore new triggers for this long after
const float BG_RISE_SEC = 10.0;       // background follows a louder room in ~10 s
const float BG_FALL_SEC = 2.0;        // ...and a quieter room in ~2 s
const uint32_t STATUS_EVERY_MS = 5000;  // print background every N ms (0 = off)
// ---------------------------------------------------------------------------

const uint32_t WINDOW_MS = 20;
const int MAX_SAMPLES = 1024;
uint16_t samples[MAX_SAMPLES];

float background = 0;
bool triggered = false;
bool armed = false;            // above threshold, waiting for MIN_LOUD_MS
uint32_t aboveSince = 0, trigStart = 0, lastEnd = 0, lastStatus = 0;
float peakRatio = 0;

float measureWindow() {
  int n = 0;
  long sum = 0;
  uint32_t start = millis();
  while (millis() - start < WINDOW_MS && n < MAX_SAMPLES) {
    samples[n] = analogRead(MIC_AO_PIN);
    sum += samples[n++];
  }
  float mean = (float)sum / n;
  float dev = 0;
  for (int i = 0; i < n; i++) dev += fabsf(samples[i] - mean);
  return dev / n;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  analogReadResolution(12);
  analogSetPinAttenuation(MIC_AO_PIN, ADC_11db);
  pinMode(MIC_DO_PIN, INPUT);

  Serial.println("Loud-sound trigger - learning room background (2 s)...");
  rgbLedWrite(RGB_PIN, 0, 0, 40);  // blue while learning
  measureWindow();                 // discard first window
  float sum = 0;
  int w = 0;
  uint32_t start = millis();
  while (millis() - start < 2000) { sum += measureWindow(); w++; }
  background = sum / w;
  rgbLedWrite(RGB_PIN, 0, 0, 0);
  Serial.printf("Background: %.1f  trigger above: %.1f (x%.1f)\n", background,
                background * LOUD_FACTOR, LOUD_FACTOR);
}

void loop() {
  float level = measureWindow();
  uint32_t now = millis();
  float ratio = background > 0.1 ? level / background : 0;
  bool above = level > background * LOUD_FACTOR && level >= MIN_LEVEL;

  // Update background: rise slowly, fall faster. Freeze it during a trigger
  // so the loud event itself doesn't become the new normal.
  if (!triggered) {
    float sec = level > background ? BG_RISE_SEC : BG_FALL_SEC;
    float alpha = (WINDOW_MS / 1000.0) / sec;
    background += (level - background) * alpha;
  }

  if (!triggered) {
    if (above && now - lastEnd > COOLDOWN_MS) {
      if (!armed) { armed = true; aboveSince = now; }
      if (now - aboveSince >= MIN_LOUD_MS) {
        triggered = true;
        armed = false;
        trigStart = now;
        peakRatio = ratio;
        Serial.printf("[%lu ms] *** LOUD! level:%.1f = x%.1f background (%.1f)\n",
                      now, level, ratio, background);
        rgbLedWrite(RGB_PIN, 60, 0, 0);  // red
      }
    } else {
      armed = false;
    }
  } else {
    if (ratio > peakRatio) peakRatio = ratio;
    // End once it drops back under half the trigger level (hysteresis).
    if (level < background * (1 + (LOUD_FACTOR - 1) / 2)) {
      triggered = false;
      lastEnd = now;
      Serial.printf("[%lu ms]     ended (%lu ms, peak x%.1f)\n", now,
                    now - trigStart, peakRatio);
      rgbLedWrite(RGB_PIN, 0, 0, 0);
    }
  }

  if (STATUS_EVERY_MS && now - lastStatus >= STATUS_EVERY_MS) {
    lastStatus = now;
    Serial.printf("[%lu ms] background:%.1f  now:%.1f (x%.1f)\n", now,
                  background, level, ratio);
  }
}
