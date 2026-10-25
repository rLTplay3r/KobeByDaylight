"""Dead by Daylight look: near-black fog, blood red accents, condensed caps, perk diamonds."""

import math
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QApplication, QSizePolicy, QWidget

from . import paths

BG = QColor("#0b0909")
PANEL = QColor(22, 16, 16, 215)
LINE = QColor("#3a2424")
RED = QColor("#c41e1e")
RED_DARK = QColor("#6e0f0f")
RED_GLOW = QColor("#ff3b30")
TEXT = QColor("#ece6e1")
MUTED = QColor("#8f8580")

STATUS_COLORS = {
    "off": QColor("#e53935"),
    "game": QColor("#fdd835"),
    "match": QColor("#43a047"),
    "stopped": QColor("#9e9e9e"),
}

HEADING_FAMILY = "Oswald"
_FALLBACK = ["Oswald", "Bebas Neue", "Roboto Condensed", "DejaVu Sans Condensed", "Arial Narrow", "Sans Serif"]


def load_fonts():
    global HEADING_FAMILY
    font_id = QFontDatabase.addApplicationFont(str(paths.FONTS_DIR / "Oswald.ttf"))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if families:
        HEADING_FAMILY = families[0]
    # Base font set in code, not in the stylesheet: a stylesheet font-size would
    # override every font the widgets set themselves
    base = QFont()
    base.setPixelSize(13)
    QApplication.setFont(base)


def heading_font(px: int, weight=QFont.Weight.DemiBold, spacing: float = 1.5, caps: bool = True) -> QFont:
    f = QFont()
    f.setFamilies([HEADING_FAMILY, *_FALLBACK])
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    return f


def diamond(center: QPointF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(center.x(), center.y() - r)
    path.lineTo(center.x() + r, center.y())
    path.lineTo(center.x(), center.y() + r)
    path.lineTo(center.x() - r, center.y())
    path.closeSubpath()
    return path


def stylesheet() -> str:
    return _STYLESHEET.replace("HEADING", HEADING_FAMILY)


_STYLESHEET = f"""
QWidget {{ color: {TEXT.name()}; }}
QLabel#muted {{ color: {MUTED.name()}; font-size: 11px; }}
QPushButton {{
    background: rgba(30, 20, 20, 210); border: 1px solid {LINE.name()};
    padding: 6px 8px; font-family: "HEADING"; font-size: 13px; letter-spacing: 1px;
}}
QPushButton:hover {{ border-color: {RED.name()}; background: rgba(70, 18, 18, 220); }}
QPushButton:disabled {{ color: #5a504c; border-color: #2a1c1c; }}
QPushButton:pressed, QPushButton:checked {{ background: {RED_DARK.name()}; border-color: {RED_GLOW.name()}; }}
QPushButton#primary {{
    font-size: 18px; font-weight: 600; letter-spacing: 3px; padding: 10px;
    border: 1px solid {RED_GLOW.name()};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b31818, stop:1 #5a0b0b);
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d42222, stop:1 #6e0f0f);
}}
QPushButton#primary[running="true"] {{
    background: rgba(30, 20, 20, 220); border: 1px solid {RED.name()}; color: {TEXT.name()};
}}
QPushButton#link {{
    background: transparent; border: none; color: {MUTED.name()}; padding: 0;
    font-size: 11px; text-decoration: underline;
}}
QPushButton#link:hover {{ color: {RED_GLOW.name()}; }}
QMenu {{ background: #120d0d; border: 1px solid {LINE.name()}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 22px; }}
QMenu::item:selected {{ background: {RED_DARK.name()}; }}
QMenu::separator {{ height: 1px; background: {LINE.name()}; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {RED_DARK.name()}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {RED.name()}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}
QToolTip {{ background: #120d0d; color: {TEXT.name()}; border: 1px solid {RED.name()}; }}
"""


class SectionTitle(QWidget):
    """Caps heading with a red rule fading out to the right."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = heading_font(14, spacing=2.5)
        p.setFont(font)
        p.setPen(RED_GLOW)
        p.fillPath(diamond(QPointF(5, 13), 4), RED)
        tw = p.fontMetrics().horizontalAdvance(self._text.upper())
        p.setPen(TEXT)
        p.drawText(QRectF(16, 0, tw + 8, 26), Qt.AlignmentFlag.AlignVCenter, self._text)
        g = QLinearGradient(tw + 26, 0, self.width(), 0)
        g.setColorAt(0, RED)
        g.setColorAt(1, QColor(196, 30, 30, 0))
        p.fillRect(QRectF(tw + 26, 13, self.width() - tw - 26, 1), g)


class PerkToggle(QAbstractButton):
    """Checkbox drawn as a perk slot: empty diamond when off, lit red when on."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False

    def sizeHint(self):
        return QSize(160, 30)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(14, self.height() / 2)
        if self._hover:
            p.fillRect(self.rect(), QColor(120, 20, 20, 40))
        if self.isChecked():
            glow = QRadialGradient(c, 16)
            glow.setColorAt(0, QColor(255, 59, 48, 110))
            glow.setColorAt(1, QColor(255, 59, 48, 0))
            p.fillRect(QRectF(c.x() - 16, c.y() - 16, 32, 32), glow)
            grad = QLinearGradient(c.x(), c.y() - 10, c.x(), c.y() + 10)
            grad.setColorAt(0, QColor("#e02a2a"))
            grad.setColorAt(1, RED_DARK)
            p.fillPath(diamond(c, 10), grad)
            p.setPen(QPen(QColor("#ff8a80"), 1.2))
            p.drawPath(diamond(c, 10))
            p.fillPath(diamond(c, 3.5), TEXT)
        else:
            p.fillPath(diamond(c, 10), QColor(20, 14, 14))
            p.setPen(QPen(RED if self._hover else QColor("#5a4a46"), 1.2))
            p.drawPath(diamond(c, 10))
        p.setPen(TEXT if self.isChecked() else MUTED)
        p.setFont(heading_font(14, QFont.Weight.Normal, 1.2))
        p.drawText(QRectF(34, 0, self.width() - 34, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())


class BloodSlider(QWidget):
    """0-100 slider: dark track, blood red fill, diamond handle."""

    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, v: int):
        v = max(0, min(100, int(v)))
        if v != self._value:
            self._value = v
            self.update()
            if not self.signalsBlocked():
                self.valueChanged.emit(v)

    def _set_from_x(self, x: float):
        margin = 9
        self.setValue(round((x - margin) / max(1, self.width() - 2 * margin) * 100))

    def mousePressEvent(self, e):
        if not self.isEnabled():
            return
        self._set_from_x(e.position().x())

    def mouseMoveEvent(self, e):
        self._set_from_x(e.position().x())

    def wheelEvent(self, e):
        # Never change on scroll: the wheel scrolls the panel instead
        e.ignore()

    def changeEvent(self, e):
        super().changeEvent(e)
        self.update()  # repaint greyed out when enabled/disabled

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin, cy = 9, self.height() / 2
        span = self.width() - 2 * margin
        x = margin + span * self._value / 100
        on = self.isEnabled()
        p.fillRect(QRectF(margin, cy - 2, span, 4), QColor(40, 28, 28))
        g = QLinearGradient(margin, 0, x, 0)
        g.setColorAt(0, RED_DARK if on else QColor(60, 55, 55))
        g.setColorAt(1, RED_GLOW if on else QColor(95, 88, 86))
        p.fillRect(QRectF(margin, cy - 2, x - margin, 4), g)
        p.fillPath(diamond(QPointF(x, cy), 8), QColor(20, 14, 14))
        p.setPen(QPen(RED_GLOW if on else QColor(95, 88, 86), 1.5))
        p.drawPath(diamond(QPointF(x, cy), 8))
        p.fillPath(diamond(QPointF(x, cy), 3), TEXT if on else MUTED)


class StatusDiamond(QWidget):
    """Big status light in a perk-diamond frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = STATUS_COLORS["stopped"]
        self.setFixedSize(46, 46)

    def set_status(self, key: str):
        self._color = STATUS_COLORS[key]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        glow = QRadialGradient(c, 23)
        col = QColor(self._color)
        col.setAlpha(120)
        glow.setColorAt(0, col)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)
        p.fillPath(diamond(c, 19), QColor(15, 10, 10))
        p.setPen(QPen(QColor("#6b5a55"), 1.5))
        p.drawPath(diamond(c, 19))
        inner = QLinearGradient(c.x(), c.y() - 11, c.x(), c.y() + 11)
        inner.setColorAt(0, self._color.lighter(130))
        inner.setColorAt(1, self._color.darker(160))
        p.fillPath(diamond(c, 11), inner)


# -- blood splatter -------------------------------------------------------------

def rough_rect(rect: QRectF, rng: random.Random, amp: float, step: float = 7.0) -> QPainterPath:
    """Rectangle with torn, uneven edges (amp = how far the edge eats inwards)."""
    def edge(n):
        raw = [rng.uniform(0, amp) for _ in range(n + 1)]
        # Light smoothing so it looks torn, not noisy
        return [(raw[max(i - 1, 0)] + 2 * raw[i] + raw[min(i + 1, n)]) / 4 for i in range(n + 1)]

    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    nx, ny = max(2, int(rect.width() / step)), max(2, int(rect.height() / step))
    pts = []
    for i, d in enumerate(edge(nx)):
        pts.append(QPointF(l + rect.width() * i / nx, t + d))
    for i, d in enumerate(edge(ny)):
        pts.append(QPointF(r - d, t + rect.height() * i / ny))
    for i, d in enumerate(edge(nx)):
        pts.append(QPointF(r - rect.width() * i / nx, b - d))
    for i, d in enumerate(edge(ny)):
        pts.append(QPointF(l + d, b - rect.height() * i / ny))
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    return path


def _blob(p: QPainter, rng: random.Random, cx: float, cy: float, size: float, color: QColor):
    """Organic stain: a cluster of overlapping circles, a ring of droplets and some drips."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    # Dense core plus smaller lobes towards the rim, so the outline is uneven
    for _ in range(60):
        a, d = rng.uniform(0, 6.283), abs(rng.gauss(0, size * 0.28))
        r = max(2.0, size * rng.uniform(0.05, 0.2) * (1 - min(d / size, 0.8)))
        p.drawEllipse(QPointF(cx + math.cos(a) * d, cy + math.sin(a) * d * 0.75), r, r * rng.uniform(0.7, 1.0))
    # Spatter flung outwards, smaller the further it flies
    drop = QColor(color)
    for _ in range(90):
        a, d = rng.uniform(0, 6.283), size * rng.uniform(0.55, 1.8)
        r = max(0.7, size * 0.022 * rng.uniform(0.2, 1.0) * (1.8 - d / size))
        drop.setAlpha(min(255, color.alpha() + 30))
        p.setBrush(drop)
        p.drawEllipse(QPointF(cx + math.cos(a) * d, cy + math.sin(a) * d), r, r)
    # Drips running down from the bottom of the stain
    p.setBrush(color)
    for _ in range(rng.randint(2, 5)):
        x = cx + rng.uniform(-size * 0.45, size * 0.45)
        w = rng.uniform(2, size * 0.06 + 2)
        top = cy + size * rng.uniform(0.1, 0.35)
        length = size * rng.uniform(0.4, 1.4)
        p.drawRoundedRect(QRectF(x - w / 2, top, w, length), w / 2, w / 2)
        p.drawEllipse(QPointF(x, top + length), w * 0.8, w * 0.9)


def blood_splatter(w: int, h: int, seed: int = 24) -> QPixmap:
    """Background stains: a few big splashes, kept mostly to the top and the edges."""
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    rng = random.Random(seed)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # (x, y, size, opacity): heavy at the top corner, faint where the controls are
    spots = [(0.1, 0.04, 0.6, 105), (0.95, 0.12, 0.35, 80), (0.03, 0.6, 0.28, 55),
             (0.98, 0.78, 0.3, 50), (0.5, 1.0, 0.32, 70)]
    for fx, fy, fs, alpha in spots:
        shade = QColor(rng.randint(95, 130), rng.randint(6, 14), rng.randint(8, 14), alpha)
        _blob(p, rng, fx * w, fy * h, fs * min(w, 520), shade)
    p.end()
    return QPixmap.fromImage(img)


class BloodBackground(QWidget):
    """Borderless window body: torn dark paper with dried blood and fog.

    Everything outside the torn edge is transparent, so the window has no frame.
    """

    EDGE = 10  # px of transparent margin the torn edge can bite into

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        rng = random.Random(24)
        grain = QImage(160, 160, QImage.Format.Format_ARGB32)
        for y in range(160):
            for x in range(160):
                v = rng.randint(0, 255)
                grain.setPixelColor(x, y, QColor(v, v, v, rng.randint(0, 18)))
        self._grain = QPixmap.fromImage(grain)
        self._cache_size = None

    def _rebuild(self):
        w, h = self.width(), self.height()
        rect = QRectF(self.EDGE, self.EDGE, w - 2 * self.EDGE, h - 2 * self.EDGE)
        self._shape = rough_rect(rect, random.Random(7), self.EDGE, step=9)
        self._splatter = blood_splatter(w, h)
        self._cache_size = (w, h)

    def paintEvent(self, _):
        if self._cache_size != (self.width(), self.height()):
            self._rebuild()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setClipPath(self._shape)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#170b0b"))
        g.setColorAt(0.5, BG)
        g.setColorAt(1, QColor("#100707"))
        p.fillRect(self.rect(), g)
        p.drawPixmap(0, 0, self._splatter)
        fog = QLinearGradient(0, h * 0.55, 0, h)
        fog.setColorAt(0, QColor(180, 170, 165, 0))
        fog.setColorAt(1, QColor(180, 170, 165, 20))
        p.fillRect(self.rect(), fog)
        p.drawTiledPixmap(self.rect(), self._grain)
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vig.setColorAt(0.5, QColor(0, 0, 0, 0))
        vig.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(self.rect(), vig)


class SplatterPanel(QWidget):
    """Smeared blood behind a block of text, fading out to the right (no border)."""

    def __init__(self, seed: int = 3, parent=None):
        super().__init__(parent)
        self._seed = seed
        self._cache = None

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if self._cache is None or self._cache.size() != self.size():
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            rng = random.Random(self._seed)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            smear = QLinearGradient(0, 0, w, 0)
            smear.setColorAt(0, QColor(150, 16, 16, 205))
            smear.setColorAt(0.6, QColor(120, 12, 12, 150))
            smear.setColorAt(1, QColor(90, 8, 8, 0))
            p.fillPath(rough_rect(QRectF(0, 2, w, h - 4), rng, 6, step=6), smear)
            # Brush streaks across the smear
            for _ in range(14):
                y = rng.uniform(4, h - 4)
                p.fillRect(QRectF(rng.uniform(0, w * 0.2), y, rng.uniform(w * 0.3, w * 0.8), rng.uniform(1, 2.5)),
                           QColor(60, 0, 0, rng.randint(30, 70)))
            p.end()
            self._cache = QPixmap.fromImage(img)
        QPainter(self).drawPixmap(0, 0, self._cache)


class BrushButton(QAbstractButton):
    """Button painted as a red brush stroke with torn ends, no border."""

    def __init__(self, text: str = "", primary: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self._primary = primary
        self._hover = False
        self._seed = random.randint(0, 10_000)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 30, 48 if self._primary else 32)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def changeEvent(self, e):
        super().changeEvent(e)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rng = random.Random(self._seed)
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        stroke = rough_rect(rect, rng, 5 if self._primary else 4, step=5)
        on = self.isEnabled()
        lit = on and (self._hover or self.isDown() or self.isChecked())
        g = QLinearGradient(0, 0, self.width(), 0)
        if not on:
            g.setColorAt(0, QColor(45, 34, 34, 200))
            g.setColorAt(1, QColor(35, 26, 26, 150))
        elif self._primary:
            g.setColorAt(0, QColor("#d42020" if lit else "#b01818"))
            g.setColorAt(1, QColor("#7a0e0e" if lit else "#5e0b0b"))
        else:
            g.setColorAt(0, QColor(150, 18, 18, 230) if lit else QColor(70, 14, 14, 210))
            g.setColorAt(1, QColor(100, 12, 12, 200) if lit else QColor(42, 10, 10, 170))
        p.fillPath(stroke, g)
        # Bristle streaks
        for _ in range(8 if self._primary else 5):
            y = rng.uniform(rect.top() + 3, rect.bottom() - 3)
            p.fillRect(QRectF(rng.uniform(0, self.width() * 0.3), y,
                              rng.uniform(self.width() * 0.3, self.width() * 0.7), 1),
                       QColor(0, 0, 0, 45) if on else QColor(0, 0, 0, 25))
        if lit and not self._primary:
            glow = QRadialGradient(rect.center(), self.width() * 0.6)
            glow.setColorAt(0, QColor(255, 59, 48, 45))
            glow.setColorAt(1, QColor(255, 59, 48, 0))
            p.fillPath(stroke, glow)
        p.setFont(heading_font(19 if self._primary else 13, QFont.Weight.DemiBold if self._primary else QFont.Weight.Normal,
                               3 if self._primary else 1.2))
        p.setPen(TEXT if on else QColor("#5a504c"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class WindowButton(QAbstractButton):
    """Minimize / close glyph for the frameless window."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind  # "min" or "close"
        self._hover = False
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Minimize" if kind == "min" else "Close to tray")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self._hover:
            glow = QRadialGradient(c, 15)
            glow.setColorAt(0, QColor(196, 30, 30, 170 if self._kind == "close" else 110))
            glow.setColorAt(1, QColor(196, 30, 30, 0))
            p.fillRect(self.rect(), glow)
        p.setPen(QPen(TEXT if self._hover else MUTED, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self._kind == "min":
            p.drawLine(QPointF(c.x() - 6, c.y() + 4), QPointF(c.x() + 6, c.y() + 4))
        else:
            p.drawLine(QPointF(c.x() - 6, c.y() - 6), QPointF(c.x() + 6, c.y() + 6))
            p.drawLine(QPointF(c.x() + 6, c.y() - 6), QPointF(c.x() - 6, c.y() + 6))
