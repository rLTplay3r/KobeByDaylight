"""Builder window, in the same Dead by Daylight style as the overlay's panel."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QVBoxLayout,
    QWidget,
)

from dbd_overlay.theme import (
    BG, MUTED, RED_DARK, RED_GLOW, TEXT, BrushButton, PerkToggle, SectionTitle, heading_font,
)

from . import steps
from .runner import Runner

DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / "kbd-builder.desktop"

EXTRA_STYLE = f"""
QWidget#root {{ background: {BG.name()}; }}
QLineEdit, QPlainTextEdit {{
    background: rgba(25, 16, 16, 230); border: none; border-bottom: 1px solid {RED_DARK.name()};
    padding: 6px; selection-background-color: {RED_DARK.name()};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-bottom: 1px solid {RED_GLOW.name()}; }}
QPlainTextEdit#log {{ background: rgba(8, 5, 5, 240); border: none; color: #d9cfc9; }}
QProgressBar {{ background: rgba(40, 28, 28, 220); border: none; height: 6px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6e0f0f, stop:1 #ff3b30); }}
"""


class BuilderWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Kobe by Daylight - Builder")
        self.setWindowIcon(QIcon(str(steps.ROOT / "KBD_icon.jpg")))
        self.resize(760, 720)
        self.runner = Runner(self)
        self.runner.step_started.connect(self._on_step)
        self.runner.output.connect(self._append)
        self.runner.finished.connect(self._on_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        # -- header -------------------------------------------------------------
        header = QHBoxLayout()
        art = QLabel()
        art.setPixmap(QPixmap(str(steps.ROOT / "KBD_icon.jpg")).scaled(
            56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(art)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Kobe by Daylight Builder")
        title.setFont(heading_font(24, QFont.Weight.Bold, 2.5))
        titles.addWidget(title)
        sub = QLabel(f"Project: {steps.ROOT}")
        sub.setFont(heading_font(11, QFont.Weight.Light, 1.2, caps=False))
        sub.setStyleSheet(f"color: {MUTED.name()};")
        titles.addWidget(sub)
        header.addLayout(titles, 1)
        layout.addLayout(header)

        # -- targets ------------------------------------------------------------
        layout.addWidget(SectionTitle("Targets"))
        targets = QHBoxLayout()
        self.linux = PerkToggle("Linux executable")
        self.linux.setChecked(True)
        self.windows = PerkToggle("Windows .exe (via Wine)")
        self.windows.setChecked(True)
        targets.addWidget(self.linux)
        targets.addWidget(self.windows)
        layout.addLayout(targets)

        # -- version ------------------------------------------------------------
        layout.addWidget(SectionTitle("Version"))
        row = QHBoxLayout()
        current = QLabel(f"Current: v{steps.read_version()}")
        current.setFont(heading_font(14, QFont.Weight.Normal, 1.2, caps=False))
        self.current_label = current
        row.addWidget(current)
        row.addSpacing(16)
        row.addWidget(QLabel("Build as"))
        self.version = QLineEdit(steps.read_version())
        self.version.setFixedWidth(110)
        row.addWidget(self.version)
        bump = BrushButton("+1")
        bump.setFixedWidth(60)
        bump.setToolTip("Raise the last number of the version")
        bump.clicked.connect(lambda: self.version.setText(steps.next_version(self.version.text().strip())))
        row.addWidget(bump)
        row.addStretch(1)
        layout.addLayout(row)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("What changed (optional, one line per change) - written to CHANGELOG.md")
        self.notes.setFixedHeight(64)
        layout.addWidget(self.notes)

        # -- actions ------------------------------------------------------------
        actions = QHBoxLayout()
        self.build_btn = BrushButton("BUILD", primary=True)
        self.build_btn.clicked.connect(self.start_build)
        actions.addWidget(self.build_btn, 3)
        self.cancel_btn = BrushButton("CANCEL")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        actions.addWidget(self.cancel_btn, 1)
        layout.addLayout(actions)

        self.status = QLabel("Ready")
        self.status.setFont(heading_font(14, QFont.Weight.Normal, 1.2))
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        # -- log ----------------------------------------------------------------
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPixelSize(12)
        self.log.setFont(mono)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log, 1)

        # -- results ------------------------------------------------------------
        bottom = QHBoxLayout()
        self.results = QLabel()
        self.results.setStyleSheet(f"color: {TEXT.name()};")
        self.results.setWordWrap(True)
        bottom.addWidget(self.results, 1)
        open_dist = BrushButton("OPEN DIST FOLDER")
        open_dist.clicked.connect(lambda: subprocess.Popen(["xdg-open", str(steps.DIST)]))
        bottom.addWidget(open_dist)
        menu = BrushButton("ADD TO APP MENU")
        menu.setToolTip(f"Creates {DESKTOP_FILE}")
        menu.clicked.connect(self.add_to_menu)
        bottom.addWidget(menu)
        layout.addLayout(bottom)

        self._show_outputs()

    # -- build ------------------------------------------------------------------

    def selected_targets(self) -> list[str]:
        return [t for t, box in (("linux", self.linux), ("windows", self.windows)) if box.isChecked()]

    def start_build(self):
        targets = self.selected_targets()
        if not targets:
            QMessageBox.warning(self, "Nothing to build", "Pick Linux, Windows or both.")
            return
        missing = steps.missing_tools(targets)
        if missing:
            QMessageBox.critical(self, "Missing tools", "Install first:\n\n" + "\n".join(missing))
            return
        version = self.version.text().strip()
        if not steps.valid_version(version):
            QMessageBox.warning(self, "Version", f"'{version}' is not a version like 0.0.16.")
            return
        self.log.clear()
        for change in steps.write_version(version, self.notes.toPlainText()):
            self._append(f"* {change}\n")
        self.notes.clear()
        self.current_label.setText(f"Current: v{steps.read_version()}")
        self._set_busy(True)
        self.runner.start(steps.plan(targets))

    def _set_busy(self, busy: bool):
        self.build_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        for w in (self.linux, self.windows, self.version):
            w.setEnabled(not busy)

    def _on_step(self, index: int, total: int, title: str):
        self.progress.setMaximum(total)
        self.progress.setValue(index)
        self.status.setText(f"Step {index + 1} of {total}: {title}")

    def _append(self, text: str):
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _on_finished(self, ok: bool, message: str):
        self._set_busy(False)
        if ok:
            self.progress.setValue(self.progress.maximum())
        self.status.setText(message)
        self.status.setStyleSheet("" if ok else f"color: {RED_GLOW.name()};")
        self._append(f"\n=== {message} ===\n")
        self._show_outputs()

    def _show_outputs(self):
        parts = []
        for target, path in steps.OUTPUTS.items():
            if path.exists():
                parts.append(f"<b>{path.name}</b> ({steps.size_text(path)})")
        self.results.setText("In dist/: " + ", ".join(parts) if parts else "No executables in dist/ yet")

    def add_to_menu(self):
        DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        launcher = Path(sys.executable) if steps.FROZEN else steps.ROOT / "build-tool.sh"
        DESKTOP_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=Kobe by Daylight Builder\n"
            "Comment=Build the Kobe by Daylight executables\n"
            f"Exec=\"{launcher}\"\nIcon={steps.ROOT / 'KBD_icon.jpg'}\n"
            f"Path={steps.ROOT}\nTerminal=false\nCategories=Development;\n",
            encoding="utf-8")
        QMessageBox.information(self, "App menu", "Added. Look for \"Kobe by Daylight Builder\" in the app menu.")

    def closeEvent(self, event):
        if self.runner.running:
            if QMessageBox.question(self, "Build running", "A build is running. Stop it and quit?") \
                    != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.cancel()
        super().closeEvent(event)
