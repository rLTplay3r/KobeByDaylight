"""Convert KBD_icon.jpg into packaging/icon.ico for the Windows executable."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
art = QImage(str(ROOT / "KBD_icon.jpg"))
if art.isNull():
    sys.exit("KBD_icon.jpg not found")
art.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) \
    .save(str(ROOT / "packaging" / "icon.ico"))
print("wrote packaging/icon.ico")
