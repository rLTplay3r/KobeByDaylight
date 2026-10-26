"""Match state machine: stopped -> watching -> in match -> watching."""

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import paths
from .audio import Audio
from .dance import DancePlayer
from .detection import GameWatcher, HudWatcher
from .keys import KeyListener
from .overlay import OverlayWindow

DEFAULT_TEXTS = ["Man, what can I say?", "Mamba out."]
JITTER = 0.4  # random timing spread around the configured average


def jittered(every: float) -> float:
    return random.uniform(every * (1 - JITTER), every * (1 + JITTER))
HOTKEY_NAME = "F8"


def load_texts() -> list[str]:
    try:
        lines = paths.KOBE_TEXTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return DEFAULT_TEXTS
    texts = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
    return texts or DEFAULT_TEXTS


class Controller(QObject):
    state_changed = Signal()
    hud_updated = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.running = False
        self.match_start: float | None = None

        self.audio = Audio(config["music_volume"], config["sfx_volume"], self)
        self.audio.beat.connect(self._on_beat)
        self.overlay = OverlayWindow()
        self.overlay.timer_visible = config["timer_enabled"]
        for element in self.overlay.scales:
            self.overlay.set_scale(element, float(config[f"scale_{element}"]))
        self.previewing = False
        self.keys = KeyListener(self)
        self.keys.pressed.connect(self._on_key)
        self.keys.released.connect(self._on_key_released)
        self.watcher = GameWatcher(self)
        self.watcher.game_running_changed.connect(self._on_game_running)
        self.hud = HudWatcher(self.watcher, config.path.parent / "debug", self)
        self.hud.sample.connect(self._on_hud_sample)
        self.hud.blind.connect(self._on_blind)
        self.hud.blind_threshold = float(config["blind_threshold"])
        self.hud_score = 0.0
        self.hud_status = "waiting for the game"
        self._hud_hits = 0
        self._hud_misses = 0
        self._hud_last_seen = 0.0
        self._manual_match = False
        self._auto_blocked = False  # after F8 ends a match, wait for the HUD to go away

        self._texts = load_texts()
        self._last_text = ""
        self._last_man = 0.0
        self._kobe_timer = QTimer(self)
        self._kobe_timer.setSingleShot(True)
        self._kobe_timer.timeout.connect(self._scheduled_kobe)
        self._last_kobe = 0.0
        self._sound_timer = QTimer(self)
        self._sound_timer.setSingleShot(True)
        self._sound_timer.timeout.connect(self._scheduled_sound)

        self.dance = DancePlayer(self)
        self.dance.frame.connect(self.overlay.set_dance_frame)
        self.dance.finished.connect(self.overlay.dance_finished)
        self._dance_timer = QTimer(self)
        self._dance_timer.setSingleShot(True)
        self._dance_timer.timeout.connect(self._scheduled_dance)

        # Keeps the timer shaking at a fixed tempo when the music gives no beat
        self._last_beat = 0.0
        self._beat_fallback = QTimer(self)
        self._beat_fallback.setInterval(int(float(config["beat_fallback_interval"]) * 1000))
        self._beat_fallback.timeout.connect(self._fallback_beat)

    # -- service ------------------------------------------------------------

    @property
    def in_match(self) -> bool:
        return self.match_start is not None

    def start(self):
        if self.running:
            return
        self.running = True
        self.keys.set_active(True)
        self.watcher.start()
        if self._needs_screen():
            self.hud.start()
        self.state_changed.emit()

    def _needs_screen(self) -> bool:
        # Screenshots are needed for match detection and for spotting flashlight blinds
        return bool(self.config["auto_detect"] or self.config["pov_enabled"])

    def stop(self):
        if not self.running:
            return
        self.end_match()
        self.keys.set_active(False)
        self.watcher.stop()
        self.hud.stop()
        self.running = False
        self.state_changed.emit()

    def status_key(self) -> str:
        """stopped / off (game not running) / game (running, not in a match) / match."""
        if not self.running:
            return "stopped"
        if self.in_match:
            return "match"
        return "game" if self.watcher.game_running else "off"

    def status_text(self) -> str:
        if not self.running:
            return "Press Start to watch for matches"
        if self.in_match:
            return f"{HOTKEY_NAME} ends the match"
        if self.watcher.sandboxed:
            return "Inside a Flatpak sandbox, the game can't be seen. Start the app from a normal terminal."
        if not self.watcher.game_running:
            return f"Waiting for Dead by Daylight ({HOTKEY_NAME} starts a match anyway)"
        if self.config["auto_detect"]:
            return f"Waiting for you to spawn ({HOTKEY_NAME} = manual)"
        return f"Press {HOTKEY_NAME} when you spawn"

    def _on_game_running(self, running: bool):
        if not running:
            self.end_match()
        self.state_changed.emit()

    def _on_hud_sample(self, score: float, status: str):
        self.hud_score, self.hud_status = score, status
        self.hud_updated.emit()
        if not self.running or not self.config["auto_detect"]:
            return
        now = time.monotonic()
        if score >= float(self.config["hud_threshold"]):
            self._hud_hits += 1
            self._hud_misses = 0
            self._hud_last_seen = now
            # Two samples in a row (~1 s) so a single lucky frame can't start a match
            if not self.in_match and not self._auto_blocked and self._hud_hits >= 2:
                self.begin_match(manual=False)
        else:
            self._hud_hits = 0
            self._hud_misses += 1
            if self._hud_misses >= 10:
                self._auto_blocked = False
            if (self.in_match and not self._manual_match
                    and now - self._hud_last_seen > float(self.config["hud_lost_timeout"])):
                self.end_match()

    def _on_key(self, name: str):
        if name == "space":
            self.on_space()
        elif name == "hotkey":
            self.toggle_match()
        elif name == "flashlight" and self.in_match and self.config["pov_enabled"]:
            self.hud.set_flashlight(True)

    def _on_key_released(self, name: str):
        if name == "flashlight":
            self.hud.set_flashlight(False)

    def _on_blind(self):
        # The flashlight burst was seen on screen: show what the blinded killer sees
        if self.in_match and self.config["pov_enabled"]:
            self.show_killer_pov()

    # -- match --------------------------------------------------------------

    def toggle_match(self):
        if self.in_match:
            self.end_match()
            self._auto_blocked = True
        else:
            self.begin_match()

    def begin_match(self, manual: bool = True):
        if self.in_match:
            return
        if not self.running:
            self.start()
        self._manual_match = manual
        self._hud_last_seen = time.monotonic()
        self.match_start = time.monotonic()
        self.overlay.start_match(self.match_start, self.hud.game_center)
        if self.config["music_enabled"]:
            self.audio.start_music()
        self._beat_fallback.start()
        self._schedule_kobe(first=True)
        self._schedule_sound()
        self._schedule_dance()
        self.state_changed.emit()

    def end_match(self):
        if not self.in_match:
            return
        self.match_start = None
        self._kobe_timer.stop()
        self._sound_timer.stop()
        self._dance_timer.stop()
        self.dance.stop()
        self.hud.set_flashlight(False)
        self._beat_fallback.stop()
        self.audio.stop_music()
        self.overlay.end_match()
        self.state_changed.emit()

    # -- effects ------------------------------------------------------------

    def _on_beat(self):
        self._last_beat = time.monotonic()
        if self.in_match:
            self.overlay.kick()

    def _fallback_beat(self):
        if time.monotonic() - self._last_beat > 1.5:
            self.overlay.kick()

    def on_space(self):
        if not self.in_match or not self.config["man_enabled"]:
            return
        now = time.monotonic()
        if now - self._last_man < float(self.config["man_cooldown"]):
            return
        self._last_man = now
        self.audio.play("man")

    def show_kobe(self):
        if not self.in_match or self.dance.playing():
            return
        choices = [t for t in self._texts if t != self._last_text] or self._texts
        text = random.choice(choices)
        self._last_text = text
        # Random sprite + random line, always together with "What can I say"
        if self.overlay.show_kobe(text, float(self.config["kobe_duration"])):
            self._last_kobe = time.monotonic()
            self.audio.play("what_can_i_say")

    def _scheduled_kobe(self):
        if self.config["kobe_enabled"]:
            self.show_kobe()
        self._schedule_kobe(first=False)

    def _schedule_kobe(self, first: bool):
        if not self.in_match:
            return
        if first:
            delay = random.uniform(float(self.config["kobe_first_min"]), float(self.config["kobe_first_max"]))
        else:
            delay = jittered(float(self.config["kobe_every"]))
        self._kobe_timer.start(int(delay * 1000))

    def show_killer_pov(self):
        if self.in_match:
            self.overlay.show_killer_pov(float(self.config["pov_duration"]))

    def show_hiding(self):
        if self.in_match:
            self.overlay.show_hiding()

    def show_dance(self):
        if self.in_match:
            self.dance.start(self.overlay.dance_height(), float(self.config["dance_duration"]))

    def _scheduled_dance(self):
        if not self.in_match:
            return
        # Kobe's speech bubble and the dance share the left side; don't stack them
        if self.overlay.kobe_active() or self.dance.playing():
            self._dance_timer.start(5000)
            return
        if self.config["dance_enabled"]:
            self.show_dance()
        self._schedule_dance()

    def _schedule_dance(self):
        if not self.in_match or not self.dance.available:
            return
        self._dance_timer.start(int(jittered(float(self.config["dance_every"])) * 1000))

    def set_preview(self, on: bool):
        """Scale mode: show every overlay element on screen while sizes are tuned."""
        if on == self.previewing:
            return
        self.previewing = on
        if on:
            self.overlay.dance_preview = self.dance.still(self.overlay.dance_height() or 600)
        self.overlay.set_preview(on, self.hud.game_center)
        self.state_changed.emit()

    def play_random_sound(self):
        if self.in_match:
            self.audio.play_random()

    def _scheduled_sound(self):
        if not self.in_match:
            return
        # Don't talk over a Kobe pop-up; try again a little later
        if self.overlay.kobe_active() or time.monotonic() - self._last_kobe < 3:
            self._sound_timer.start(5000)
            return
        if self.config["random_sounds_enabled"]:
            self.audio.play_random()
        self._schedule_sound()

    def _schedule_sound(self):
        if not self.in_match or not self.audio.random_keys:
            return
        delay = jittered(float(self.config["sound_every"]))
        self._sound_timer.start(int(delay * 1000))

    # -- settings -----------------------------------------------------------

    def set_option(self, key: str, value):
        self.config[key] = value
        if key == "timer_enabled":
            self.overlay.timer_visible = value
        elif key == "music_enabled" and self.in_match:
            if value:
                self.audio.start_music()
            else:
                self.audio.stop_music()
        elif key == "music_volume":
            self.audio.set_music_volume(value)
        elif key == "sfx_volume":
            self.audio.set_sfx_volume(value)
        elif key.startswith("scale_"):
            self.overlay.set_scale(key[len("scale_"):], float(value))
            if key == "scale_dance" and self.previewing:
                self.overlay.dance_preview = self.dance.still(self.overlay.dance_height())
        elif key == "kobe_every" and self._kobe_timer.isActive():
            self._schedule_kobe(first=False)  # apply the new frequency right away
        elif key == "sound_every" and self._sound_timer.isActive():
            self._schedule_sound()
        elif key == "dance_every" and self._dance_timer.isActive():
            self._schedule_dance()
        elif key in ("auto_detect", "pov_enabled") and self.running:
            if self._needs_screen():
                self.hud.start()
            else:
                self.hud.stop()
        self.state_changed.emit()
