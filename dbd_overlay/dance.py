"""Dancing Kobe: plays a clip from dancing/ with its green-screen (or black) background made transparent.

Keying a video live is far too heavy (it made the game stutter on laptops), so each
clip is keyed once into a sequence of transparent WebP frames. Builds ship the
sequences ready (builder step "Prepare dance frames"); a video added later is
prepared in the background on first start and cached. Playback then only loads
the frames.
"""

import hashlib
import json
import os
import random
import shutil
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QImage

from . import APP_ID, paths

FRAME_HEIGHT = 720   # prepared frames are stored this tall
WEBP_QUALITY = 85
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


# -- prepared frame sequences ----------------------------------------------------------

def file_key(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"{path.stem}-{h.hexdigest()[:10]}"


def cache_dirs() -> list[Path]:
    """Where prepared sequences are looked for: bundled with the build, then the user cache."""
    user = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)) / APP_ID / "dance"
    dirs = [paths.DANCE_FRAMES_DIR]
    if not getattr(sys, "frozen", False):
        dirs.append(paths.asset_roots()[0] / "build" / "dance-frames")  # made by the builder
    return dirs + [user]


def find_sequence(key: str) -> Path | None:
    for root in cache_dirs():
        folder = root / key
        if (folder / "meta.json").is_file():
            return folder
    return None


def prepare(video: Path, out_root: Path, key: str | None = None, throttle: float = 0.0) -> Path:
    """Key a video into out_root/<key>/0000.webp... plus meta.json; returns the folder.

    throttle: seconds to rest after each frame, to keep a background preparation light.
    """
    import cv2

    key = key or file_key(video)
    final = out_root / key
    if (final / "meta.json").is_file():
        return final
    tmp = out_root / (key + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    kind, box = clip_info(cap)
    bh = box[3] if box else int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    height = min(FRAME_HEIGHT, bh)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    count = 0
    size = None
    while True:
        ok, img = cap.read()
        if not ok:
            break
        rgba = DancePlayer._render(img, height, kind, box)
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        cv2.imwrite(str(tmp / f"{count:04d}.webp"), bgra, [cv2.IMWRITE_WEBP_QUALITY, WEBP_QUALITY])
        size = bgra.shape[1], bgra.shape[0]
        count += 1
        if throttle:
            time.sleep(throttle)
    cap.release()
    (tmp / "meta.json").write_text(json.dumps({"fps": fps, "count": count, "width": size[0] if size else 0,
                                               "height": size[1] if size else 0, "source": video.name}))
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    return final


class DancePlayer(QObject):
    frame = Signal(QImage)
    finished = Signal()
    ready_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop: threading.Event | None = None
        self._last: Path | None = None
        self._sequences: list[Path] = []
        self._preparing = False

    def prepare_all(self):
        """Find the prepared sequences; key any video that has none in the background."""
        if self._preparing:
            return
        self._preparing = True
        threading.Thread(target=self._prepare_worker, daemon=True, name="dance-prepare").start()

    def _prepare_worker(self):
        try:
            found, missing = [], []
            for video in dance_files():
                key = file_key(video)
                seq = find_sequence(key)
                (found.append(seq) if seq else missing.append((video, key)))
            self._sequences = found
            self.ready_changed.emit()
            for video, key in missing:
                # Slow and steady: this runs while the user may be playing
                seq = prepare(video, cache_dirs()[-1], key, throttle=0.02)
                self._sequences = self._sequences + [seq]
                self.ready_changed.emit()
        finally:
            self._preparing = False

    @property
    def available(self) -> bool:
        return bool(self._sequences)

    def playing(self) -> bool:
        return self._stop is not None and not self._stop.is_set()

    def start(self, height: int, duration: float):
        if not self._sequences:
            return False
        self.stop()
        choices = [q for q in self._sequences if q != self._last] or self._sequences
        seq = random.choice(choices)
        self._last = seq
        stop = self._stop = threading.Event()
        threading.Thread(target=self._run, args=(seq, height, duration, stop), daemon=True,
                         name="dance").start()
        return True

    def stop(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    def still(self, height: int) -> QImage | None:
        """One frame, for the scale preview."""
        if not self._sequences:
            return None
        meta = json.loads((self._sequences[0] / "meta.json").read_text())
        return self._load(self._sequences[0], min(50, meta["count"] - 1), height)

    @staticmethod
    def _load(seq: Path, index: int, height: int) -> QImage | None:
        img = QImage(str(seq / f"{index:04d}.webp"))
        if img.isNull():
            return None
        if img.height() != height:
            img = img.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        # Premultiplied here, on the worker thread, so painting is a plain copy
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

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

    def _run(self, seq: Path, height: int, duration: float, stop: threading.Event):
        meta = json.loads((seq / "meta.json").read_text())
        fps, count = meta["fps"] or 25, meta["count"]
        if not count:
            return
        # A random point in the clip, so the moves differ each time; loops if needed
        index = random.randrange(count) if count / fps > duration + 1 else 0
        start = time.monotonic()
        shown = 0
        while not stop.is_set() and time.monotonic() - start <= duration:
            img = self._load(seq, index, height)
            if img is not None:
                self.frame.emit(img)
            shown += 1
            index = (index + 1) % count
            delay = shown / fps - (time.monotonic() - start)
            if delay > 0:
                stop.wait(delay)
        if not stop.is_set():
            stop.set()
            self.finished.emit()


def main():
    """python -m dbd_overlay.dance --prepare OUT_DIR : key every video in dancing/ into OUT_DIR."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", required=True, help="output folder for the frame sequences")
    out = Path(parser.parse_args().prepare)
    out.mkdir(parents=True, exist_ok=True)
    keep = set()
    for video in dance_files():
        key = file_key(video)
        keep.add(key)
        t0 = time.monotonic()
        folder = prepare(video, out, key)
        print(f"{video.name} -> {folder.name} ({time.monotonic() - t0:.0f} s)")
    for old in out.iterdir():  # sequences of videos that are gone
        if old.is_dir() and old.name not in keep:
            shutil.rmtree(old, ignore_errors=True)


if __name__ == "__main__":
    main()
