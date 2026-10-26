"""Transparent, click-through, always-on-top window that draws the timer, Kobe and effects."""

import random
import time

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QMovie, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QWidget

from . import paths

FRAME_MS = 16
SLIDE_IN = 0.35
SLIDE_OUT = 0.35
BUBBLE_DELAY = 0.2
KICK_LENGTH = 0.14  # seconds the timer stays knocked out of place after a beat
PREVIEW_TEXT = "Man, what can I say?"
PREVIEW_BEAT = 0.42  # fake beat so the preview shows the timer shake
# Dark text area inside speechbuble.png, as fractions of the image size
BUBBLE_TEXT_RECT = (0.23, 0.37, 0.60, 0.30)


BUBBLE_TIP_Y = 0.49  # height of the bubble's left tip, as a fraction of the image
POV_SIZE = 0.3        # killer POV inset: a 16:9 picture 0.3 of the screen height, top-right
POV_LABEL = "KILLER POV \u2192"
HIDE_DURATION = 2.6
DANCE_HEIGHT = 0.8    # dancing Kobe, as a fraction of the screen height
FADE = 0.3


class Sprite:
    """A Kobe cutout plus where his head is, found from the transparency.

    Positions are fractions of the image size, so the bubble lands next to the
    head for any sprite dropped into kobe-sprites/.
    """

    def __init__(self, path):
        self.pixmap = QPixmap(str(path))
        self.head_right, self.head_y = 0.65, 0.15
        img = self.pixmap.toImage().scaledToWidth(120).convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        opaque = [[img.pixelColor(x, y).alpha() > 128 for x in range(w)] for y in range(h)]
        top = next((y for y in range(h) if sum(opaque[y]) >= 3), None)
        if top is None:
            return
        # The top ~22% of the figure is the head; shoulders start below that
        band = range(top, min(h, top + int(h * 0.22)))
        xs = [x for y in band for x in range(w) if opaque[y][x]]
        self.head_right = max(xs) / w
        self.head_y = (top + h * 0.13) / h


def format_elapsed(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("DBD Kobe Overlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._sprites = [s for s in map(Sprite, paths.kobe_sprites()) if not s.pixmap.isNull()]
        self._sprite_px: dict[int, QPixmap] = {}
        self._last_sprite = -1
        self._bubble = QPixmap(str(paths.BUBBLE_IMAGE))
        self._scaled_for: tuple[int, int] | None = None

        self.timer_visible = True
        # Size multipliers per element, 1.0 = default
        self.scales = {"timer": 1.0, "kobe": 1.0, "bubble": 1.0, "dance": 1.0, "pov": 1.0}
        self._preview_start: float | None = None
        self._preview_sprite = 0
        self._match_start: float | None = None
        self._popup: tuple[float, float, str, int] | None = None  # start, duration, text, sprite
        self._kick: tuple[float, float, float] | None = None  # start, dx, dy (fractions of height)

        # Killer POV when blinded: the GIF plays in an inset like in the edit
        self._pov = QMovie(str(paths.KILLER_POV))
        self._pov.setCacheMode(QMovie.CacheMode.CacheAll)
        self._pov_shown: tuple[float, float] | None = None  # start, duration
        # Kobe going "shh" while hiding in a locker
        self._hiding = QPixmap(str(paths.KOBE_HIDING))
        self._hide_start: float | None = None
        # Dancing Kobe: frames arrive from DancePlayer
        self._dance_img: QImage | None = None
        self._dance_end: float | None = None
        self.dance_preview: QImage | None = None

        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self.update)

    # -- public API ---------------------------------------------------------

    def start_match(self, start_time: float, game_center: tuple[int, int] | None = None):
        self._match_start = start_time
        self._cover_screen(game_center)
        self.show()
        self.raise_()
        self._frame.start()

    def end_match(self):
        self._match_start = None
        self._popup = None
        self._pov_shown = None
        self._hide_start = None
        self._dance_img = None
        if self._preview_start is None:
            self._frame.stop()
            self.hide()

    def set_preview(self, on: bool, game_center: tuple[int, int] | None = None):
        """Scale mode: shows every element, held still, so sizes can be tuned live."""
        if on:
            if self._preview_start is None and self._sprites:
                self._preview_sprite = (self._preview_sprite + 1) % len(self._sprites)
            self._preview_start = time.monotonic()
            if self._match_start is None:
                self._cover_screen(game_center)
            self.show()
            self.raise_()
            self._frame.start()
        else:
            self._preview_start = None
            if self._match_start is None:
                self._frame.stop()
                self.hide()

    def set_scale(self, element: str, value: float):
        self.scales[element] = value
        self.update()

    def show_kobe(self, text: str, duration: float) -> bool:
        """Pops up a random Kobe sprite with the text; False when there are no sprites."""
        if not self._sprites:
            return False
        choices = [i for i in range(len(self._sprites)) if i != self._last_sprite] or [0]
        index = random.choice(choices)
        self._last_sprite = index
        self._popup = (time.monotonic(), duration, text, index)
        return True

    def kick(self):
        """Knock the timer out of place for a moment, as on the beat in the video."""
        dx = random.choice((-1, 1)) * random.uniform(0.006, 0.014)
        dy = random.uniform(-0.006, 0.004)
        self._kick = (time.monotonic(), dx, dy)

    def kobe_active(self) -> bool:
        return self._popup is not None

    def show_killer_pov(self, duration: float = 3.5) -> bool:
        if not self._pov.isValid():
            return False
        self._pov.stop()
        self._pov.jumpToFrame(0)
        self._pov.start()
        self._pov_shown = (time.monotonic(), duration)
        return True

    def show_hiding(self) -> bool:
        if self._hiding.isNull():
            return False
        self._hide_start = time.monotonic()
        return True

    def dance_height(self) -> int:
        """Pixel height the dance frames should be decoded at."""
        return int(self.height() * DANCE_HEIGHT * self.scales["dance"] * self.devicePixelRatioF())

    def set_dance_frame(self, img: QImage):
        img.setDevicePixelRatio(self.devicePixelRatioF())
        self._dance_img = img
        self._dance_end = None

    def dance_finished(self):
        self._dance_end = time.monotonic()  # fade the last frame out

    def dance_active(self) -> bool:
        return self._dance_img is not None

    # -- painting -----------------------------------------------------------

    def _cover_screen(self, game_center: tuple[int, int] | None):
        """Covers the monitor the game is on (primary if unknown)."""
        screen = QGuiApplication.primaryScreen()
        if game_center:
            gx, gy = game_center
            for s in QGuiApplication.screens():
                g, dpr = s.geometry(), s.devicePixelRatio()
                # Screen origins are native pixels, sizes are scaled by the DPI factor
                if g.x() <= gx < g.x() + g.width() * dpr and g.y() <= gy < g.y() + g.height() * dpr:
                    screen = s
                    break
        if screen:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

    def _ensure_scaled(self):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.scales["kobe"], self.scales["bubble"])
        if self._scaled_for == key:
            return
        # Everything is sized from the screen height so any resolution or aspect
        # ratio looks the same; pixmaps are rendered at native pixels for HiDPI.
        h = self.height()
        smooth = Qt.TransformationMode.SmoothTransformation
        if not self._hiding.isNull():
            self._hiding_px = self._hiding.scaledToHeight(int(h * 0.62 * self.scales["kobe"] * dpr), smooth)
            self._hiding_px.setDevicePixelRatio(dpr)
        self._sprite_px.clear()
        for i, sprite in enumerate(self._sprites):
            # 0.6 of the screen height at 100%, the size Kobe has in the video
            px = sprite.pixmap.scaledToHeight(int(h * 0.6 * self.scales["kobe"] * dpr), smooth)
            px.setDevicePixelRatio(dpr)
            self._sprite_px[i] = px
        self._bubble_px = self._bubble.scaledToWidth(int(h * 0.62 * self.scales["bubble"] * dpr), smooth)
        self._bubble_px.setDevicePixelRatio(dpr)
        self._scaled_for = key

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        preview = self._preview_start is not None
        if self._match_start is None and not preview:
            return
        self._ensure_scaled()
        now = time.monotonic()
        start = self._match_start if self._match_start is not None else self._preview_start
        if preview and (self._kick is None or now - self._kick[0] > PREVIEW_BEAT):
            self.kick()
        if self.timer_visible or preview:
            self._paint_timer(p, now - start, now)
        if preview:
            # Every element shown and held still, so the sizes can be judged
            if self.dance_preview is not None:
                self.dance_preview.setDevicePixelRatio(self.devicePixelRatioF())
                self._paint_dance(p, self.dance_preview, 1.0)
            if self._sprites:
                self._paint_kobe(p, SLIDE_IN + 0.5, 1e9, PREVIEW_TEXT, self._preview_sprite)
            if not self._hiding.isNull():
                self._paint_hiding(p, SLIDE_IN + 0.5)
            if self._pov.isValid():
                if self._pov.state() != QMovie.MovieState.Running:
                    self._pov.start()
                self._paint_pov(p, 1.0)
            self._paint_preview_banner(p)
            return
        self._paint_effects(p, now)
        if self._popup:
            start, duration, text, index = self._popup
            t = now - start
            if t > duration:
                self._popup = None
            else:
                self._paint_kobe(p, t, duration, text, index)

    # -- effects ------------------------------------------------------------

    def _paint_effects(self, p: QPainter, now: float):
        if self._dance_img is not None:
            alpha = 1.0
            if self._dance_end is not None:
                alpha = 1 - (now - self._dance_end) / FADE
                if alpha <= 0:
                    self._dance_img = None
            if self._dance_img is not None:
                self._paint_dance(p, self._dance_img, alpha)
        if self._hide_start is not None:
            t = now - self._hide_start
            if t > HIDE_DURATION:
                self._hide_start = None
            else:
                self._paint_hiding(p, t)
        if self._pov_shown is not None:
            start, duration = self._pov_shown
            t = now - start
            if t > duration:
                self._pov_shown = None
                self._pov.stop()
            else:
                # Quick fade in, slower fade out like the edit
                alpha = min(1.0, t / 0.15, (duration - t) / 0.4)
                self._paint_pov(p, alpha)

    def _paint_pov(self, p: QPainter, alpha: float):
        h, w = self.height(), self.width()
        ph = h * POV_SIZE * self.scales["pov"]
        pw = ph * 16 / 9
        rect = QRectF(w - pw, 0, pw, ph)
        p.save()
        p.setOpacity(max(0.0, alpha))
        p.drawPixmap(rect, self._pov.currentPixmap(), QRectF(self._pov.currentPixmap().rect()))
        # "KILLER POV ->" in yellow with a thick purple outline, left of the inset
        font = QFont()
        font.setFamilies(["Oswald", "Impact", "Arial Black", "DejaVu Sans"])
        font.setWeight(QFont.Weight.Bold)
        font.setPixelSize(max(12, int(ph * 0.19)))
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(POV_LABEL)
        path = QPainterPath()
        path.addText(rect.left() - tw - ph * 0.12, ph * 0.45 + fm.ascent() / 2 - fm.descent() / 2, font, POV_LABEL)
        p.setPen(QPen(QColor("#5b1fa8"), max(2.0, ph * 0.035), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.fillPath(path, QColor("#ffe81a"))
        p.restore()

    def _paint_hiding(self, p: QPainter, t: float):
        h, w = self.height(), self.width()
        px = self._hiding_px
        size = px.deviceIndependentSize()
        if t < SLIDE_IN:
            shown = QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(t / SLIDE_IN)
        elif t > HIDE_DURATION - SLIDE_OUT:
            shown = 1 - QEasingCurve(QEasingCurve.Type.InCubic).valueForProgress(
                (t - (HIDE_DURATION - SLIDE_OUT)) / SLIDE_OUT)
        else:
            shown = 1.0
        # Bottom-right, rising from the bottom edge like in the edit
        x = w - size.width() - h * 0.12
        p.drawPixmap(int(x), int(h - size.height() * shown), px)

    def _paint_dance(self, p: QPainter, img: QImage, alpha: float):
        h = self.height()
        size = img.deviceIndependentSize()
        # Centre-left, feet on the bottom edge; height-based so ultrawide matches 16:9
        x = h * 0.85 - size.width() / 2
        p.save()
        p.setOpacity(max(0.0, alpha))
        p.drawImage(int(x), int(h - size.height()), img)
        p.restore()

    def _paint_timer(self, p: QPainter, elapsed: float, now: float):
        # Thin white digits on a dark translucent box flush with the top-left corner
        h = self.height()
        font = QFont()
        font.setFamilies(["Bahnschrift Light", "Segoe UI Light", "Noto Sans", "DejaVu Sans"])
        font.setWeight(QFont.Weight.Light)
        font.setPixelSize(max(12, int(h * 0.075 * self.scales["timer"])))
        font.setStyleHint(QFont.StyleHint.SansSerif)
        p.setFont(font)
        fm = QFontMetricsF(font)
        text = format_elapsed(elapsed)
        # Fixed-width box so it does not wobble as digits change
        text_w = fm.horizontalAdvance("00:00.00")
        pad_x, pad_y = h * 0.012, h * 0.004
        box = QRectF(0, 0, text_w + pad_x * 2, fm.height() + pad_y * 2)

        # On a beat the whole timer jerks sideways, smears and splits into RGB
        strength, dx, dy = 0.0, 0.0, 0.0
        if self._kick:
            age = now - self._kick[0]
            if age < KICK_LENGTH:
                strength = 1 - age / KICK_LENGTH
                dx, dy = self._kick[1] * h * strength, self._kick[2] * h * strength
            else:
                self._kick = None
        p.save()
        p.translate(dx, dy)
        p.fillRect(box.adjusted(-abs(dx), 0, abs(dx), 0), QColor(0, 0, 0, 150))
        text_rect = box.adjusted(pad_x, 0, 0, 0)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if strength > 0:
            split = h * 0.006 * strength
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for color, off in ((QColor(255, 0, 40, 170), -split), (QColor(0, 120, 255, 170), split)):
                p.setPen(color)
                p.drawText(text_rect.translated(off, 0), align, text)
            # Motion smear: fading copies trailing the jump
            for i in (1, 2):
                p.setPen(QColor(255, 255, 255, int(70 * strength / i)))
                p.drawText(text_rect.translated(-dx * 0.35 * i, 0), align, text)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(text_rect, align, text)
        p.restore()

    def _paint_kobe(self, p: QPainter, t: float, duration: float, text: str, index: int):
        h = self.height()
        sprite, kobe, bubble = self._sprites[index], self._sprite_px[index], self._bubble_px
        kobe_w, kobe_h = kobe.deviceIndependentSize().width(), kobe.deviceIndependentSize().height()
        bubble_w, bubble_h = bubble.deviceIndependentSize().width(), bubble.deviceIndependentSize().height()

        # Kobe rises from the bottom edge, holds, then sinks back down
        if t < SLIDE_IN:
            shown = QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(t / SLIDE_IN)
        elif t > duration - SLIDE_OUT:
            shown = 1 - QEasingCurve(QEasingCurve.Type.InCubic).valueForProgress((t - (duration - SLIDE_OUT)) / SLIDE_OUT)
        else:
            shown = 1.0
        kx = h * 0.11  # near the left edge like in the video; height-based so ultrawide matches
        ky = h - kobe_h * shown
        p.drawPixmap(int(kx), int(ky), kobe)

        # Speech bubble pops out of the side of his head, tip pointing at him
        bt = t - BUBBLE_DELAY
        if bt <= 0 or t > duration - SLIDE_OUT * 0.5:
            return
        scale = QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(min(1.0, bt / 0.25))
        tip_x = kx + kobe_w * sprite.head_right + h * 0.01
        tip_y = h - kobe_h + kobe_h * sprite.head_y
        p.save()
        p.translate(tip_x, tip_y)
        p.scale(scale, scale)
        p.translate(0, -bubble_h * BUBBLE_TIP_Y)
        p.drawPixmap(0, 0, bubble)
        fx, fy, fw, fh = BUBBLE_TEXT_RECT
        rect = QRectF(bubble_w * fx, bubble_h * fy, bubble_w * fw, bubble_h * fh)
        self._draw_fitted_text(p, rect, text)
        p.restore()

    def _paint_preview_banner(self, p: QPainter):
        h = self.height()
        font = QFont()
        font.setFamilies(["Oswald", "Noto Sans", "DejaVu Sans"])
        font.setPixelSize(max(12, int(h * 0.022)))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(font)
        text = "SCALE PREVIEW  -  ADJUST IN THE PANEL"
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(text) + h * 0.04
        box = QRectF((self.width() - w) / 2, h * 0.02, w, fm.height() + h * 0.016)
        p.fillRect(box, QColor(110, 12, 12, 200))
        p.setPen(QColor(255, 255, 255))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _draw_fitted_text(p: QPainter, rect: QRectF, text: str):
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        font = QFont()
        font.setFamilies(["Impact", "Arial Black", "Noto Sans", "DejaVu Sans"])
        font.setBold(True)
        size = int(rect.height() * 0.45)
        while size > 8:
            font.setPixelSize(size)
            bounds = QFontMetricsF(font).boundingRect(rect, int(flags), text)
            if bounds.width() <= rect.width() and bounds.height() <= rect.height():
                break
            size -= 1
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(rect, int(flags), text)
