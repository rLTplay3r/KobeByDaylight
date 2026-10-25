"""User settings, persisted as JSON in the per-user config directory."""

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import APP_ID

DEFAULTS = {
    "autostart": True,           # start watching for matches when the app launches
    "auto_detect": True,         # start/end matches from the perk HUD on screen
    "hud_threshold": 0.68,       # rhombus score that counts as "perk HUD visible"
    "hud_lost_timeout": 25.0,    # seconds without the HUD before the match ends
    "music_enabled": True,
    "timer_enabled": True,
    "kobe_enabled": True,
    "man_enabled": True,
    "music_volume": 0.45,
    "sfx_volume": 0.85,
    "random_sounds_enabled": True,
    "kobe_first_min": 5.0,       # the first Kobe comes this many seconds after spawn...
    "kobe_first_max": 20.0,      # ...at a random moment up to this
    "kobe_every": 80.0,          # average seconds between Kobe pop-ups (actual: +-40%)
    "kobe_duration": 4.0,
    "sound_every": 45.0,         # average seconds between random extra Kobe sounds
    "man_cooldown": 0.7,         # seconds; Space is also the skill-check key
    "scale_timer": 1.0,          # size multipliers for the on-screen elements
    "scale_kobe": 1.0,
    "scale_bubble": 1.0,
    "beat_fallback_interval": 0.42,  # timer shake tempo when the music gives no beat
}


def config_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    return Path(base) / APP_ID / "settings.json"


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.data = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass
