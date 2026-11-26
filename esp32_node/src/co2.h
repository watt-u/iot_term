#pragma once
#include <Arduino.h>

// CO2 sensor, model picked with CO2_SENSOR in config.h (MQ-135 / MH-Z19 / SCD40).
// Never blocks and never halts: a missing or failed sensor just reports null.
void co2_begin();
void co2_update(uint32_t now);

bool co2_valid(uint32_t now);  // a fresh, plausible reading exists
float co2_ppm();               // last reading (check co2_valid first)
int co2_raw();                 // MQ-135 ADC counts, -1 for other models
const char *co2_model_name();

// Writes the CO2 part of the car/node/air payload, e.g. "\"co2\":820,\"co2_raw\":1234"
// or "\"co2\":null". Returns length.
int co2_json_fields(char *buf, size_t len, uint32_t now);
