#pragma once
// Pins, rates and tuning for the ESP32-S3 sensor node.
// Topics and payloads follow docs/mqtt_contract.md.

#include <Arduino.h>

// ---- Pins -------------------------------------------------------------------
// Avoid 19/20 (native USB), 26-37 (flash/PSRAM), 0/3/45/46 (strapping).
// Analog inputs must be on ADC1 (GPIO 1-10): ADC2 stops working with Wi-Fi on.
#define I2C_SDA_PIN 10
#define I2C_SCL_PIN 9
#define I2C_FREQ_HZ 400000

#define LDR_AO_PIN 4    // LDR photosensitive module AO, powered from 3V3 (ADC1_CH3)
#define SMOKE_AO_PIN 6  // MQ-2 AO via 10k/20k divider (ADC1_CH5)

#define BUZZER_PIN 12  // KY-012 active buzzer, HIGH = sound
#define LED_R_PIN 13   // KY-016 RGB LED, common cathode
#define LED_G_PIN 14
#define LED_B_PIN 21

#define ONBOARD_RGB_PIN 48  // onboard WS2812 (some DevKitC revisions use 38)
#define MIRROR_ONBOARD_RGB 1

// ---- MQTT topics (docs/mqtt_contract.md) -----------------------------------
#define TOPIC_MOTION "car/node/motion"
#define TOPIC_AIR "car/node/air"
#define TOPIC_ALERT "car/cmd/alert"

// ---- Rates ------------------------------------------------------------------
const uint32_t MOTION_PERIOD_MS = 200;   // 5 Hz
const uint32_t AIR_PERIOD_MS = 1000;     // 1 Hz
const uint32_t STATUS_PERIOD_MS = 5000;  // serial status line

// ---- Network ----------------------------------------------------------------
const uint32_t WIFI_RETRY_MS = 10000;      // restart Wi-Fi if still down after this
const uint32_t MQTT_RETRY_MS = 2000;       // gap between MQTT connect attempts
const uint32_t MDNS_TIMEOUT_MS = 1000;     // MDNS.queryHost timeout (blocks)
const uint8_t MQTT_FAILS_BEFORE_RESOLVE = 3;  // re-run mDNS after N failed connects
const uint16_t MQTT_BUFFER_SIZE = 512;
const uint16_t MQTT_KEEPALIVE_S = 10;
const uint16_t MQTT_SOCKET_TIMEOUT_S = 2;

// ---- IMU --------------------------------------------------------------------
const float IMPACT_G = 2.5f;              // impact when a_mag > this
const uint32_t IMU_SAMPLE_MS = 5;         // read the MPU6050 at 200 Hz
const uint32_t IMPACT_MIN_GAP_MS = 200;   // limit immediate impact publishes
const uint32_t IMU_RETRY_MS = 5000;       // retry init if the MPU is missing

// ---- Smoke (MQ-2) -----------------------------------------------------------
// Estimate: ppm = A * (Rs/R0)^B, fitted to the smoke curve of the MQ-2 datasheet
// (log-log line through 200 ppm @ Rs/R0 = 3.4 with slope -0.44).
// The MQ-2 also reacts to LPG, propane, H2 and alcohol, so this is an estimate.
const float MQ2_A = 3197.0f;
const float MQ2_B = -2.273f;
const float MQ2_CLEAN_AIR_RATIO = 9.83f;  // Rs/R0 in clean air (datasheet)
const float MQ2_RL_KOHM = 1.0f;           // load resistor on the module (often 1k, "102")
const float MQ2_VC = 5.0f;                // heater/circuit supply
const float MQ2_DIVIDER = 1.5f;           // V_AO = V_adc * (10k+20k)/20k
const float MQ2_R0_KOHM = 0.0f;           // 0 = auto-calibrate at boot (assumes clean air)
const uint32_t MQ2_WARMUP_MS = 20000;     // heater warm-up before calibrating
const uint32_t MQ2_CAL_MS = 10000;        // then average this long for R0
const uint32_t SMOKE_READ_MS = 1000;
const uint32_t SMOKE_STALE_MS = 15000;    // no good reading this long -> send null

// ---- Light (LDR module) -------------------------------------------------------
// Most LM393 LDR modules give a HIGH AO in the dark. Set to 0 if yours is the other way.
#define LDR_DARK_IS_HIGH 1
const uint32_t LIGHT_READ_MS = 200;       // sample at 5 Hz, report the 1 s average
const float LIGHT_DARK_ENTER_PCT = 15.0f; // dark when light < this ...
const float LIGHT_DARK_EXIT_PCT = 25.0f;  // ... and light again when > this (hysteresis)
