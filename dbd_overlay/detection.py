"""Anti-cheat safe game detection.

GameWatcher reads only the OS process list. HudWatcher takes screenshots of the
game window (like OBS / Fog Companion) and looks for the in-match perk HUD.
We never open the game process, read its memory or inject anything.

The game log can't be used: BHVR writes DeadByDaylight(-EGS).log encrypted.
"""

import os
import re
import sys
import threading
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, Signal

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


# On Windows process names are never shortened, and reading other processes' command
# lines is slow there, so only Linux (Wine names cut to 15 chars) needs the cmdline.
_SCAN_ATTRS = ["name"] if sys.platform == "win32" else ["name", "cmdline"]


def scan_game_pids() -> set[int]:
    pids = set()
    own_pid = os.getpid()
    for proc in psutil.process_iter(_SCAN_ATTRS):
        if proc.pid == own_pid:
            continue
        try:
            if _is_game(proc):
                pids.add(proc.pid)
        except (psutil.Error, OSError):
            continue
    return pids


class GameWatcher(QObject):
    """Checks every few seconds whether the game runs, on a worker thread.

    Walking the process list can take hundreds of milliseconds on Windows; on the
    UI thread that froze the whole app every few seconds.
    """

    game_running_changed = Signal(bool)
    _scanned = Signal(object)  # set of pids, delivered to the UI thread

    INTERVAL = 3.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game_running = False
        self.pids: set[int] = set()
        self.sandboxed = in_sandbox()
        self._stop_event: threading.Event | None = None
        self._scanned.connect(self._apply)

    def start(self):
        if self._stop_event is not None:
            return
        # One event per run, so a quick stop/start can't leave two threads scanning
        stop = self._stop_event = threading.Event()
        threading.Thread(target=self._run, args=(stop,), name="game-watcher", daemon=True).start()

    def stop(self):
        if self._stop_event is not None:
            self._stop_event.set()
            self._stop_event = None
        self.pids = set()
        self._set_running(False)

    def _run(self, stop: threading.Event):
        while not stop.is_set():
            pids = scan_game_pids()
            if not stop.is_set():
                self._scanned.emit(pids)
            stop.wait(self.INTERVAL)

    def _apply(self, pids: set[int]):
        if self._stop_event is None:  # stopped while that scan was running
            return
        self.pids = pids
        self._set_running(bool(pids))

    def _set_running(self, running: bool):
        if running != self.game_running:
            self.game_running = running
            self.game_running_changed.emit(running)


class HudWatcher(QObject):
    """Samples the game's HUD corner twice a second on a worker thread.

    While the flashlight is held it also watches the middle of the screen ten
    times a second for the white burst of a successful blind.
    """

    sample = Signal(float, str)  # best rhombus score, capture status
    blind = Signal()

    INTERVAL = 0.5
    FLASH_INTERVAL = 0.1
    FLASH_LINGER = 0.6     # keep watching a moment after the button is released
    FLASH_MIN_HOLD = 0.25  # a blind needs the beam on the killer for a while
    BLIND_COOLDOWN = 4.0

    def __init__(self, game: GameWatcher, debug_dir: Path, parent=None):
        super().__init__(parent)
        self._game = game
        self._debug_dir = debug_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._save_debug = False
        self.game_center: tuple[int, int] | None = None  # native pixels, for picking the monitor
        self.blind_threshold = 0.35
        self._flash_since: float | None = None  # flashlight held since (monotonic)
        self._flash_until = 0.0                 # still watching until (after release)

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

    def set_flashlight(self, held: bool):
        now = time.monotonic()
        if held:
            self._flash_since = now
        else:
            self._flash_until = now + self.FLASH_LINGER
            self._flash_since = None

    def _flash_watch(self, now: float) -> float | None:
        """Seconds the flashlight has been held, or None when not watching."""
        since = self._flash_since
        if since is not None:
            return now - since
        if now < self._flash_until:
            return self.FLASH_MIN_HOLD  # just released: still counts
        return None

    def _run(self):
        # Heavy imports stay off the startup path and out of the UI thread
        try:
            from . import capture, hud
        except Exception as e:
            self.sample.emit(0.0, f"screen detection unavailable ({e})")
            return
        grabber = None
        last_hud = 0.0
        last_blind = 0.0
        baseline: float | None = None
        while not self._stop.wait(self.FLASH_INTERVAL if self._flash_watch(time.monotonic()) is not None
                                  else self.INTERVAL):
            pids = set(self._game.pids)
            if not pids:
                continue
            now = time.monotonic()
            try:
                if grabber is None:
                    grabber = capture.make_grabber()
                width, height = grabber.window_size(pids)
                self.game_center = grabber.center

                held = self._flash_watch(now)
                if held is None:
                    baseline = None
                else:
                    white = hud.white_fraction(grabber.grab(*hud.center_region(width, height)))
                    if baseline is None:
                        baseline = white  # bright scenery before the beam isn't a blind
                    if (held >= self.FLASH_MIN_HOLD and white > self.blind_threshold
                            and white - baseline > 0.2 and now - last_blind > self.BLIND_COOLDOWN):
                        last_blind = now
                        self.blind.emit()
                if now - last_hud < self.INTERVAL:
                    continue
                last_hud = now
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
