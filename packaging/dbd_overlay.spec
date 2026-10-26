# PyInstaller spec for Windows and Linux: pyinstaller packaging/dbd_overlay.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform == "win32"

datas = [
    (str(ROOT / "Sounds"), "Sounds"),
    (str(ROOT / "kobe-sprites"), "kobe-sprites"),
    (str(ROOT / "effects"), "effects"),
    (str(ROOT / "dancing"), "dancing"),
    (str(ROOT / "speechbuble.png"), "."),
    (str(ROOT / "kobe_texts.txt"), "."),
    (str(ROOT / "KBD_icon.jpg"), "."),
    (str(ROOT / "fonts"), "fonts"),
]

# Music isn't part of the public source (copyright): bundle whatever is in Music/, if anything
MUSIC_EXTS = {".mp3", ".ogg", ".wav", ".flac", ".m4a"}
datas += [(str(p), "Music") for p in sorted((ROOT / "Music").glob("*")) if p.suffix.lower() in MUSIC_EXTS]

# pynput picks its backend at runtime, so PyInstaller cannot see it
# HUD detection modules are imported lazily from a worker thread
hiddenimports = ["dbd_overlay.capture", "dbd_overlay.hud", "dbd_overlay.dance", "cv2", "numpy"]
hiddenimports += ["mss", "mss.windows"] if IS_WIN else [
    "pynput.keyboard._xorg", "pynput.mouse._xorg", "evdev", "Xlib.display", "Xlib.X",
]

# PyInstaller's Qt hooks find the plugin folder by importing QtCore in a helper
# process. When that fails (e.g. building under Wine, which lacks the Windows ICU
# DLLs) no plugins get bundled and the app can't even open a window, so the ones
# we need are listed explicitly. Duplicates of what the hooks add are harmless.
binaries = []
if IS_WIN:
    import glob
    import os

    import PySide6

    qt_dir = os.path.dirname(PySide6.__file__)
    for sub in ("platforms", "multimedia", "imageformats", "styles", "iconengines"):
        for dll in glob.glob(os.path.join(qt_dir, "plugins", sub, "*.dll")):
            binaries.append((dll, os.path.join("PySide6", "plugins", sub)))
    # FFmpeg used by the multimedia plugin
    for pattern in ("av*.dll", "sw*.dll"):
        for dll in glob.glob(os.path.join(qt_dir, pattern)):
            binaries.append((dll, "PySide6"))

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtSql", "PySide6.QtTest",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="DBD-Kobe-Overlay",
    console=False,  # tray app: no terminal window
    icon=str(ROOT / "packaging" / "icon.ico") if IS_WIN else None,
    upx=False,
)
