#pragma once
#include <Arduino.h>

// MQ-2 smoke/gas sensor on SMOKE_AO_PIN (through a 10k/20k divider).
// Never blocks and never halts: a missing sensor or the warm-up just reports null.
void smoke_begin();
void smoke_update(uint32_t now);

bool smoke_valid(uint32_t now);  // a fresh, plausible reading exists
float smoke_ppm();               // last estimate (check smoke_valid first)
float smoke_ratio();             // last Rs/R0 (0 until calibrated)
int smoke_raw();                 // ADC counts, -1 before the first read
const char *smoke_phase(uint32_t now);  // "warm-up" | "calibrating" | "ok" | "no signal"

// Writes the smoke part of the car/node/air payload, e.g. "\"smoke\":42,\"smoke_raw\":512"
// or "\"smoke\":null,\"smoke_raw\":512". Returns length.
int smoke_json_fields(char *buf, size_t len, uint32_t now);
