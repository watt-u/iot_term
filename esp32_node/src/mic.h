#pragma once
#include <Arduino.h>

// KY-037/038 sound module on MIC_AO_PIN: sound level + adaptive loud trigger
// (logic from commit f567fad, made non-blocking: each mic_update() call samples
// for at most MIC_SAMPLE_BUDGET_US and a 20 ms window is closed when it is full).
void mic_begin();
void mic_update(uint32_t now);

float mic_level();       // last 20 ms window (mean absolute deviation, ADC counts)
float mic_background();  // adaptive room background
bool mic_loud();         // loud trigger active right now

// For the 1 Hz car/node/air message: the loudest 20 ms window since the last
// call, and whether a loud trigger was active at any point since the last call.
void mic_take_report(float &sound, bool &loud);
