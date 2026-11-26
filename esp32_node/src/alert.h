#pragma once
#include <Arduino.h>

// car/cmd/alert -> KY-016 RGB LED + KY-012 active buzzer.
//   ok      -> green
//   warning -> yellow
//   danger  -> red + buzzer beeping 200 ms on / 200 ms off
//   MQTT down > 5 s, level "offline", or no alert for 6 s -> blink blue, buzzer off
//   no alert received yet -> LED off
void alert_begin();
void alert_handle(const uint8_t *payload, unsigned int len);
void alert_update(uint32_t now, uint32_t mqttDownMs);

const char *alert_level_name();
const char *alert_reason();
