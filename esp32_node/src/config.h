#pragma once
// Pins, rates and tuning for the ESP32-S3 sensor node.
// Topics and payloads follow docs/mqtt_contract.md.

#include <Arduino.h>

// ---- CO2 sensor model -------------------------------------------------------
// Pick one. You can also override it from platformio.ini:
//   build_flags = ... -DCO2_SENSOR=CO2_SCD40
#define CO2_MQ135 1  // analog, AO on CO2_AO_PIN through a 10k/20k divider
#define CO2_MHZ19 2  // UART on CO2_RX_PIN / CO2_TX_PIN, 9600 baud
#define CO2_SCD40 3  // I2C on the shared bus, address 0x62
#ifndef CO2_SENSOR
#define CO2_SENSOR CO2_MQ135
#endif

// ---- Pins -------------------------------------------------------------------
// Avoid 19/20 (native USB), 26-37 (flash/PSRAM), 0/3/45/46 (strapping).
// Analog inputs must be on ADC1 (GPIO 1-10): ADC2 stops working with Wi-Fi on.
#define I2C_SDA_PIN 10
#define I2C_SCL_PIN 9
#define I2C_FREQ_HZ 400000

#define MIC_AO_PIN 4  // KY-037/038 AO (ADC1_CH3)

#define CO2_AO_PIN 6   // MQ-135 AO via divider (ADC1_CH5)
#define CO2_RX_PIN 17  // ESP32 RX  <- MH-Z19 TX
#define CO2_TX_PIN 18  // ESP32 TX  -> MH-Z19 RX

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

// ---- Mic (same tuning as commit f567fad) ------------------------------------
const uint32_t MIC_WINDOW_MS = 20;
const float MIC_LOUD_FACTOR = 5.0f;   // trigger at N x the room's background
const float MIC_MIN_LEVEL = 5.0f;     // also require level >= this
const uint32_t MIC_COOLDOWN_MS = 1000;
const float MIC_BG_RISE_SEC = 10.0f;  // background follows a louder room in ~10 s
const float MIC_BG_FALL_SEC = 2.0f;   // ...and a quieter room in ~2 s
const uint32_t MIC_LEARN_MS = 2000;   // learn the background before triggering
const uint32_t MIC_SAMPLE_BUDGET_US = 1000;  // max time per mic_update() call

// ---- CO2 --------------------------------------------------------------------
// MQ-135 estimate: ppm = A * (Rs/R0)^B (common datasheet curve fit for CO2).
const float MQ135_A = 116.6020682f;
const float MQ135_B = -2.769034857f;
const float MQ135_RL_KOHM = 1.0f;       // load resistor on the module (often 1k, "102")
const float MQ135_VC = 5.0f;            // heater/circuit supply
const float MQ135_DIVIDER = 1.5f;       // V_AO = V_adc * (10k+20k)/20k
const float MQ135_R0_KOHM = 0.0f;       // 0 = auto-calibrate at boot (assumes fresh air)
const float MQ135_CAL_PPM = 420.0f;     // fresh-air CO2 used for auto-calibration
const uint32_t MQ135_CAL_MS = 10000;    // average this long for auto-calibration
const uint32_t CO2_READ_MS = 1000;
const uint32_t CO2_STALE_MS = 15000;    // no good reading this long -> send null
const uint32_t CO2_RETRY_MS = 10000;    // SCD40 re-init when missing
