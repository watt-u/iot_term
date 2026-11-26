"""Vision state machine, rolling fps and payload (pure code, no camera)."""
import json

import pytest

from drowsiness.logic import (
    CLOSED, DROWSY, NO_FACE, OPEN, DriverState, RollingFps, Throttle, build_payload,
)

T = 0.21


def feed(ds, ears):
    return [ds.update(e, T) for e in ears]


def test_logic_has_no_heavy_imports():
    import drowsiness.logic as logic
    src = open(logic.__file__).read()
    assert "import cv2" not in src and "mediapipe" not in src


def test_open_then_closed_then_drowsy():
    ds = DriverState(frames_needed=3)
    out = feed(ds, [0.30, 0.10, 0.10, 0.10, 0.10])
    assert [s for s, _, _ in out] == [OPEN, CLOSED, CLOSED, DROWSY, DROWSY]
    assert [c for _, c, _ in out] == [True, True, False, True, False]
    assert [b for _, _, b in out] == [False, False, False, True, False]
    assert ds.closed_frames == 4


def test_open_resets_counter():
    ds = DriverState(frames_needed=3)
    feed(ds, [0.1, 0.1, 0.1])
    assert ds.state == DROWSY
    state, changed, became = ds.update(0.3, T)
    assert (state, changed, became) == (OPEN, True, False)
    assert ds.closed_frames == 0
    # a fresh run of closed frames has to reach the limit again
    assert [s for s, _, _ in feed(ds, [0.1, 0.1])] == [CLOSED, CLOSED]


def test_no_face_resets_counter_and_is_a_state():
    ds = DriverState(frames_needed=2)
    feed(ds, [0.1, 0.1])
    state, changed, became = ds.update(None, T)
    assert (state, changed, became) == (NO_FACE, True, False)
    assert ds.closed_frames == 0
    assert ds.update(None, T) == (NO_FACE, False, False)


def test_threshold_is_strict():
    ds = DriverState(frames_needed=1)
    assert ds.update(T, T)[0] == OPEN  # equal to threshold counts as open
    assert ds.update(T - 0.001, T)[0] == DROWSY


def test_first_frame_counts_as_change():
    assert DriverState().update(0.3, T) == (OPEN, True, False)


def test_rolling_fps_steady():
    fps = RollingFps(window=30)
    assert fps.tick(0.0) == 0.0  # one frame: unknown
    for i in range(1, 100):
        v = fps.tick(i / 15.0)
    assert v == pytest.approx(15.0)


def test_rolling_fps_uses_only_last_window():
    fps = RollingFps(window=30)
    t = 0.0
    for _ in range(100):  # slow start at 5 fps
        t += 0.2
        fps.tick(t)
    for _ in range(30):  # then 20 fps
        t += 0.05
        v = fps.tick(t)
    assert v == pytest.approx(20.0)
    assert len(fps.times) == 30


def test_rolling_fps_zero_span():
    fps = RollingFps()
    fps.tick(1.0)
    assert fps.tick(1.0) == 0.0


def test_throttle_2hz_and_on_change():
    th = Throttle(period=0.5)
    assert th.due(0.0)
    assert not th.due(0.2)
    assert th.due(0.3, changed=True)  # state change goes out at once
    assert not th.due(0.6)            # timer restarted at 0.3
    assert th.due(0.8)
    sent = sum(th.due(1.0 + i * 0.01) for i in range(100))  # 1 s of 100 fps
    assert sent == 2


def test_payload_matches_contract():
    p = build_payload(1764140000.5, 0.27341, 0.2109, OPEN, 0, 14.63)
    assert p == {"ts": 1764140000.5, "ear": 0.273, "thresh": 0.211, "state": "open",
                 "closed_frames": 0, "fps": 14.6, "snapshot": None}
    json.dumps(p)  # serializable


def test_payload_no_face_has_null_ear():
    p = build_payload(1.0, None, 0.21, NO_FACE, 0, 10)
    assert p["ear"] is None and p["state"] == "no_face"


def test_payload_snapshot_only_when_drowsy():
    path = "/home/bum/iot_term/pi_gateway/alerts/drowsy_1.jpg"
    assert build_payload(1, 0.1, 0.21, DROWSY, 15, 15, path)["snapshot"] == path
    assert build_payload(1, 0.1, 0.21, CLOSED, 3, 15, path)["snapshot"] is None


def test_payload_rejects_unknown_state():
    with pytest.raises(ValueError):
        build_payload(1, 0.3, 0.21, "sleepy", 0, 15)


def test_numpy_floats_serialize():
    np = pytest.importorskip("numpy")
    p = build_payload(np.float64(1.5), np.float64(0.25), np.float32(0.2), OPEN, np.int64(0), np.float64(15))
    json.dumps(p)
