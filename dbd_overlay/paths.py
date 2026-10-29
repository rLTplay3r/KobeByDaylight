"""Locations of bundled assets."""

import sys
from pathlib import Path


def asset_roots() -> list[Path]:
    if getattr(sys, "frozen", False):
        # Files next to the executable override the ones bundled inside it,
        # so users can swap music or edit kobe_texts.txt without rebuilding.
        exe_dir = Path(sys.executable).resolve().parent
        return [exe_dir, Path(getattr(sys, "_MEIPASS", exe_dir))]
    return [Path(__file__).resolve().parent.parent]


def _asset(name: str) -> Path:
    roots = asset_roots()
    for root in roots:
        if (root / name).exists():
            return root / name
    return roots[-1] / name


MUSIC_DIR = _asset("Music")
SOUNDS_DIR = _asset("Sounds")
KOBE_SPRITES_DIR = _asset("kobe-sprites")
EFFECTS_DIR = _asset("effects")
DANCE_DIR = _asset("dancing")
DANCE_FRAMES_DIR = _asset("dance-frames")  # prepared sequences shipped with builds
KILLER_POV = EFFECTS_DIR / "killer-pov.gif"
KOBE_HIDING = EFFECTS_DIR / "kobe-hiding.png"
BUBBLE_IMAGE = _asset("speechbuble.png")
KOBE_TEXTS = _asset("kobe_texts.txt")
APP_ICON = _asset("KBD_icon.jpg")
FONTS_DIR = _asset("fonts")

# Sounds with a fixed job; every other file in Sounds/ plays at random during a match
SOUND_FILES = {
    "man": "Kobe Bryant MAN Sound Effect.mp3",
    "what_can_i_say": "Kobe Bryant What Can I Say Sound Effect.mp3",
}
AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".flac", ".m4a"}


def _files(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)


def music_files() -> list[Path]:
    return _files(MUSIC_DIR, AUDIO_EXTS)


def random_sound_files() -> list[Path]:
    fixed = set(SOUND_FILES.values())
    return [p for p in _files(SOUNDS_DIR, AUDIO_EXTS) if p.name not in fixed]


def kobe_sprites() -> list[Path]:
    return _files(KOBE_SPRITES_DIR, {".png", ".webp"})
