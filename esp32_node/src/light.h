#pragma once
#include <Arduino.h>

// LDR photosensitive module (LM393 board) on LDR_AO_PIN, powered from 3V3.
// Reports cabin light as 0-100 % (0 = dark, 100 = bright) and a "dark" flag
// with hysteresis, so night driving shows up on the dashboard.
void light_begin();
void light_update(uint32_t now);

float light_pct();  // latest sample, 0-100 %
int light_raw();    // latest ADC counts
bool light_dark();  // dark flag (hysteresis)

// For the 1 Hz car/node/air message: average light % and the mean raw ADC counts
// since the last call, and the current dark flag. Returns false if no samples yet.
bool light_take_report(float &pct, int &raw, bool &dark);
