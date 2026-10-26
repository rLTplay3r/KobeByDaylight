"""Recognizes the in-match HUD on a screenshot.

In a trial both killer and survivors see their 4 perks as diamonds arranged in a
rhombus in the bottom-right corner. In the lobby and on the scoreboard perks are
shown in a row, so the rhombus means "in match". We look for the shape and the
layout, not for specific perk icons, so any loadout, role, resolution, aspect
ratio and HUD scale works.
"""

import math

import cv2
import numpy as np

# HUD is anchored bottom-right and scales with the screen height
ROI_SIZE = 0.42      # region side, as a fraction of the screen height
NORM = 320           # the region is resized to NORM x NORM before analysis


def hud_region(width: int, height: int) -> tuple[int, int, int, int]:
    side = int(height * ROI_SIZE)
    side = min(side, width, height)
    return width - side, height - side, side, side


def hud_regions(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Regions where the perks can be; on ultrawide the HUD may stay inside 16:9."""
    regions = [hud_region(width, height)]
    if width / height > 1.85:
        right = int((width + height * 16 / 9) / 2)
        x, y, w, h = hud_region(right, height)
        regions.append((x, y, w, h))
    return regions


def _template(r: int, gap: float) -> np.ndarray:
    """Outline of 4 diamonds (half-diagonal r) laid out as a rhombus."""
    g = gap * r
    half = int(math.ceil(g + r)) + 2
    t = np.zeros((2 * half + 1, 2 * half + 1), np.float32)
    for cx, cy in ((0, -g), (-g, 0), (g, 0), (0, g)):
        corners = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        for k in range(4):
            (x1, y1), (x2, y2) = corners[k], corners[(k + 1) % 4]
            steps = int(max(abs(x2 - x1), abs(y2 - y1)))
            for i in range(steps):
                t[int(round(y1 + (y2 - y1) * i / steps)) + half, int(round(x1 + (x2 - x1) * i / steps)) + half] = 1
    return t


# Diamond half-diagonals to try (pixels in the normalized region) and spacing ratios
_TEMPLATES = [(r, gap, _template(r, gap)) for r in range(14, 52, 2) for gap in (1.25, 1.34, 1.43)]


def _diagonal_edge_distance(gray: np.ndarray) -> np.ndarray:
    """Distance to the nearest edge that runs at about 45 degrees."""
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 40, 120)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1)
    angle = np.degrees(np.arctan2(gy, gx)) % 90
    diagonal = (edges > 0) & (np.abs(angle - 45) < 18)
    dist = cv2.distanceTransform((~diagonal).astype(np.uint8), cv2.DIST_L2, 3)
    return np.minimum(dist, 8.0)


def perk_rhombus_score(roi_bgr: np.ndarray) -> float:
    """How well a perk rhombus lines up with the diagonal edges, 0..1.

    Raw hit rate is corrected for how busy the area is, so textured backgrounds
    full of edges don't look like a HUD.
    """
    roi = cv2.resize(np.ascontiguousarray(roi_bgr), (NORM, NORM), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    near = (_diagonal_edge_distance(gray) <= 1.5).astype(np.float32)
    best = 0.0
    for _, _, t in _TEMPLATES:
        size = t.shape[0]
        if size > NORM:
            continue
        hits = cv2.matchTemplate(near, t, cv2.TM_CCORR) / float(t.sum())
        density = cv2.boxFilter(near, -1, (size, size), anchor=(0, 0), normalize=True,
                                borderType=cv2.BORDER_CONSTANT)[: hits.shape[0], : hits.shape[1]]
        score = (hits - density) / np.maximum(1.0 - density, 0.05)
        best = max(best, float(score.max()))
    return best


# -- flashlight blind --------------------------------------------------------------
# A successful blind bursts into a big white-yellow flash where the player aims,
# i.e. the middle of the screen. Measured on footage: 50-62% of this region turns
# white on a blind, the flashlight beam alone stays under ~11%.
CENTER = (0.3, 0.25, 0.4, 0.5)  # x, y, width, height as fractions of the game window


def center_region(width: int, height: int) -> tuple[int, int, int, int]:
    fx, fy, fw, fh = CENTER
    return int(width * fx), int(height * fy), int(width * fw), int(height * fh)


def white_fraction(img_bgr: np.ndarray) -> float:
    small = cv2.resize(np.ascontiguousarray(img_bgr), (128, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 2] > 235) & (hsv[..., 1] < 90)).mean())
