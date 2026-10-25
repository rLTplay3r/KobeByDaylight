# PyInstaller spec for the builder app: pyinstaller --distpath . packaging/builder.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "builder_entry.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "fonts"), "fonts"), (str(ROOT / "KBD_icon.jpg"), ".")],
    hiddenimports=["builder.app", "builder.runner", "builder.steps", "dbd_overlay.theme"],
    # Only QtCore / QtGui / QtWidgets are used; keep the rest of the overlay's stack out
    excludes=["tkinter", "cv2", "numpy", "psutil", "pynput", "Xlib", "mss", "PySide6.QtMultimedia",
              "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtOpenGL"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="KBD-Builder", console=False, upx=False)
