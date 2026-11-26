"""Alert rules engine (pure logic, no I/O). Rules: docs/mqtt_contract.md -> "Alert rules".

The engine keeps the latest value from each source and turns it into one alert
level (`ok` | `warning` | `danger`) and one reason. It never reads the clock by
itself unless you let it: every method takes an optional `now` (seconds, any
monotonic base), and the default comes from the injected `clock`. Tests drive
time by hand; server.py uses time.monotonic.

Rules (thresholds come from a `Thresholds` object; server.py holds the values):

- danger:  vision state == "drowsy" (latched; clears `drowsy_clear_s` after
           vision reports "open" again, and re-arms if it reports anything else)
           impact == true (held `impact_hold_s` after the last impact message)
- warning: smoke > smoke_ppm, temp > temp_c,
           distance < distance_cm continuously for `distance_hold_s`,
           state == "no_face" continuously for `no_face_hold_s`
- ok:      none of the above

The highest level wins. Inside a level, the reason follows REASON_PRIORITY,
so `drowsy` wins a tie with `impact`.

Stale data: a source silent for more than `stale_s` is stale. A stale source
triggers nothing (no danger, no warning), and its latched/held state (drowsy
latch, impact hold, the 3 s / 5 s timers) is dropped, so it cannot fire later
from old data.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

OK, WARNING, DANGER = "ok", "warning", "danger"
LEVEL_NUM = {OK: 0, WARNING: 1, DANGER: 2}

SOURCES = ("motion", "air", "cabin", "driver")
TOPIC_SOURCE = {
    "car/node/motion": "motion",
    "car/node/air": "air",
    "car/gateway/cabin": "cabin",
    "car/vision/driver": "driver",
}

# Tie-break order inside one level (contract: "if two triggers tie, drowsy wins").
REASON_PRIORITY = ("drowsy", "impact", "smoke", "heat", "too_close", "no_face")
REASON_LEVEL = {
    "drowsy": DANGER,
    "impact": DANGER,
    "smoke": WARNING,
    "heat": WARNING,
    "too_close": WARNING,
    "no_face": WARNING,
}


@dataclass(frozen=True)
class Thresholds:
    smoke_ppm: float  # warning when smoke > this (MQ-2 estimate)
    temp_c: float  # warning when temp > this
    distance_cm: float  # warning when distance < this ...
    distance_hold_s: float  # ... for this long
    no_face_hold_s: float  # warning when no_face for this long
    impact_hold_s: float  # danger held this long after an impact
    drowsy_clear_s: float  # drowsy danger clears this long after "open"
    stale_s: float  # a source silent longer than this is stale


@dataclass(frozen=True)
class Alert:
    level: str
    reason: str

    @property
    def level_num(self) -> int:
        return LEVEL_NUM[self.level]


ALERT_OK = Alert(OK, "none")


def _num(value: Any) -> float | None:
    """Return a finite float, or None for null / missing / bad values."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class RulesEngine:
    def __init__(self, thresholds: Thresholds, clock: Callable[[], float] = time.monotonic):
        self.t = thresholds
        self.clock = clock
        self.last_seen: dict[str, float] = {}
        # Latest values
        self.smoke: float | None = None
        self.temp: float | None = None
        self.state: str | None = None
        # Timers / latches
        self.impact_until: float | None = None
        self.too_close_since: float | None = None
        self.no_face_since: float | None = None
        self.drowsy_latched = False
        self.open_since: float | None = None

    # ------------------------------------------------------------------ input
    def update(self, source: str, payload: Mapping[str, Any], now: float | None = None) -> None:
        """Feed one decoded message. `source` is one of SOURCES (see TOPIC_SOURCE)."""
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        now = self.clock() if now is None else now
        self.last_seen[source] = now
        getattr(self, f"_update_{source}")(payload, now)

    def _update_motion(self, p: Mapping[str, Any], now: float) -> None:
        if p.get("impact") is True:
            self.impact_until = now + self.t.impact_hold_s

    def _update_air(self, p: Mapping[str, Any], now: float) -> None:
        self.smoke = _num(p.get("smoke"))

    def _update_cabin(self, p: Mapping[str, Any], now: float) -> None:
        self.temp = _num(p.get("temp"))
        distance = _num(p.get("distance"))
        if distance is not None and distance < self.t.distance_cm:
            if self.too_close_since is None:
                self.too_close_since = now
        else:
            # A far reading or a failed read (null) restarts the 3 s window.
            self.too_close_since = None

    def _update_driver(self, p: Mapping[str, Any], now: float) -> None:
        state = p.get("state")
        self.state = state if isinstance(state, str) else None

        if state == "no_face":
            if self.no_face_since is None:
                self.no_face_since = now
        else:
            self.no_face_since = None

        if state == "drowsy":
            self.drowsy_latched = True
            self.open_since = None
        elif self.drowsy_latched:
            if state == "open":
                if self.open_since is None:
                    self.open_since = now
            else:  # closed / no_face / unknown: eyes not confirmed open, re-arm
                self.open_since = None

    # ----------------------------------------------------------------- output
    def is_stale(self, source: str, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        seen = self.last_seen.get(source)
        return seen is None or now - seen > self.t.stale_s

    def stale_sources(self, now: float | None = None) -> list[str]:
        now = self.clock() if now is None else now
        return [s for s in SOURCES if self.is_stale(s, now)]

    def active_reasons(self, now: float | None = None) -> list[str]:
        """All triggers that are active right now, in REASON_PRIORITY order."""
        now = self.clock() if now is None else now
        self._drop_stale_state(now)
        t = self.t
        active: set[str] = set()

        if not self.is_stale("driver", now):
            if self.drowsy_latched and self.open_since is not None and now - self.open_since >= t.drowsy_clear_s:
                self.drowsy_latched = False
                self.open_since = None
            if self.drowsy_latched:
                active.add("drowsy")
            if self.no_face_since is not None and now - self.no_face_since >= t.no_face_hold_s:
                active.add("no_face")

        if not self.is_stale("motion", now):
            if self.impact_until is not None and now < self.impact_until:
                active.add("impact")

        if not self.is_stale("air", now):
            if self.smoke is not None and self.smoke > t.smoke_ppm:
                active.add("smoke")

        if not self.is_stale("cabin", now):
            if self.temp is not None and self.temp > t.temp_c:
                active.add("heat")
            if self.too_close_since is not None and now - self.too_close_since >= t.distance_hold_s:
                active.add("too_close")

        return [r for r in REASON_PRIORITY if r in active]

    def evaluate(self, now: float | None = None) -> Alert:
        reasons = self.active_reasons(now)
        for level in (DANGER, WARNING):
            for reason in reasons:  # already in priority order
                if REASON_LEVEL[reason] == level:
                    return Alert(level, reason)
        return ALERT_OK

    def _drop_stale_state(self, now: float) -> None:
        if self.is_stale("driver", now):
            self.drowsy_latched = False
            self.open_since = None
            self.no_face_since = None
        if self.is_stale("motion", now):
            self.impact_until = None
        if self.is_stale("cabin", now):
            self.too_close_since = None
