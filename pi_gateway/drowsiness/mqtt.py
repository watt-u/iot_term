"""Small MQTT publisher that reconnects by itself and never blocks the caller.

Used by the vision loop (uv venv, paho-mqtt 2.x) and by sensors.py (system
python3, apt python3-paho-mqtt). The paho 1.x API is supported as a fallback
so an older apt package still works.

If the broker is down, publish() drops the message (QoS 0 sensor data) and
returns False. paho's background thread keeps retrying the connection.
"""
import json
import threading

import paho.mqtt.client as mqtt


def _ok(rc):
    """True for a successful connect reason code (paho 2 ReasonCode or paho 1 int)."""
    if hasattr(rc, "is_failure"):
        return not rc.is_failure
    return rc == 0


class Publisher:
    def __init__(self, host="localhost", port=1883, client_id="", keepalive=30, name="mqtt"):
        self.host, self.port, self.name = host, port, name
        self._connected = threading.Event()
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:  # paho-mqtt 1.x
            self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        # connect_async + loop_start: the network thread makes the first attempt
        # and keeps retrying, so a missing broker never raises here.
        self.client.connect_async(host, port, keepalive)
        self.client.loop_start()

    # paho 2: (client, userdata, flags, reason_code, properties)
    # paho 1: (client, userdata, flags, rc)
    def _on_connect(self, client, userdata, flags, rc, *rest):
        if _ok(rc):
            self._connected.set()
            print(f"{self.name}: connected to {self.host}:{self.port}", flush=True)
        else:
            print(f"{self.name}: connect refused ({rc})", flush=True)

    # paho 2: (client, userdata, flags, reason_code, properties)
    # paho 1: (client, userdata, rc)
    def _on_disconnect(self, client, userdata, *rest):
        if self._connected.is_set():
            print(f"{self.name}: disconnected, retrying", flush=True)
        self._connected.clear()

    @property
    def connected(self):
        return self._connected.is_set()

    def publish(self, topic, payload, qos=0, retain=False):
        """Publishes a dict as JSON. Returns True if handed to paho, False if dropped."""
        if not self.connected:
            return False
        try:
            info = self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:  # never let MQTT crash the caller
            print(f"{self.name}: publish failed: {e}", flush=True)
            return False

    def close(self):
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:
            pass
