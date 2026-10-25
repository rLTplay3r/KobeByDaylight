"""Background music and sound effects on two independent volume channels."""

import array
import random
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, QVariantAnimation, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QMediaPlayer

try:
    from PySide6.QtMultimedia import QAudioBufferOutput  # Qt 6.8+
except ImportError:
    QAudioBufferOutput = None

from . import paths


class BeatDetector:
    """Online kick detector: low-passed energy compared to its moving average."""

    RATE = 11025
    HOP = 256
    MIN_GAP = 0.25

    def __init__(self):
        self.reset()

    def reset(self):
        self._lp = 0.0
        self._acc = 0.0
        self._n = 0
        self._avg = 0.0
        self._t = 0.0
        self._last = -1.0

    def feed(self, samples) -> bool:
        beat = False
        lp, acc, n = self._lp, self._acc, self._n
        for x in samples:
            lp += 0.08 * (x - lp)
            acc += lp * lp
            n += 1
            if n == self.HOP:
                energy = acc / self.HOP
                self._t += self.HOP / self.RATE
                if energy > self._avg * 1.6 and energy > 2e5 and self._t - self._last > self.MIN_GAP:
                    self._last = self._t
                    beat = True
                self._avg = self._avg * 0.97 + energy * 0.03
                acc, n = 0.0, 0
        self._lp, self._acc, self._n = lp, acc, n
        return beat


class Audio(QObject):
    beat = Signal()

    def __init__(self, music_volume: float, sfx_volume: float, parent=None):
        super().__init__(parent)
        self._music_volume = music_volume
        self._sfx_volume = sfx_volume

        self._music_out = QAudioOutput(self)
        self._music_out.setVolume(music_volume)
        self._music = QMediaPlayer(self)
        self._music.setAudioOutput(self._music_out)
        self._music.mediaStatusChanged.connect(self._on_music_status)
        self._tracks: list[Path] = []
        self._track_index = 0

        # Tap the decoded music (downmixed by Qt to mono int16) to find the beat
        self._beats = BeatDetector()
        self.beat_source = False
        if QAudioBufferOutput is not None:
            fmt = QAudioFormat()
            fmt.setSampleRate(BeatDetector.RATE)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._tap = QAudioBufferOutput(fmt, self)
            self._tap.audioBufferReceived.connect(self._on_buffer)
            self._music.setAudioBufferOutput(self._tap)
            self.beat_source = True

        self._fade = QVariantAnimation(self)
        self._fade.valueChanged.connect(lambda v: self._music_out.setVolume(float(v)))
        self._fade.finished.connect(self._on_fade_finished)
        self._stop_after_fade = False

        # One preloaded player per effect keeps the latency low
        self._sfx: dict[str, tuple[QMediaPlayer, QAudioOutput]] = {}
        for key, name in paths.SOUND_FILES.items():
            self._load_sfx(key, paths.SOUNDS_DIR / name)
        self.random_keys: list[str] = []
        for file in paths.random_sound_files():
            key = "random:" + file.stem
            self._load_sfx(key, file)
            self.random_keys.append(key)
        self._last_random = ""

    def _load_sfx(self, key: str, file: Path):
        if not file.is_file():
            return
        out = QAudioOutput(self)
        out.setVolume(self._sfx_volume)
        player = QMediaPlayer(self)
        player.setAudioOutput(out)
        player.setSource(QUrl.fromLocalFile(str(file)))
        self._sfx[key] = (player, out)

    # -- music --------------------------------------------------------------

    def start_music(self, fade_in: float = 1.5):
        self._tracks = paths.music_files()
        if not self._tracks:
            return
        random.shuffle(self._tracks)
        self._track_index = 0
        self._play_track()
        self._fade_to(self._music_volume, fade_in, stop=False, start_from=0.0)

    def stop_music(self, fade_out: float = 1.5):
        if self._music.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        self._fade_to(0.0, fade_out, stop=True)

    def is_music_playing(self) -> bool:
        return self._music.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _on_buffer(self, buffer):
        if self._music.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        data = buffer.constData()
        if not data:
            return
        samples = array.array("h")
        samples.frombytes(bytes(data))
        if self._beats.feed(samples):
            self.beat.emit()

    def _play_track(self):
        self._beats.reset()
        self._music.setSource(QUrl.fromLocalFile(str(self._tracks[self._track_index])))
        self._music.play()

    def _on_music_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._tracks:
            self._track_index = (self._track_index + 1) % len(self._tracks)
            self._play_track()

    def _fade_to(self, target: float, seconds: float, stop: bool, start_from: float | None = None):
        self._fade.stop()
        self._stop_after_fade = stop
        self._fade.setStartValue(self._music_out.volume() if start_from is None else start_from)
        self._fade.setEndValue(target)
        self._fade.setDuration(max(1, int(seconds * 1000)))
        self._fade.start()

    def _on_fade_finished(self):
        if self._stop_after_fade:
            self._music.stop()
            self._music_out.setVolume(self._music_volume)

    # -- effects ------------------------------------------------------------

    def play(self, key: str):
        entry = self._sfx.get(key)
        if not entry:
            return
        player, _ = entry
        player.setPosition(0)
        player.play()

    def play_random(self) -> str | None:
        """Plays one of the extra Kobe sounds, never the same one twice in a row."""
        choices = [k for k in self.random_keys if k != self._last_random] or self.random_keys
        if not choices:
            return None
        key = random.choice(choices)
        self._last_random = key
        self.play(key)
        return key

    # -- volumes ------------------------------------------------------------

    def set_music_volume(self, volume: float):
        self._music_volume = volume
        if self._fade.state() != QVariantAnimation.State.Running:
            self._music_out.setVolume(volume)

    def set_sfx_volume(self, volume: float):
        self._sfx_volume = volume
        for _, out in self._sfx.values():
            out.setVolume(volume)
