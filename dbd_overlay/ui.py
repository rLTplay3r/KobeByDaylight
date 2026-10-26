"""Tray icon and the control panel, styled after the Dead by Daylight menus."""

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, paths
from .controller import HOTKEY_NAME, Controller
from .theme import (
    MUTED, RED_GLOW, STATUS_COLORS, BloodBackground, BloodSlider, BrushButton, PerkToggle,
    SectionTitle, SplatterPanel, StatusDiamond, WindowButton, heading_font,
)

TOGGLES = [
    ("auto_detect", "Auto-detect match"),
    ("music_enabled", "Music"),
    ("timer_enabled", "Timer"),
    ("kobe_enabled", "Kobe pop-ups"),
    ("random_sounds_enabled", "Random sounds"),
    ("man_enabled", '"Man" on Space'),
    ("dance_enabled", "Kobe dance"),
    ("pov_enabled", "Killer POV on blind"),
]

# Frequency sliders: right = more often. Value is the average seconds between events,
# on a log scale so short intervals get finer steps.
FREQUENCIES = [
    ("kobe_every", "Kobe", 300.0, 15.0),
    ("sound_every", "Sounds", 180.0, 10.0),
    ("dance_every", "Dance", 300.0, 20.0),
]


def slider_to_seconds(v: int, rare: float, often: float) -> float:
    return rare * (often / rare) ** (v / 100)


def seconds_to_slider(seconds: float, rare: float, often: float) -> int:
    seconds = min(max(seconds, often), rare)
    return round(math.log(seconds / rare) / math.log(often / rare) * 100)


# On-screen element sizes, 50-200% of the default
SCALES = [("scale_timer", "Timer"), ("scale_kobe", "Kobe"), ("scale_bubble", "Bubble"),
          ("scale_dance", "Dance"), ("scale_pov", "Killer POV")]
SCALE_MIN, SCALE_MAX = 0.5, 2.0


def slider_to_scale(v: int) -> float:
    return round(SCALE_MIN + (SCALE_MAX - SCALE_MIN) * v / 100, 2)


def scale_to_slider(scale: float) -> int:
    return round((scale - SCALE_MIN) / (SCALE_MAX - SCALE_MIN) * 100)


MAX_PANEL_HEIGHT = 600

DANCE_MIN, DANCE_MAX = 3.0, 30.0  # seconds


def slider_to_dance(v: int) -> float:
    return round(DANCE_MIN + (DANCE_MAX - DANCE_MIN) * v / 100)


def dance_to_slider(secs: float) -> int:
    return round((min(max(secs, DANCE_MIN), DANCE_MAX) - DANCE_MIN) / (DANCE_MAX - DANCE_MIN) * 100)


STATUS_TITLES = {
    "stopped": "Overlay stopped",
    "off": "Game not running",
    "game": "In the lobby",
    "match": "In a trial",
}


_logo: QPixmap | None = None


def logo() -> QPixmap:
    """The Kobe by Daylight artwork (KBD_icon.jpg)."""
    global _logo
    if _logo is None:
        _logo = QPixmap(str(paths.APP_ICON))
    return _logo


def make_icon(status: str | None = None) -> QIcon:
    icon = QIcon()
    art = logo()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not art.isNull():
            p.drawPixmap(pm.rect(), art.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        else:  # artwork missing: plain gold 24 on purple
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#552583"))
            p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
            p.setPen(QColor("#FDB927"))
            p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "24")
        if status:
            # Dot in the bottom-right corner with a dark ring so it reads on any panel
            d = size * 0.46
            ring = max(1.0, size / 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 20, 20))
            p.drawEllipse(QRectF(size - d, size - d, d, d))
            p.setBrush(STATUS_COLORS[status])
            p.drawEllipse(QRectF(size - d + ring, size - d + ring, d - 2 * ring, d - 2 * ring))
        p.end()
        icon.addPixmap(pm)
    return icon


def _label(text: str, font: QFont, color: QColor | None = None) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(font)
    if color is not None:
        lbl.setStyleSheet(f"color: {color.name()};")
    return lbl


class ControlPanel(BloodBackground):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        # No system frame: the torn edge is the border, the buttons are drawn in the header
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.setWindowIcon(make_icon())
        # Content scrolls when the screen is shorter than the panel (e.g. 768 px)
        content = QWidget()
        content.setFixedWidth(430)
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._scroll = QScrollArea()
        self._scroll.setWidget(content)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.EDGE + 2, self.EDGE + 2, self.EDGE + 2, self.EDGE + 2)
        outer.addWidget(self._scroll)
        self._content = content

        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        # -- header -----------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(12)
        art = QLabel()
        art.setPixmap(logo().scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        header.addWidget(art)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        title = _label("Kobe by Daylight", heading_font(25, QFont.Weight.Bold, 2.5))
        glow = QGraphicsDropShadowEffect(title)
        glow.setColor(RED_GLOW)
        glow.setBlurRadius(22)
        glow.setOffset(0, 0)
        title.setGraphicsEffect(glow)
        heading.addWidget(title)
        heading.addWidget(_label("Mamba overlay for Dead by Daylight", heading_font(11, QFont.Weight.Light, 1.8), MUTED))
        header.addLayout(heading, 1)
        header.addSpacing(40)  # room for the window buttons floating in the corner
        layout.addLayout(header)

        # -- status card ------------------------------------------------------
        card = SplatterPanel(seed=11)
        card_row = QHBoxLayout(card)
        card_row.setContentsMargins(12, 12, 12, 12)
        card_row.setSpacing(12)
        self.status_light = StatusDiamond()
        card_row.addWidget(self.status_light)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.status_title = _label("", heading_font(19, QFont.Weight.DemiBold, 2))
        self.status_detail = QLabel()
        self.status_detail.setObjectName("muted")
        self.status_detail.setWordWrap(True)
        # Room for two lines so a wrapped status never gets clipped
        self.status_detail.setMinimumHeight(self.status_detail.fontMetrics().lineSpacing() * 2 + 4)
        texts.addWidget(self.status_title)
        texts.addWidget(self.status_detail)
        card_row.addLayout(texts, 1)
        layout.addWidget(card)

        self.start_btn = BrushButton(primary=True)
        self.start_btn.clicked.connect(lambda: ctl.stop() if ctl.running else ctl.start())
        layout.addWidget(self.start_btn)

        # -- effects ----------------------------------------------------------
        layout.addWidget(SectionTitle("Effects"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self.checks: dict[str, PerkToggle] = {}
        for i, (key, label) in enumerate(TOGGLES):
            t = PerkToggle(label)
            t.toggled.connect(lambda v, k=key: ctl.set_option(k, v))
            grid.addWidget(t, i // 2, i % 2)
            self.checks[key] = t
        layout.addLayout(grid)

        # -- volume -----------------------------------------------------------
        layout.addWidget(SectionTitle("Volume"))
        self.sliders: dict[str, BloodSlider] = {}
        self.slider_values: dict[str, QLabel] = {}
        for key, label in (("music_volume", "Music"), ("sfx_volume", "Sounds")):
            row = QHBoxLayout()
            name = _label(label, heading_font(14, QFont.Weight.Normal, 1.2))
            name.setFixedWidth(70)
            row.addWidget(name)
            s = BloodSlider()
            value = _label("", heading_font(14, QFont.Weight.Normal, 1), MUTED)
            value.setFixedWidth(42)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            s.valueChanged.connect(lambda v, k=key, lbl=value: (lbl.setText(f"{v}%"), ctl.set_option(k, v / 100)))
            row.addWidget(s, 1)
            row.addWidget(value)
            layout.addLayout(row)
            self.sliders[key] = s
            self.slider_values[key] = value

        # -- frequency ----------------------------------------------------------
        layout.addWidget(SectionTitle("Frequency"))
        self.freq_sliders: dict[str, BloodSlider] = {}
        self.freq_values: dict[str, QLabel] = {}
        for key, label, rare, often in FREQUENCIES:
            row = QHBoxLayout()
            name = _label(label, heading_font(14, QFont.Weight.Normal, 1.2))
            name.setFixedWidth(70)
            row.addWidget(name)
            row.addWidget(_label("Rare", heading_font(11, QFont.Weight.Light, 1), MUTED))
            s = BloodSlider()
            s.setToolTip("Average time between them; the real timing varies randomly around it")
            value = _label("", heading_font(14, QFont.Weight.Normal, 1, caps=False), MUTED)
            value.setFixedWidth(58)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            def changed(v, k=key, lbl=value, r=rare, o=often):
                secs = slider_to_seconds(v, r, o)
                lbl.setText(f"~{secs:.0f} s")
                ctl.set_option(k, round(secs, 1))

            s.valueChanged.connect(changed)
            row.addWidget(s, 1)
            row.addWidget(_label("Often", heading_font(11, QFont.Weight.Light, 1), MUTED))
            row.addWidget(value)
            layout.addLayout(row)
            self.freq_sliders[key] = s
            self.freq_values[key] = value

        # Dance length
        row = QHBoxLayout()
        name = _label("Dance length", heading_font(14, QFont.Weight.Normal, 1.2))
        name.setFixedWidth(120)
        row.addWidget(name)
        self.dance_len = BloodSlider()
        self.dance_len.setToolTip("How long Kobe dances each time")
        self.dance_len_value = _label("", heading_font(14, QFont.Weight.Normal, 1, caps=False), MUTED)
        self.dance_len_value.setFixedWidth(58)
        self.dance_len_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def dance_len_changed(v):
            secs = slider_to_dance(v)
            self.dance_len_value.setText(f"{secs:.0f} s")
            ctl.set_option("dance_duration", secs)

        self.dance_len.valueChanged.connect(dance_len_changed)
        row.addWidget(self.dance_len, 1)
        row.addWidget(self.dance_len_value)
        layout.addLayout(row)

        # -- scale ------------------------------------------------------------
        layout.addWidget(SectionTitle("Scale"))
        self.scale_sliders: dict[str, BloodSlider] = {}
        self.scale_values: dict[str, QLabel] = {}
        for key, label in SCALES:
            row = QHBoxLayout()
            name = _label(label, heading_font(14, QFont.Weight.Normal, 1.2))
            name.setFixedWidth(70)
            row.addWidget(name)
            s = BloodSlider()
            value = _label("", heading_font(14, QFont.Weight.Normal, 1), MUTED)
            value.setFixedWidth(42)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            def scaled(v, k=key, lbl=value):
                scale = slider_to_scale(v)
                lbl.setText(f"{scale * 100:.0f}%")
                ctl.set_option(k, scale)

            s.valueChanged.connect(scaled)
            row.addWidget(s, 1)
            row.addWidget(value)
            layout.addLayout(row)
            self.scale_sliders[key] = s
            self.scale_values[key] = value
        scale_buttons = QHBoxLayout()
        self.preview_btn = BrushButton()
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("Unlocks the sizes and shows every element on screen as a preview")
        self.preview_btn.toggled.connect(ctl.set_preview)
        scale_buttons.addWidget(self.preview_btn, 1)
        reset = self.reset_sizes_btn = BrushButton("RESET SIZES")
        reset.clicked.connect(self._reset_sizes)
        scale_buttons.addWidget(reset)
        layout.addLayout(scale_buttons)

        # -- manual trial controls ---------------------------------------------
        layout.addWidget(SectionTitle("Trial"))
        buttons = QGridLayout()
        buttons.setHorizontalSpacing(6)
        buttons.setVerticalSpacing(4)
        for i, (label, slot, tip) in enumerate((
            ("Spawn", lambda: ctl.begin_match(), f"Start a match now ({HOTKEY_NAME} in game)"),
            ("Space", ctl.on_space, 'Play "Man"'),
            ("Kobe", ctl.show_kobe, "Show a Kobe pop-up"),
            ("Sound", ctl.play_random_sound, "Play a random Kobe sound"),
            ("Dance", ctl.show_dance, "Make Kobe dance"),
            ("Hide", ctl.show_hiding, 'Kobe going "shh", as when you hide in a locker'),
            ("POV", ctl.show_killer_pov, "Show the blinded killer's view (normally: when you blind the killer)"),
            ("End", ctl.end_match, f"End the match ({HOTKEY_NAME} in game)"),
        )):
            b = BrushButton(label.upper())
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.addWidget(b, i // 4, i % 4)
        layout.addLayout(buttons)
        hint = QLabel(f"{HOTKEY_NAME} starts or ends a match in game. Spawns are detected automatically.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # -- footer -----------------------------------------------------------
        layout.addSpacing(6)
        footer = QHBoxLayout()
        self.hud_info = QLabel()
        self.hud_info.setObjectName("muted")
        self.hud_info.setWordWrap(True)
        footer.addWidget(self.hud_info, 1)
        save = QPushButton("Save HUD capture")
        save.setObjectName("link")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setToolTip("Saves the next screenshot of the HUD corner, for tuning the detection")
        save.clicked.connect(ctl.hud.save_debug_capture)
        footer.addWidget(save, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(footer)
        keys = QLabel(f"Key detection: {ctl.keys.backend}")
        keys.setObjectName("muted")
        layout.addWidget(keys)

        credits = QHBoxLayout()
        made = QVBoxLayout()
        made.setSpacing(0)
        made.addWidget(_label("Created by LT and Claude", heading_font(12, QFont.Weight.Normal, 1.5)))
        based = QLabel("Based on ering6666's Dead by Daylight edits")
        based.setObjectName("muted")
        made.addWidget(based)
        credits.addLayout(made, 1)
        credits.addWidget(_label(f"v{__version__}", heading_font(13, QFont.Weight.Normal, 1.5, caps=False), RED_GLOW),
                          0, Qt.AlignmentFlag.AlignBottom)
        layout.addSpacing(4)
        layout.addLayout(credits)

        # Window buttons float over the content in the top-right corner, so they
        # stay reachable while the panel is scrolled
        self._minimize = WindowButton("min", self)
        self._minimize.clicked.connect(self.showMinimized)
        self._close = WindowButton("close", self)
        self._close.clicked.connect(self.hide)

        ctl.state_changed.connect(self.refresh)
        ctl.hud_updated.connect(self.refresh_hud)
        self.refresh()
        self.refresh_hud()
        self.fit_to_screen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        top = self.EDGE + 6
        self._close.move(self.width() - self.EDGE - 8 - self._close.width(), top)
        self._minimize.move(self._close.x() - self._minimize.width(), top)
        self._close.raise_()
        self._minimize.raise_()

    def fit_to_screen(self):
        hint = self._content.sizeHint()
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry().height() - 60 if screen else hint.height()
        avail = min(avail, MAX_PANEL_HEIGHT)  # compact window, the rest scrolls
        scrollbar = self._scroll.verticalScrollBar().sizeHint().width()
        frame = 2 * (self.EDGE + 2)
        self.setFixedWidth(430 + frame + (0 if hint.height() + frame <= avail else scrollbar))
        self.resize(self.width(), min(hint.height() + frame, avail))

    def showEvent(self, event):
        self.fit_to_screen()
        super().showEvent(event)

    def refresh_hud(self):
        ctl = self.ctl
        seen = ctl.hud_score >= float(ctl.config["hud_threshold"])
        self.hud_info.setText(f"HUD: {'visible' if seen else 'not visible'} "
                              f"(score {ctl.hud_score:.2f}) - {ctl.hud_status}")

    def refresh(self):
        ctl, cfg = self.ctl, self.ctl.config
        status = ctl.status_key()
        self.status_light.set_status(status)
        self.status_title.setText(STATUS_TITLES[status])
        self.status_detail.setText(ctl.status_text())
        self.start_btn.setText("STOP" if ctl.running else "START")
        for key, toggle in self.checks.items():
            toggle.blockSignals(True)
            toggle.setChecked(cfg[key])
            toggle.blockSignals(False)
            toggle.update()
        for key, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(cfg[key] * 100))
            slider.blockSignals(False)
            self.slider_values[key].setText(f"{slider.value()}%")
        self.dance_len.blockSignals(True)
        self.dance_len.setValue(dance_to_slider(float(cfg["dance_duration"])))
        self.dance_len.blockSignals(False)
        self.dance_len_value.setText(f"{float(cfg['dance_duration']):.0f} s")
        for key, _ in SCALES:
            slider = self.scale_sliders[key]
            slider.blockSignals(True)
            slider.setValue(scale_to_slider(float(cfg[key])))
            slider.blockSignals(False)
            self.scale_values[key].setText(f"{float(cfg[key]) * 100:.0f}%")
        self.preview_btn.blockSignals(True)
        self.preview_btn.setChecked(ctl.previewing)
        self.preview_btn.blockSignals(False)
        self.preview_btn.setText("DONE" if ctl.previewing else "EDIT SCALE")
        # Sizes only change in scale mode, so scrolling or a stray click can't move them
        for slider in self.scale_sliders.values():
            slider.setEnabled(ctl.previewing)
        self.reset_sizes_btn.setEnabled(ctl.previewing)
        for key, _, rare, often in FREQUENCIES:
            slider = self.freq_sliders[key]
            slider.blockSignals(True)
            slider.setValue(seconds_to_slider(float(cfg[key]), rare, often))
            slider.blockSignals(False)
            self.freq_values[key].setText(f"~{float(cfg[key]):.0f} s")

    def mousePressEvent(self, event):
        # Frameless: drag the window by any empty spot of the panel
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def _reset_sizes(self):
        # Straight to 1.0; going through the slider would round it to 0.99
        for key, _ in SCALES:
            self.ctl.set_option(key, 1.0)

    def closeEvent(self, event):
        # Closing the window only hides it; the app keeps running in the tray
        event.ignore()
        self.hide()

    def hideEvent(self, event):
        self.ctl.set_preview(False)
        super().hideEvent(event)


class Tray(QSystemTrayIcon):
    def __init__(self, ctl: Controller, panel: ControlPanel, quit_fn):
        super().__init__(make_icon("stopped"))
        self._shown_status = "stopped"
        self.ctl, self.panel = ctl, panel
        self.setToolTip(APP_NAME)

        menu = QMenu()
        menu.addAction("Open panel", self.show_panel)
        self.start_action = menu.addAction("Start", lambda: ctl.stop() if ctl.running else ctl.start())
        menu.addSeparator()
        self.toggle_actions: dict[str, QAction] = {}
        for key, label in TOGGLES:
            a = menu.addAction(label)
            a.setCheckable(True)
            a.toggled.connect(lambda v, k=key: ctl.set_option(k, v))
            self.toggle_actions[key] = a
        menu.addSeparator()
        sim = menu.addMenu("Match")
        sim.addAction(f"Spawn into match ({HOTKEY_NAME})", lambda: ctl.begin_match())
        sim.addAction("Press Space", ctl.on_space)
        sim.addAction("Show Kobe", ctl.show_kobe)
        sim.addAction("Random sound", ctl.play_random_sound)
        sim.addAction("Kobe dance", ctl.show_dance)
        sim.addAction("Hide (shh)", ctl.show_hiding)
        sim.addAction("Killer POV", ctl.show_killer_pov)
        sim.addAction("End match", ctl.end_match)
        menu.addSeparator()
        menu.addAction("Quit", quit_fn)
        self._menu = menu
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        ctl.state_changed.connect(self.refresh)
        self.refresh()

    def show_panel(self):
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.panel.isVisible():
                self.panel.hide()
            else:
                self.show_panel()

    def refresh(self):
        status = self.ctl.status_key()
        if status != self._shown_status:
            self._shown_status = status
            self.setIcon(make_icon(status))
        self.start_action.setText("Stop" if self.ctl.running else "Start")
        self.setToolTip(f"{APP_NAME} v{__version__} - {self.ctl.status_text()}")
        for key, action in self.toggle_actions.items():
            action.blockSignals(True)
            action.setChecked(self.ctl.config[key])
            action.blockSignals(False)
