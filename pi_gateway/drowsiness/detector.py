"""Face Mesh wrapper and eye aspect ratio (EAR)."""
import cv2
import mediapipe as mp
import numpy as np

# MediaPipe Face Mesh indices: [outer corner, top1, top2, inner corner, bottom2, bottom1]
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]


def ear(pts):
    """pts: 6x2 array ordered p1..p6. EAR = (|p2-p6| + |p3-p5|) / (2|p1-p4|)."""
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    h = np.linalg.norm(pts[0] - pts[3])
    return (v1 + v2) / (2.0 * h) if h > 0 else 0.0


class Detector:
    def __init__(self):
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def process(self, frame_bgr):
        """Returns (mean_ear or None, list of (x, y) eye pixel points)."""
        h, w = frame_bgr.shape[:2]
        res = self.mesh.process(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            return None, []
        lm = res.multi_face_landmarks[0].landmark
        left = np.array([(lm[i].x * w, lm[i].y * h) for i in LEFT_EYE])
        right = np.array([(lm[i].x * w, lm[i].y * h) for i in RIGHT_EYE])
        value = (ear(left) + ear(right)) / 2.0
        return value, [tuple(p.astype(int)) for p in np.vstack([left, right])]
