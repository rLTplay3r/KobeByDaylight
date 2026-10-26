"""Dancing Kobe: plays a clip from dancing/ with its green-screen (or black) background made transparent.

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
# Background = dark pixels joined to the frame edge. A beard can be as dark as the background,
# so the dancer's silhouette (bright parts closed over small dark gaps) is protected.
BLACK = 15  # background is ~9; hair is mostly brighter, the beard is protected below


def dance_files() -> list[Path]:
    if not paths.DANCE_DIR.is_dir():
        return []
    return sorted(p for p in paths.DANCE_DIR.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def background_kind(frame_bgr) -> tuple[str, "object"]:
    """("green", key colour in CrCb) for a green screen, ("black", None) otherwise."""
    import cv2
    import numpy as np

    edge = np.concatenate([frame_bgr[:8].reshape(-1, 3), frame_bgr[:, :8].reshape(-1, 3),
                           frame_bgr[:, -8:].reshape(-1, 3)])
    b, g, r = np.median(edge, axis=0)
    if g > 90 and g > 1.6 * max(r, b):
        ycc = cv2.cvtColor(edge.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2YCrCb).reshape(-1, 3)
        return "green", np.median(ycc[:, 1:], axis=0).astype(np.float32)
    return "black", None


def key_green(frame_bgr, key_crcb):
    """BGR frame -> RGBA, green screen removed by colour.

    Pixels are judged by their colour (CrCb), not brightness, so a near-black beard
    or dark hair is never mistaken for background. Edges get partial alpha and the
    green light spilling onto them is removed.
    """
    import cv2
    import numpy as np

    ycc = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    dist = np.sqrt(((ycc[..., 1:] - key_crcb) ** 2).sum(axis=2))
    # Fully background within ~12 of the key colour, fully solid beyond ~40
    alpha = np.clip((dist - 16) / 24, 0, 1)
    # Specks of noise in the background
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # Pull the edge in by a pixel: the outermost ring is mostly green light
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    rgb = frame_bgr.astype(np.float32)
    # Spill suppression: green may not exceed the brighter of red and blue
    rgb[..., 1] = np.minimum(rgb[..., 1], np.maximum(rgb[..., 0], rgb[..., 2]) * 1.02)
    rgba = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGBA)
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    return rgba


def key_frame(frame_bgr, kind):
    return key_green(frame_bgr, kind[1]) if kind[0] == "green" else key_black(frame_bgr)


def key_black(frame_bgr):
    """BGR frame -> RGBA with the black background transparent.

    Dark pixels connected to the frame border are background, except inside the
    dancer's silhouette: the bright body parts closed over small dark gaps, which
    keeps a near-black beard or shadowed neck solid instead of see-through.
    """
    import cv2
    import numpy as np

    h, w = frame_bgr.shape[:2]
    m = frame_bgr.max(axis=2)
    dark = (m < BLACK).astype(np.uint8)
    n, labels = cv2.connectedComponents(dark, connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border = border[border != 0]
    bg = np.isin(labels, border)
    # Silhouette: bright parts (skin, jersey) closed with a kernel about a beard wide
    k = max(5, int(h * 0.03)) | 1
    silhouette = cv2.morphologyEx((1 - dark), cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))).astype(bool)
    bg &= ~silhouette
    # Compression specks in the background (a few pixels a bit brighter than the black)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((~bg).astype(np.uint8), connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < h * w * 0.0005)[0]
    small = small[small != 0]
    if small.size:
        bg |= np.isin(labels, small)
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)  # soft edge instead of a jagged cut
    rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA)
    rgba[..., 3] = alpha
    return rgba


def clip_info(cap, samples: int = 40):
    """(background kind, dancer box) for a clip: what to key out and where to crop."""
    import cv2

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ok, img = cap.read()
    kind = background_kind(img) if ok else ("black", None)
    return kind, content_box(cap, kind, samples)


def content_box(cap, kind, samples: int = 40) -> tuple[int, int, int, int] | None:
    """Where the dancer moves in the clip (x, y, w, h), so empty margins get cropped.

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
        alpha = (key_frame(small, kind)[..., 3] > 128).astype(np.uint8)
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
    # Some room for moves between the sampled frames (a jump, a raised hand)
    fw, fh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pad = int(fh * 0.04)
    x0, y0 = max(0, box[0] - pad), max(0, box[1] - pad)
    x1, y1 = min(fw, box[2] + pad), min(fh, box[3] + pad)
    return x0, y0, x1 - x0, y1 - y0


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
        kind, box = clip_info(cap)
        cap.set(cv2.CAP_PROP_POS_MSEC, 2000)
        ok, img = cap.read()
        cap.release()
        return to_qimage(self._render(img, height, kind, box)) if ok else None

    @staticmethod
    def _render(img, height: int, kind, box=None):
        """Scale so the dancer's area is `height` tall, key the background out, then crop.

        Keying happens before cropping: the black key needs the frame edge to be
        background, and after the crop the hair would touch it.
        """
        import cv2

        bx, by, bw, bh = box if box is not None else (0, 0, img.shape[1], img.shape[0])
        s = height / bh
        h, w = img.shape[:2]
        rgba = key_frame(cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA), kind)
        x0, y0 = int(bx * s), int(by * s)
        return rgba[y0:y0 + height, x0:x0 + max(1, int(bw * s))].copy()

    def _run(self, path: Path, height: int, duration: float, stop: threading.Event):
        import cv2

        cap = cv2.VideoCapture(str(path))
        kind, box = clip_info(cap)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0
        # A random stretch of the clip, so a long dance video gives different moves
        if total > duration + 1:
            cap.set(cv2.CAP_PROP_POS_MSEC, random.uniform(0, total - duration) * 1000)
        start = time.monotonic()
        shown = 0
        while not stop.is_set():
            ok, img = cap.read()
            if not ok:
                # Asked for longer than the clip: start it over
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = cap.read()
            if not ok or time.monotonic() - start > duration:
                break
            self.frame.emit(to_qimage(self._render(img, height, kind, box)))
            shown += 1
            # Keep the clip's own speed
            delay = shown / fps - (time.monotonic() - start)
            if delay > 0:
                stop.wait(delay)
        cap.release()
        if not stop.is_set():
            stop.set()
            self.finished.emit()
