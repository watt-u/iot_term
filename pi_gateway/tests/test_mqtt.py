"""Publisher: never blocks or raises without a broker; really publishes with one."""
import json
import socket
import threading
import time

from drowsiness.mqtt import Publisher


def test_publish_without_broker_is_fast_and_safe():
    t0 = time.monotonic()
    pub = Publisher("127.0.0.1", 1, client_id="pytest")  # nothing listens on port 1
    try:
        for _ in range(100):
            assert pub.publish("car/test", {"ts": 0}) is False
        assert not pub.connected
    finally:
        pub.close()
    assert time.monotonic() - t0 < 2.0


def test_unresolvable_host_does_not_raise():
    pub = Publisher("no-such-host.invalid", 1883, client_id="pytest2")
    try:
        assert pub.publish("car/test", {"ts": 0}) is False
    finally:
        pub.close()


# --- a tiny in-process MQTT 3.1.1 broker stub, enough for CONNECT + QoS 0 PUBLISH ---


def _read_packet(conn):
    first = conn.recv(1)
    if not first:
        return None, None
    mult, length = 1, 0
    while True:
        b = conn.recv(1)[0]
        length += (b & 0x7F) * mult
        mult *= 128
        if not b & 0x80:
            break
    body = b""
    while len(body) < length:
        chunk = conn.recv(length - len(body))
        if not chunk:
            return None, None
        body += chunk
    return first[0] >> 4, body


class StubBroker:
    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.messages = []
        self.got = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        conn, _ = self.sock.accept()
        with conn:
            while True:
                kind, body = _read_packet(conn)
                if kind is None or kind == 14:  # closed or DISCONNECT
                    return
                if kind == 1:  # CONNECT -> CONNACK accepted
                    conn.sendall(b"\x20\x02\x00\x00")
                elif kind == 3:  # PUBLISH, QoS 0
                    n = int.from_bytes(body[:2], "big")
                    self.messages.append((body[2:2 + n].decode(), json.loads(body[2 + n:])))
                    self.got.set()
                elif kind == 12:  # PINGREQ -> PINGRESP
                    conn.sendall(b"\xd0\x00")


def test_connects_and_publishes_json():
    broker = StubBroker()
    pub = Publisher("127.0.0.1", broker.port, client_id="pytest3")
    try:
        deadline = time.monotonic() + 5
        while not pub.connected and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pub.connected
        assert pub.publish("car/vision/driver", {"ts": 1.5, "state": "open", "snapshot": None})
        assert broker.got.wait(5)
    finally:
        pub.close()
    assert broker.messages == [("car/vision/driver", {"ts": 1.5, "state": "open", "snapshot": None})]
