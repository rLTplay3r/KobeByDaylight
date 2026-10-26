"""Dancing Kobe: plays a clip from dancing/ with its black background made transparent.

Frames are decoded and keyed on a worker thread, so any video dropped into dancing/
works without preparing it first.
"""

import random
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import paths

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
BLACK = 26  # brightness below which a pixel touching the border counts as background


def dance_files() -> list[Path]:
    if not paths.DANCE_DIR.is_dir():
        return []
    return sorted(p for p in paths.DANCE_DIR.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def key_black(frame_bgr):
    """BGR frame -> RGBA with the black background transparent.

    Only dark pixels connected to the frame border are removed, so dark hair,
    beard and shadows on the dancer stay solid.
    """
    import cv2
    import numpy as np

    h, w = frame_bgr.shape[:2]
    dark = (frame_bgr.max(axis=2) < BLACK).astype(np.uint8)
    # Flood the dark area from the border: whatever it reaches is background
    flood = np.zeros((h + 2, w + 2), np.uint8)
    bg = dark.copy()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1)):
        if bg[seed[1], seed[0]] == 1:
            cv2.floodFill(bg, flood, seed, 2)
    alpha = np.where(bg == 2, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)  # soft edge instead of a jagged cut
    rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA)
    rgba[..., 3] = alpha
    return rgba


def content_box(cap, samples: int = 12) -> tuple[int, int, int, int] | None:
    """Where the dancer moves in the clip (x, y, w, h), so empty black margins get cropped.

    Looks at the biggest keyed shape in a dozen frames; small bits like a watermark
    don't stretch the box.
    """
    import cv2
    import numpy as np

    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    box = None
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(count * (i + 0.5) / samples))
        ok, img = cap.read()
        if not ok:
            continue
        h, w = img.shape[:2]
        scale = 320 / h
        small = cv2.resize(img, (max(1, int(w * scale)), 320), interpolation=cv2.INTER_AREA)
        alpha = (key_black(small)[..., 3] > 128).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(alpha)
        if n < 2:
            continue
        x, y, bw, bh, _ = stats[1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))]
        x, y, bw, bh = (int(v / scale) for v in (x, y, bw, bh))
        box = (x, y, x + bw, y + bh) if box is None else (
            min(box[0], x), min(box[1], y), max(box[2], x + bw), max(box[3], y + bh))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if box is None:
        return None
    return box[0], box[1], box[2] - box[0], box[3] - box[1]


def to_qimage(rgba) -> QImage:
    h, w = rgba.shape[:2]
    return QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class DancePlayer(QObject):
    frame = Signal(QImage)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop: threading.Event | None = None
        self._last_file: Path | None = None

    @property
    def available(self) -> bool:
        return bool(dance_files())

    def playing(self) -> bool:
        return self._stop is not None and not self._stop.is_set()

    def start(self, height: int, duration: float):
        files = dance_files()
        if not files:
            return False
        self.stop()
        choices = [f for f in files if f != self._last_file] or files
        path = random.choice(choices)
        self._last_file = path
        stop = self._stop = threading.Event()
        threading.Thread(target=self._run, args=(path, height, duration, stop), daemon=True,
                         name="dance").start()
        return True

    def stop(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    def still(self, height: int) -> QImage | None:
        """One keyed frame, for the scale preview."""
        import cv2

        files = dance_files()
        if not files:
            return None
        cap = cv2.VideoCapture(str(files[0]))
        box = content_box(cap)
        cap.set(cv2.CAP_PROP_POS_MSEC, 2000)
        ok, img = cap.read()
        cap.release()
        return to_qimage(self._render(img, height, box)) if ok else None

    @staticmethod
    def _render(img, height: int, box=None):
        """Scale so the dancer's area is `height` tall, key the black out, then crop.

        Keying happens before cropping: after the crop the hair touches the top
        edge and would be taken for background.
        """
        import cv2

        bx, by, bw, bh = box if box is not None else (0, 0, img.shape[1], img.shape[0])
        s = height / bh
        h, w = img.shape[:2]
        rgba = key_black(cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA))
        x0, y0 = int(bx * s), int(by * s)
        return rgba[y0:y0 + height, x0:x0 + max(1, int(bw * s))].copy()

    def _run(self, path: Path, height: int, duration: float, stop: threading.Event):
        import cv2

        cap = cv2.VideoCapture(str(path))
        box = content_box(cap)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0
        # A random stretch of the clip, so a long dance video gives different moves
        if total > duration + 1:
            cap.set(cv2.CAP_PROP_POS_MSEC, random.uniform(0, total - duration) * 1000)
        start = time.monotonic()
        shown = 0
        while not stop.is_set():
            ok, img = cap.read()
            elapsed = time.monotonic() - start
            if not ok or elapsed > duration:
                break
            self.frame.emit(to_qimage(self._render(img, height, box)))
            shown += 1
            # Keep the clip's own speed
            delay = shown / fps - (time.monotonic() - start)
            if delay > 0:
                stop.wait(delay)
        cap.release()
        if not stop.is_set():
            stop.set()
            self.finished.emit()
