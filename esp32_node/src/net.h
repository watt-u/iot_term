#pragma once
#include <Arduino.h>

// Wi-Fi + MQTT. Call net_begin() once and net_loop() every loop.
typedef void (*MessageHandler)(const char *topic, const uint8_t *payload, unsigned int len);

void net_begin(MessageHandler onMessage);
void net_loop(uint32_t now);

bool net_wifi_up();
bool net_mqtt_up();
// How long MQTT has been down (0 while connected; time since boot if it never connected).
uint32_t net_mqtt_down_ms(uint32_t now);

bool net_publish(const char *topic, const char *payload, bool retain = false);

// For the status line.
const char *net_client_id();
String net_broker_ip();
uint32_t net_publish_count();
uint32_t net_publish_fail_count();
uint32_t net_reconnect_count();
