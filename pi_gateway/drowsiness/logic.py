"""Pure driver-state logic for car/vision/driver (no camera, OpenCV or MediaPipe).

Kept separate so it can be unit-tested on any machine.
Payload format: docs/mqtt_contract.md.
"""
from collections import deque

TOPIC = "car/vision/driver"

OPEN = "open"
CLOSED = "closed"
DROWSY = "drowsy"
NO_FACE = "no_face"
STATES = (OPEN, CLOSED, DROWSY, NO_FACE)


class DriverState:
    """Turns per-frame EAR values into open / closed / drowsy / no_face.

    `closed_frames` counts consecutive frames with EAR below the threshold.
    Once it reaches `frames_needed` the state is `drowsy` until the eyes open
    again or the face is lost.
    """

    def __init__(self, frames_needed=15):
        self.frames_needed = frames_needed
        self.closed_frames = 0
        self.state = None

    def update(self, ear, thresh):
        """Feeds one frame. Returns (state, changed, became_drowsy)."""
        if ear is None:
            self.closed_frames = 0
            new = NO_FACE
        elif ear < thresh:
            self.closed_frames += 1
            new = DROWSY if self.closed_frames >= self.frames_needed else CLOSED
        else:
            self.closed_frames = 0
            new = OPEN
        changed = new != self.state
        became_drowsy = changed and new == DROWSY
        self.state = new
        return new, changed, became_drowsy


class RollingFps:
    """Frames per second over the last `window` frame timestamps."""

    def __init__(self, window=30):
        self.times = deque(maxlen=window)

    def tick(self, t):
        self.times.append(t)
        return self.value()

    def value(self):
        if len(self.times) < 2:
            return 0.0
        span = self.times[-1] - self.times[0]
        return (len(self.times) - 1) / span if span > 0 else 0.0


class Throttle:
    """Says when to publish: every `period` seconds, or at once on a state change."""

    def __init__(self, period=0.5):
        self.period = period
        self.last = None

    def due(self, now, changed=False):
        if changed or self.last is None or now - self.last >= self.period:
            self.last = now
            return True
        return False


def build_payload(ts, ear, thresh, state, closed_frames, fps, snapshot=None):
    """Builds the car/vision/driver JSON dict. `ear` is None when there is no face."""
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    return {
        "ts": float(ts),
        "ear": None if ear is None else round(float(ear), 3),
        "thresh": round(float(thresh), 3),
        "state": state,
        "closed_frames": int(closed_frames),
        "fps": round(float(fps), 1),
        "snapshot": snapshot if state == DROWSY else None,
    }
