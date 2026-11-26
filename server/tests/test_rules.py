"""Tests for rules.py. Time is driven by hand through a fake clock."""

import pytest

from rules import ALERT_OK, Alert, RulesEngine, Thresholds

CONTRACT = Thresholds(
    smoke_ppm=300,
    temp_c=35,
    distance_cm=25,
    distance_hold_s=3,
    no_face_hold_s=5,
    impact_hold_s=10,
    drowsy_clear_s=2,
    stale_s=5,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def eng(clock):
    return RulesEngine(CONTRACT, clock=clock)


def driver(state):
    return {"ts": 0, "ear": 0.3, "thresh": 0.21, "state": state, "closed_frames": 0, "fps": 15, "snapshot": None}


def motion(impact=False):
    return {"ts": 0, "ax": 0, "ay": 0, "az": 1, "gx": 0, "gy": 0, "gz": 0, "a_mag": 3.0 if impact else 1.0, "impact": impact}


def air(smoke=20):
    return {"ts": 0, "smoke": smoke, "smoke_raw": 400, "light": 60.0, "light_raw": 1600, "dark": False}


def cabin(temp=30.0, distance=50.0):
    return {"ts": 1.0, "temp": temp, "distance": distance}


def feed_all_normal(eng):
    eng.update("motion", motion())
    eng.update("air", air())
    eng.update("cabin", cabin())
    eng.update("driver", driver("open"))


# --------------------------------------------------------------------- basics
def test_no_data_is_ok(eng):
    assert eng.evaluate() == ALERT_OK
    assert eng.evaluate().level_num == 0


def test_all_normal_is_ok(eng):
    feed_all_normal(eng)
    assert eng.evaluate() == Alert("ok", "none")


def test_level_num():
    assert Alert("warning", "smoke").level_num == 1
    assert Alert("danger", "drowsy").level_num == 2


def test_unknown_source_raises(eng):
    with pytest.raises(ValueError):
        eng.update("bogus", {})


# --------------------------------------------------------------------- drowsy
def test_drowsy_is_danger_immediately(eng):
    eng.update("driver", driver("drowsy"))
    assert eng.evaluate() == Alert("danger", "drowsy")


def test_drowsy_clears_2s_after_open(eng, clock):
    eng.update("driver", driver("drowsy"))
    clock.advance(1)
    eng.update("driver", driver("open"))
    clock.advance(1.9)
    assert eng.evaluate().reason == "drowsy"
    clock.advance(0.1)
    assert eng.evaluate() == ALERT_OK


def test_drowsy_stays_while_closed(eng, clock):
    eng.update("driver", driver("drowsy"))
    for _ in range(10):
        clock.advance(0.5)
        eng.update("driver", driver("closed"))
    assert eng.evaluate().reason == "drowsy"


def test_drowsy_clear_timer_rearms_if_eyes_close_again(eng, clock):
    eng.update("driver", driver("drowsy"))
    eng.update("driver", driver("open"))
    clock.advance(1.5)
    eng.update("driver", driver("closed"))
    clock.advance(1.0)  # 2.5 s after the first open, but it was interrupted
    eng.update("driver", driver("open"))
    assert eng.evaluate().reason == "drowsy"
    clock.advance(2.0)
    assert eng.evaluate() == ALERT_OK


def test_repeated_open_does_not_restart_clear_timer(eng, clock):
    eng.update("driver", driver("drowsy"))
    eng.update("driver", driver("open"))
    for _ in range(4):
        clock.advance(0.5)
        eng.update("driver", driver("open"))
    assert eng.evaluate() == ALERT_OK


def test_drowsy_again_after_clear(eng, clock):
    eng.update("driver", driver("drowsy"))
    eng.update("driver", driver("open"))
    clock.advance(2)
    assert eng.evaluate() == ALERT_OK
    eng.update("driver", driver("drowsy"))
    assert eng.evaluate().reason == "drowsy"


def test_closed_without_drowsy_is_ok(eng):
    eng.update("driver", driver("closed"))
    assert eng.evaluate() == ALERT_OK


# --------------------------------------------------------------------- impact
def test_impact_held_10s(eng, clock):
    eng.update("motion", motion(impact=True))
    assert eng.evaluate() == Alert("danger", "impact")
    for _ in range(9):  # keep motion fresh with normal readings
        clock.advance(1)
        eng.update("motion", motion())
    clock.advance(0.9)
    assert eng.evaluate().reason == "impact"
    clock.advance(0.1)
    assert eng.evaluate() == ALERT_OK


def test_new_impact_extends_hold(eng, clock):
    eng.update("motion", motion(impact=True))
    clock.advance(4)
    eng.update("motion", motion(impact=True))
    clock.advance(4)
    eng.update("motion", motion())
    clock.advance(4)  # 12 s after the first, 8 s after the second
    eng.update("motion", motion())
    assert eng.evaluate().reason == "impact"


def test_impact_false_does_not_trigger(eng):
    eng.update("motion", motion(impact=False))
    assert eng.evaluate() == ALERT_OK


def test_impact_must_be_real_bool(eng):
    eng.update("motion", {"impact": "true"})
    assert eng.evaluate() == ALERT_OK


# ------------------------------------------------------------------ warnings
def test_smoke_warning(eng):
    eng.update("air", air(smoke=300))
    assert eng.evaluate() == ALERT_OK  # strictly greater than
    eng.update("air", air(smoke=301))
    assert eng.evaluate() == Alert("warning", "smoke")
    eng.update("air", air(smoke=50))
    assert eng.evaluate() == ALERT_OK


def test_heat_warning(eng):
    eng.update("cabin", cabin(temp=35.0))
    assert eng.evaluate() == ALERT_OK
    eng.update("cabin", cabin(temp=35.1))
    assert eng.evaluate() == Alert("warning", "heat")


def test_null_temp_does_not_warn(eng):
    eng.update("cabin", cabin(temp=40))
    eng.update("cabin", cabin(temp=None))
    assert eng.evaluate() == ALERT_OK


def test_too_close_needs_3s(eng, clock):
    eng.update("cabin", cabin(distance=20))
    clock.advance(1)
    eng.update("cabin", cabin(distance=19))
    clock.advance(1)
    eng.update("cabin", cabin(distance=18))
    clock.advance(0.9)
    assert eng.evaluate() == ALERT_OK
    clock.advance(0.1)
    assert eng.evaluate() == Alert("warning", "too_close")


def test_too_close_resets_on_far_reading(eng, clock):
    eng.update("cabin", cabin(distance=20))
    clock.advance(2)
    eng.update("cabin", cabin(distance=40))
    clock.advance(0.5)
    eng.update("cabin", cabin(distance=20))
    clock.advance(2.9)
    assert eng.evaluate() == ALERT_OK
    clock.advance(0.1)
    assert eng.evaluate().reason == "too_close"


def test_too_close_resets_on_failed_read(eng, clock):
    eng.update("cabin", cabin(distance=20))
    clock.advance(2)
    eng.update("cabin", cabin(distance=None))
    clock.advance(1)
    eng.update("cabin", cabin(distance=20))
    clock.advance(1)
    assert eng.evaluate() == ALERT_OK


def test_distance_exactly_threshold_is_not_close(eng, clock):
    eng.update("cabin", cabin(distance=25))
    clock.advance(4)
    eng.update("cabin", cabin(distance=25))
    assert eng.evaluate() == ALERT_OK


def test_no_face_needs_5s(eng, clock):
    eng.update("driver", driver("no_face"))
    for _ in range(4):
        clock.advance(1)
        eng.update("driver", driver("no_face"))
    clock.advance(0.9)
    assert eng.evaluate() == ALERT_OK
    clock.advance(0.1)
    assert eng.evaluate() == Alert("warning", "no_face")
    eng.update("driver", driver("open"))
    assert eng.evaluate() == ALERT_OK


def test_no_face_timer_resets(eng, clock):
    eng.update("driver", driver("no_face"))
    clock.advance(4)
    eng.update("driver", driver("open"))
    clock.advance(0.5)
    eng.update("driver", driver("no_face"))
    clock.advance(4)
    eng.update("driver", driver("no_face"))
    assert eng.evaluate() == ALERT_OK


# ------------------------------------------------------------------ priority
def test_danger_beats_warning(eng):
    eng.update("air", air(smoke=600))
    eng.update("cabin", cabin(temp=40))
    eng.update("motion", motion(impact=True))
    assert eng.evaluate() == Alert("danger", "impact")


def test_drowsy_wins_tie_with_impact(eng):
    eng.update("motion", motion(impact=True))
    eng.update("driver", driver("drowsy"))
    assert eng.evaluate() == Alert("danger", "drowsy")
    assert eng.active_reasons() == ["drowsy", "impact"]


def test_warning_order_is_stable(eng, clock):
    eng.update("air", air(smoke=400))
    eng.update("cabin", cabin(temp=40))
    assert eng.evaluate() == Alert("warning", "smoke")
    eng.update("air", air(smoke=20))
    assert eng.evaluate() == Alert("warning", "heat")


def test_impact_ends_then_drowsy_remains(eng, clock):
    eng.update("motion", motion(impact=True))
    eng.update("driver", driver("drowsy"))
    for _ in range(11):
        clock.advance(1)
        eng.update("motion", motion())
        eng.update("driver", driver("closed"))
    assert eng.evaluate() == Alert("danger", "drowsy")


# --------------------------------------------------------------------- stale
def test_all_sources_stale_at_start(eng):
    assert eng.stale_sources() == ["motion", "air", "cabin", "driver"]


def test_stale_after_5s(eng, clock):
    feed_all_normal(eng)
    clock.advance(5)
    assert eng.stale_sources() == []
    clock.advance(0.01)
    assert eng.stale_sources() == ["motion", "air", "cabin", "driver"]


def test_stale_driver_never_triggers_drowsy(eng, clock):
    eng.update("driver", driver("drowsy"))
    clock.advance(5.1)
    assert eng.evaluate() == ALERT_OK


def test_stale_driver_drops_latch(eng, clock):
    eng.update("driver", driver("drowsy"))
    clock.advance(6)
    assert eng.evaluate() == ALERT_OK
    # Vision comes back reporting "closed": the old drowsy must not come back.
    eng.update("driver", driver("closed"))
    assert eng.evaluate() == ALERT_OK


def test_stale_motion_never_triggers_impact(eng, clock):
    eng.update("motion", motion(impact=True))
    clock.advance(6)  # hold is 10 s, but the ESP32 went silent
    assert eng.evaluate() == ALERT_OK
    eng.update("motion", motion())
    assert eng.evaluate() == ALERT_OK  # hold was dropped while stale


def test_stale_air_drops_smoke_warning(eng, clock):
    eng.update("air", air(smoke=400))
    clock.advance(6)
    assert eng.evaluate() == ALERT_OK


def test_stale_cabin_drops_warnings(eng, clock):
    eng.update("cabin", cabin(temp=40, distance=10))
    clock.advance(6)
    assert eng.evaluate() == ALERT_OK


def test_fresh_source_still_works_when_another_is_stale(eng, clock):
    eng.update("driver", driver("drowsy"))
    eng.update("air", air(smoke=400))
    clock.advance(6)
    eng.update("air", air(smoke=400))
    assert eng.evaluate() == Alert("warning", "smoke")


def test_bad_values_are_ignored(eng):
    eng.update("air", {"smoke": "lots"})
    eng.update("cabin", {"temp": float("nan"), "distance": True})
    eng.update("driver", {"state": 3})
    assert eng.evaluate() == ALERT_OK


def test_explicit_now_overrides_clock(clock):
    eng = RulesEngine(CONTRACT, clock=clock)
    eng.update("driver", driver("drowsy"), now=0.0)
    assert eng.evaluate(now=1.0).reason == "drowsy"
    assert eng.evaluate(now=6.0) == ALERT_OK


def test_server_thresholds_match_contract():
    import server

    assert server.THRESHOLDS == CONTRACT
