"""Tests for server.py: InfluxDB mapping, alert publishing, caption wiring. No network."""

import json

import pytest

import server as srv
from rules import Alert


# ------------------------------------------------------------------ mapping
def test_motion_mapping_replaces_ts_zero():
    p = srv.to_point(
        "car/node/motion",
        {"ts": 0, "ax": 0.01, "ay": -0.02, "az": 1, "gx": 0.4, "gy": -0.1, "gz": 0, "a_mag": 1, "impact": False},
        recv_ts=1764140000.123,
    )
    assert p["measurement"] == "motion"
    assert p["tags"] == {"source": "esp32"}
    assert p["time"] == 1764140000123
    assert p["fields"] == {
        "ax": 0.01, "ay": -0.02, "az": 1.0, "gx": 0.4, "gy": -0.1, "gz": 0.0, "a_mag": 1.0, "impact": False,
    }
    assert all(isinstance(p["fields"][k], float) for k in ("az", "gz", "a_mag"))  # ints become floats


def test_air_mapping_ignores_extra_fields():
    p = srv.to_point(
        "car/node/air",
        {"ts": 0, "smoke": 42, "smoke_raw": 512, "light": 63.5, "light_raw": 1495, "dark": False, "extra": 1},
        1.0,
    )
    assert p["measurement"] == "air"
    assert p["tags"] == {"source": "esp32"}
    assert p["fields"] == {"smoke": 42.0, "smoke_raw": 512, "light": 63.5, "light_raw": 1495, "dark": False}


def test_air_mapping_skips_null_smoke_during_warmup():
    payload = {"ts": 0, "smoke": None, "smoke_raw": 300, "light": 10.0, "light_raw": 3700, "dark": True}
    p = srv.to_point("car/node/air", payload, 1.0)
    assert p["fields"] == {"smoke_raw": 300, "light": 10.0, "light_raw": 3700, "dark": True}


def test_cabin_mapping_keeps_sender_ts_and_skips_nulls():
    p = srv.to_point("car/gateway/cabin", {"ts": 1764140000.1, "temp": 31.4, "distance": None}, 1764140000.5)
    assert p["measurement"] == "cabin"
    assert p["tags"] == {"source": "pi"}
    assert p["fields"] == {"temp": 31.4}
    assert p["time"] == 1764140000100


def test_cabin_all_null_is_not_written():
    assert srv.to_point("car/gateway/cabin", {"ts": 1.0, "temp": None, "distance": None}, 1.0) is None


@pytest.mark.parametrize("state,drowsy", [("open", 0), ("closed", 0), ("drowsy", 1), ("no_face", 0)])
def test_driver_mapping(state, drowsy):
    p = srv.to_point(
        "car/vision/driver",
        {"ts": 1764140000.5, "ear": 0.27, "thresh": 0.21, "state": state, "closed_frames": 3, "fps": 14.6, "snapshot": None},
        1764140000.6,
    )
    assert p["measurement"] == "driver"
    assert p["tags"] == {"source": "pi", "state": state}
    assert p["fields"] == {"ear": 0.27, "thresh": 0.21, "closed_frames": 3, "fps": 14.6, "drowsy": drowsy}
    assert isinstance(p["fields"]["closed_frames"], int)


def test_driver_no_face_null_ear():
    p = srv.to_point("car/vision/driver", {"ts": 5.0, "ear": None, "state": "no_face", "fps": 15}, 5.0)
    assert p["fields"] == {"fps": 15.0, "drowsy": 0}


def test_driver_unknown_state_tag():
    p = srv.to_point("car/vision/driver", {"ts": 0, "state": "weird", "fps": 1}, 2.0)
    assert p["tags"]["state"] == "unknown"


def test_unknown_topic_not_mapped():
    assert srv.to_point("car/test", {"x": 1}, 1.0) is None
    assert srv.to_point("car/cmd/alert", {"level": "ok"}, 1.0) is None


@pytest.mark.parametrize("ts", [0, None, "x", True, -5, float("nan"), 1e15])
def test_point_time_falls_back_to_receive_time(ts):
    assert srv.point_time({"ts": ts}, 1764140000.0) == 1764140000.0


def test_point_time_missing_ts():
    assert srv.point_time({}, 42.0) == 42.0


def test_bad_bool_and_number_values_dropped():
    p = srv.to_point("car/node/motion", {"ts": 0, "ax": "nope", "ay": True, "impact": 1, "a_mag": 1.2}, 1.0)
    assert p["fields"] == {"a_mag": 1.2}


def test_alert_point_and_payload():
    a = Alert("danger", "drowsy")
    assert srv.alert_point(a, 10.5) == {
        "measurement": "alert", "tags": {"level": "danger", "reason": "drowsy"}, "fields": {"level_num": 2}, "time": 10500,
    }
    assert srv.alert_point(a, 10.5, caption="eyes closed")["fields"] == {"level_num": 2, "caption": "eyes closed"}
    assert srv.alert_payload(Alert("ok", "none"), 1.23456) == {"ts": 1.235, "level": "ok", "reason": "none"}


# ------------------------------------------------------------------- server
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeCaptioner:
    def __init__(self):
        self.jobs = []

    def submit(self, path, on_done):
        self.jobs.append((path, on_done))
        return True


@pytest.fixture
def rig():
    class Rig:
        pass

    r = Rig()
    r.published, r.points = [], []
    r.connected = True
    r.mono, r.wall = Clock(100.0), Clock(1764140000.0)
    r.cap = FakeCaptioner()

    def publish(topic, payload, qos, retain):
        if not r.connected:
            return False
        r.published.append((topic, json.loads(payload), qos, retain))
        return True

    r.server = srv.Server(publish=publish, write=r.points.append, captioner=r.cap, wall=r.wall, mono=r.mono)

    def advance(dt):
        r.mono.t += dt
        r.wall.t += dt

    r.advance = advance
    r.alerts = lambda: [p for p in r.points if p["measurement"] == "alert"]
    return r


def send(server, topic, payload):
    server.on_message(topic, json.dumps(payload).encode())


def test_first_tick_publishes_ok_retained_qos1(rig):
    rig.server.tick()
    assert rig.published == [("car/cmd/alert", {"ts": 1764140000.0, "level": "ok", "reason": "none"}, 1, True)]
    assert rig.alerts()[0]["tags"] == {"level": "ok", "reason": "none"}


def test_heartbeat_every_2s_without_extra_writes(rig):
    rig.server.tick()
    for _ in range(7):  # 1.75 s
        rig.advance(0.25)
        rig.server.tick()
    assert len(rig.published) == 1
    rig.advance(0.25)
    rig.server.tick()
    assert len(rig.published) == 2
    assert len(rig.alerts()) == 1  # only changes go to InfluxDB


def test_drowsy_publishes_immediately_on_vision_message(rig):
    rig.server.tick()
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy", "fps": 15, "snapshot": None})
    topic, payload, qos, retain = rig.published[-1]
    assert (payload["level"], payload["reason"], qos, retain) == ("danger", "drowsy", 1, True)
    assert rig.alerts()[-1]["fields"] == {"level_num": 2}
    driver_points = [p for p in rig.points if p["measurement"] == "driver"]
    assert driver_points[0]["fields"]["drowsy"] == 1


def test_drowsy_clears_after_open(rig):
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy"})
    rig.advance(0.5)
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "open"})
    rig.advance(1.75)
    rig.server.tick()
    assert rig.server.current == Alert("danger", "drowsy")
    rig.advance(0.25)
    rig.server.tick()
    assert rig.server.current == Alert("ok", "none")
    assert rig.published[-1][1]["level"] == "ok"


def test_sensor_messages_are_written(rig):
    send(rig.server, "car/node/air", {"ts": 0, "smoke": 400, "smoke_raw": 1800, "light": 50.0, "light_raw": 2000, "dark": False})
    air = [p for p in rig.points if p["measurement"] == "air"]
    assert air[0]["time"] == 1764140000000
    rig.server.tick()
    assert rig.server.current == Alert("warning", "smoke")


def test_ignores_own_alert_and_unknown_topics(rig):
    send(rig.server, "car/cmd/alert", {"level": "danger", "reason": "drowsy"})
    rig.server.on_message("car/test", b"hi")
    assert rig.points == []


def test_bad_json_is_ignored(rig):
    rig.server.on_message("car/node/air", b"{not json")
    rig.server.on_message("car/node/air", b"[1, 2]")
    rig.server.on_message("car/node/air", b"\xff\xfe")
    assert rig.points == []


def test_disconnected_publish_retried_next_tick(rig):
    rig.connected = False
    rig.server.tick()
    assert rig.published == []
    rig.connected = True
    rig.advance(0.25)
    rig.server.tick()
    assert len(rig.published) == 1


def test_on_connected_forces_publish(rig):
    rig.server.tick()
    rig.advance(0.25)
    rig.server.on_connected()
    rig.server.tick()
    assert len(rig.published) == 2


def test_snapshot_caption_is_written_on_the_alert_event_row(rig):
    rig.server.tick()
    rig.advance(1)
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy", "snapshot": "/home/bum/alerts/x.jpg"})
    event = rig.alerts()[-1]
    assert len(rig.cap.jobs) == 1
    path, done = rig.cap.jobs[0]
    assert path == "/home/bum/alerts/x.jpg"

    rig.advance(3)  # the AI call takes a while
    done("The driver's eyes are closed and the head is tilted forward.", 3.0)
    cap = rig.alerts()[-1]
    assert cap["time"] == event["time"]
    assert cap["tags"] == {"level": "danger", "reason": "drowsy"}
    assert cap["fields"] == {"level_num": 2, "caption": "The driver's eyes are closed and the head is tilted forward."}


def test_unavailable_caption_is_written(rig):
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy", "snapshot": "/x.jpg"})
    rig.cap.jobs[0][1]("unavailable", 0.1)
    assert rig.alerts()[-1]["fields"]["caption"] == "unavailable"


def test_no_caption_without_snapshot(rig):
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy", "snapshot": None})
    send(rig.server, "car/vision/driver", {"ts": 0, "state": "drowsy", "snapshot": ""})
    assert rig.cap.jobs == []


def test_load_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO_TEST_A=1\nFOO_TEST_B = 'two words'\nFOO_TEST_C=keep\nnot a line\n")
    monkeypatch.delenv("FOO_TEST_A", raising=False)
    monkeypatch.delenv("FOO_TEST_B", raising=False)
    monkeypatch.setenv("FOO_TEST_C", "real")
    srv.load_env(env)
    import os

    assert os.environ["FOO_TEST_A"] == "1"
    assert os.environ["FOO_TEST_B"] == "two words"
    assert os.environ["FOO_TEST_C"] == "real"
