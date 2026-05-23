"""
Hand Gesture 3D Object Controller
===================================
Controls a 3D particle torus using your webcam + hand position.
Move your hand left/right to rotate horizontally,
up/down to rotate vertically.
Pinch thumb & index together to zoom out, spread them apart to zoom in.
Keyboard: + / - to zoom, Q to quit.

Install dependencies:
    pip install -r requirements.txt

Run:
    python hand_gesture_3d.py
"""

import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    HandLandmarksConnections,
)
from mediapipe.tasks.python.vision.core.image import Image, ImageFormat
from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
    VisionTaskRunningMode,
)

HAND_CONNECTIONS = HandLandmarksConnections.HAND_CONNECTIONS

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent / "hand_landmarker.task"


def ensure_model() -> str:
    if MODEL_PATH.exists():
        return str(MODEL_PATH)
    print("Downloading hand_landmarker.task (one-time, ~3 MB)...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return str(MODEL_PATH)


# ── 3D particle shapes ───────────────────────────────────────────────────────
def make_torus(n=1200, R=130, r=45):
    theta = np.random.uniform(0, 2 * np.pi, n)
    phi   = np.random.uniform(0, 2 * np.pi, n)
    x = (R + r * np.cos(phi)) * np.cos(theta)
    y = (R + r * np.cos(phi)) * np.sin(theta)
    z = r * np.sin(phi)
    return np.stack([x, y, z], axis=1).astype(np.float32)


def rot_x(pts, a):
    c, s = np.cos(a), np.sin(a)
    R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)
    return pts @ R.T


def rot_y(pts, a):
    c, s = np.cos(a), np.sin(a)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)
    return pts @ R.T


# ── Draw hand skeleton on a frame ────────────────────────────────────────────
def draw_skeleton(frame, landmarks, w, h, color=(0, 165, 255)):
    for conn in HAND_CONNECTIONS:
        x1 = int(landmarks[conn.start].x * w)
        y1 = int(landmarks[conn.start].y * h)
        x2 = int(landmarks[conn.end].x * w)
        y2 = int(landmarks[conn.end].y * h)
        cv2.line(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    for lm in landmarks:
        cx = int(lm.x * w)
        cy = int(lm.y * h)
        cv2.circle(frame, (cx, cy), 3, (255, 255, 255), -1, cv2.LINE_AA)


def pinch_distance(landmarks) -> float:
    """Distance between thumb tip (4) and index tip (8), normalized 0–1."""
    thumb = landmarks[4]
    index = landmarks[8]
    return float(np.hypot(thumb.x - index.x, thumb.y - index.y))


def pinch_to_zoom(pinch: float) -> float:
    """Map pinch spread to zoom multiplier."""
    pinch = np.clip(pinch, PINCH_MIN, PINCH_MAX)
    t = (pinch - PINCH_MIN) / (PINCH_MAX - PINCH_MIN)
    return ZOOM_MIN + t * (ZOOM_MAX - ZOOM_MIN)


PINCH_MIN, PINCH_MAX = 0.035, 0.20
ZOOM_MIN, ZOOM_MAX = 0.45, 2.2
ZOOM_DEFAULT = 1.0


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    particles = make_torus()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)

    window_name = "Hand Gesture 3D Control"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    is_fullscreen = True

    W, H = 1280, 720
    PW, PH = 240, 180
    DEPTH = 450

    rx, ry = 0.0, 0.0
    target_rx = 0.0
    target_ry = 0.0
    auto_ry = 0.0
    zoom = ZOOM_DEFAULT
    target_zoom = ZOOM_DEFAULT

    print("=== Hand Gesture 3D Control ===")
    print("Move your hand to rotate the object.")
    print("Pinch thumb+index: close = zoom out, spread = zoom in.")
    print("Keys: + zoom in, - zoom out, Q quit.")

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=ensure_model()),
        running_mode=VisionTaskRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    with HandLandmarker.create_from_options(options) as landmarker:
        frame_ts_ms = 0
        while True:
            # Check if window was closed by the user
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

            # Get actual window size to adjust canvas size and rendering dynamically
            rect = cv2.getWindowImageRect(window_name)
            if rect is not None and rect[2] > 0 and rect[3] > 0:
                W, H = rect[2], rect[3]
            else:
                W, H = 1280, 720

            FOV = H * (600.0 / 720.0)

            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_ts_ms = int(time.time() * 1000)
            mp_image = Image(image_format=ImageFormat.SRGB, data=rgb)
            results = landmarker.detect_for_video(mp_image, frame_ts_ms)

            hand_found = bool(results.hand_landmarks)
            hand_landmarks = results.hand_landmarks[0] if hand_found else None

            if hand_found:
                wrist = hand_landmarks[0]
                target_ry = (wrist.x - 0.5) * 5.0
                target_rx = (wrist.y - 0.5) * 5.0
                target_zoom = pinch_to_zoom(pinch_distance(hand_landmarks))

            if hand_found:
                rx += (target_rx - rx) * 0.12
                ry += (target_ry - ry) * 0.12
                zoom += (target_zoom - zoom) * 0.15
            else:
                auto_ry += 0.012
                ry += (auto_ry - ry) * 0.05
                rx += (0.3 - rx) * 0.03
                zoom += (ZOOM_DEFAULT - zoom) * 0.03

            canvas = np.full((H, W, 3), (15, 15, 20), dtype=np.uint8)

            pts = particles * zoom
            pts = rot_x(pts, rx)
            pts = rot_y(pts, ry)

            order = np.argsort(pts[:, 2])
            cx2, cy2 = W // 2, H // 2

            for idx in order:
                p = pts[idx]
                z = p[2] + DEPTH
                if z <= 0:
                    continue
                scale = FOV / z
                px = int(cx2 + p[0] * scale)
                py = int(cy2 + p[1] * scale)
                if not (0 <= px < W and 0 <= py < H):
                    continue
                bright = int(np.clip(180 + p[2] * 0.4, 60, 255))
                radius = max(1, int(2.2 * scale))
                cv2.circle(
                    canvas, (px, py), radius,
                    (bright, bright, bright), -1, cv2.LINE_AA,
                )

            preview = cv2.resize(frame, (PW, PH))
            if hand_landmarks is not None:
                draw_skeleton(preview, hand_landmarks, PW, PH, color=(0, 165, 255))
                t = hand_landmarks[4]
                i = hand_landmarks[8]
                tx, ty = int(t.x * PW), int(t.y * PH)
                ix, iy = int(i.x * PW), int(i.y * PH)
                cv2.line(preview, (tx, ty), (ix, iy), (0, 220, 255), 2, cv2.LINE_AA)
                cv2.circle(preview, (tx, ty), 5, (0, 220, 255), -1, cv2.LINE_AA)
                cv2.circle(preview, (ix, iy), 5, (0, 220, 255), -1, cv2.LINE_AA)

            bx = max(0, W - PW - 20)
            by = min(20, max(0, H - PH))
            if H >= PH and W >= PW:
                canvas[by : by + PH, bx : bx + PW] = preview
                cv2.rectangle(
                    canvas, (bx - 2, by - 2), (bx + PW + 2, by + PH + 2),
                    (0, 200, 150), 2, cv2.LINE_AA,
                )

            status = (
                "Hand detected  —  move to rotate, pinch thumb+index to zoom"
                if hand_found
                else "Show your hand to control the object"
            )
            cv2.putText(
                canvas, status, (20, H - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (130, 130, 130), 1, cv2.LINE_AA,
            )
            cv2.putText(
                canvas, f"Zoom {int(zoom * 100)}%", (20, H - 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 180, 140), 1, cv2.LINE_AA,
            )
            cv2.putText(
                canvas, "Q quit   F toggle fullscreen   + zoom in   - zoom out", (20, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1, cv2.LINE_AA,
            )

            cv2.imshow(window_name, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("+"), ord("=")):
                zoom = min(ZOOM_MAX, zoom * 1.08)
            elif key in (ord("-"), ord("_")):
                zoom = max(ZOOM_MIN, zoom * 0.92)
            elif key in (ord("f"), ord("F")):
                is_fullscreen = not is_fullscreen
                val = cv2.WINDOW_FULLSCREEN if is_fullscreen else cv2.WINDOW_NORMAL
                cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, val)
            elif key == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
