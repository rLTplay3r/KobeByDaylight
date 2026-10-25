"""Anti-cheat safe game detection.

GameWatcher reads only the OS process list. HudWatcher takes screenshots of the
game window (like OBS / Fog Companion) and looks for the in-match perk HUD.
We never open the game process, read its memory or inject anything.

The game log can't be used: BHVR writes DeadByDaylight(-EGS).log encrypted.
"""

import os
import re
import threading
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

# Steam: DeadByDaylight-Win64-Shipping.exe, Epic: DeadByDaylight-EGS-Shipping.exe,
# Windows Store: DeadByDaylight-WinGDK-Shipping.exe
GAME_EXE = re.compile(r"deadbydaylight-\w+-shipping(\.exe)?$", re.IGNORECASE)


def in_sandbox() -> bool:
    """Inside Flatpak (e.g. the VS Code Flatpak terminal) the host's processes are invisible."""
    return Path("/.flatpak-info").exists()


def _is_game(proc: psutil.Process) -> bool:
    name = proc.info.get("name") or ""
    # Linux cuts process names to 15 chars ("DeadByDaylight-"); Wine keeps the exe
    # name there, so check the full Windows path from the command line as well.
    if name.lower().startswith("deadbydaylight-") or GAME_EXE.search(name):
        return True
    for arg in (proc.info.get("cmdline") or [])[:2]:
        base = re.split(r"[\\/]", arg)[-1]
        if GAME_EXE.search(base):
            return True
    return False


class GameWatcher(QObject):
    game_running_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game_running = False
        self.pids: set[int] = set()
        self.sandboxed = in_sandbox()
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._check)

    def start(self):
        self._check()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._set_running(False)

    def _check(self):
        pids = set()
        own_pid = os.getpid()
        for proc in psutil.process_iter(["name", "cmdline"]):
            if proc.pid == own_pid:
                continue
            try:
                if _is_game(proc):
                    pids.add(proc.pid)
            except (psutil.Error, OSError):
                continue
        self.pids = pids
        self._set_running(bool(pids))

    def _set_running(self, running: bool):
        if running != self.game_running:
            self.game_running = running
            self.game_running_changed.emit(running)


class HudWatcher(QObject):
    """Samples the game's HUD corner twice a second on a worker thread."""

    sample = Signal(float, str)  # best rhombus score, capture status

    INTERVAL = 0.5

    def __init__(self, game: GameWatcher, debug_dir: Path, parent=None):
        super().__init__(parent)
        self._game = game
        self._debug_dir = debug_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._save_debug = False
        self.game_center: tuple[int, int] | None = None  # native pixels, for picking the monitor

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hud-watcher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def save_debug_capture(self):
        self._save_debug = True

    def _run(self):
        # Heavy imports stay off the startup path and out of the UI thread
        try:
            from . import capture, hud
        except Exception as e:
            self.sample.emit(0.0, f"screen detection unavailable ({e})")
            return
        grabber = None
        while not self._stop.wait(self.INTERVAL):
            pids = set(self._game.pids)
            if not pids:
                continue
            try:
                if grabber is None:
                    grabber = capture.make_grabber()
                width, height = grabber.window_size(pids)
                self.game_center = grabber.center
                best, best_img = 0.0, None
                for x, y, w, h in hud.hud_regions(width, height):
                    img = grabber.grab(x, y, w, h)
                    score = hud.perk_rhombus_score(img)
                    if best_img is None or score > best:
                        best, best_img = score, img
                status = "ok"
                if best_img is not None and best_img.max() < 8:
                    status = "capture is black"
                if self._save_debug and best_img is not None:
                    self._save_debug = False
                    status = self._write_debug(best_img, best)
                self.sample.emit(best, status)
            except Exception as e:  # CaptureError, X errors, game window gone...
                grabber = None if not isinstance(e, capture.CaptureError) else grabber
                self.sample.emit(0.0, str(e))
                time.sleep(2)

    def _write_debug(self, img, score) -> str:
        import cv2

        self._debug_dir.mkdir(parents=True, exist_ok=True)
        path = self._debug_dir / f"hud-{time.strftime('%Y%m%d-%H%M%S')}-{score:.2f}.png"
        cv2.imwrite(str(path), img)
        return f"saved {path}"
