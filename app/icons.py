"""Vector icons drawn with QPainter.

Everything is defined in a 24x24 space and scaled into the target rect, so icons
stay crisp at any size and can be tinted by the active skin. A skin may override
any icon with its own image file (see Skin.icon_pixmap).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

UNIT = 24.0


def _play() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(8.5, 5.5)
    path.lineTo(18.5, 12.0)
    path.lineTo(8.5, 18.5)
    path.closeSubpath()
    return path


def _pause() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(8.0, 5.5, 3.2, 13.0), 1.2, 1.2)
    path.addRoundedRect(QRectF(12.8, 5.5, 3.2, 13.0), 1.2, 1.2)
    return path


def _next() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(6.5, 5.5)
    path.lineTo(15.0, 12.0)
    path.lineTo(6.5, 18.5)
    path.closeSubpath()
    path.addRoundedRect(QRectF(15.8, 5.5, 2.6, 13.0), 1.1, 1.1)
    return path


def _prev() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(17.5, 5.5)
    path.lineTo(9.0, 12.0)
    path.lineTo(17.5, 18.5)
    path.closeSubpath()
    path.addRoundedRect(QRectF(5.6, 5.5, 2.6, 13.0), 1.1, 1.1)
    return path


def _stop() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(6.5, 6.5, 11.0, 11.0), 1.6, 1.6)
    return path


def _gear() -> QPainterPath:
    path = QPainterPath()
    center = QPointF(12.0, 12.0)
    teeth = 8
    r_out, r_in = 10.0, 7.4
    step = math.pi / teeth
    for i in range(teeth * 2):
        radius = r_out if i % 2 == 0 else r_in
        angle = i * step - math.pi / 2
        point = QPointF(center.x() + radius * math.cos(angle),
                        center.y() + radius * math.sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(center, 3.4, 3.4)
    return path.subtracted(hole)


def _minimize() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(6.0, 11.0, 12.0, 2.2), 1.1, 1.1)
    return path


def _close() -> QPainterPath:
    path = QPainterPath()
    stroke = QPainterPath()
    stroke.moveTo(7.0, 7.0)
    stroke.lineTo(17.0, 17.0)
    stroke.moveTo(17.0, 7.0)
    stroke.lineTo(7.0, 17.0)
    pen = QPen()
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    from PySide6.QtGui import QPainterPathStroker

    stroker = QPainterPathStroker(pen)
    path.addPath(stroker.createStroke(stroke))
    return path


def _note() -> QPainterPath:
    path = QPainterPath()
    # Winding (not the QPainterPath default of odd-even) so the overlap between
    # the head and the stem fills solid instead of punching a crescent hole.
    path.setFillRule(Qt.FillRule.WindingFill)
    path.addEllipse(QPointF(9.0, 17.0), 3.4, 2.8)
    path.addRoundedRect(QRectF(11.2, 5.0, 1.9, 12.0), 0.9, 0.9)
    path.moveTo(11.2, 5.4)
    path.lineTo(18.5, 3.2)
    path.lineTo(18.5, 7.0)
    path.lineTo(11.2, 9.2)
    path.closeSubpath()
    return path


def _pin() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(9.0, 3.5, 6.0, 9.0), 1.5, 1.5)
    path.addRoundedRect(QRectF(6.5, 12.0, 11.0, 2.2), 1.1, 1.1)
    path.addRoundedRect(QRectF(11.2, 14.0, 1.6, 6.5), 0.8, 0.8)
    return path


_BUILDERS = {
    "play": _play,
    "pause": _pause,
    "next": _next,
    "prev": _prev,
    "stop": _stop,
    "gear": _gear,
    "minimize": _minimize,
    "close": _close,
    "note": _note,
    "pin": _pin,
}

_CACHE: dict[str, QPainterPath] = {}


def icon_path(name: str) -> QPainterPath | None:
    if name not in _CACHE:
        builder = _BUILDERS.get(name)
        if builder is None:
            return None
        _CACHE[name] = builder()
    return _CACHE[name]


def paint_icon(painter: QPainter, name: str, rect: QRectF, color: QColor,
               scale: float = 1.0) -> None:
    """Draw icon `name` centred in `rect`, tinted with `color`."""
    path = icon_path(name)
    if path is None:
        return
    side = min(rect.width(), rect.height()) * scale
    factor = side / UNIT
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.center().x() - side / 2.0, rect.center().y() - side / 2.0)
    painter.scale(factor, factor)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)
    painter.restore()


def _hue_shifted(color: QColor, degrees: float) -> QColor:
    """`color` rotated round the hue wheel, kept saturated and bright enough to glow."""
    hue, sat, val, _ = color.getHsvF()
    if hue < 0:  # achromatic accent (grey/white): borrow the default blue's hue
        hue = 0.63
    return QColor.fromHsvF((hue + degrees / 360.0) % 1.0, max(sat, 0.65), max(val, 0.9), 1.0)


def _sound_wave(rect: QRectF) -> QPainterPath:
    """Vertical bars of a sound wave, centred in `rect`. Fewer, wider bars when tiny."""
    side = min(rect.width(), rect.height())
    if side < 24:
        heights, width, gap = (0.36, 0.62, 0.36), 0.14, 0.08
    else:
        heights, width, gap = (0.22, 0.42, 0.6, 0.42, 0.22), 0.085, 0.045
    width *= side
    gap *= side
    x = rect.center().x() - (len(heights) * width + (len(heights) - 1) * gap) / 2
    path = QPainterPath()
    for height in heights:
        bar = side * height
        path.addRoundedRect(QRectF(x, rect.center().y() - bar / 2, width, bar),
                            width / 2, width / 2)
        x += width + gap
    return path


def paint_app_icon(painter: QPainter, rect: QRectF, accent: QColor) -> None:
    """Draw the full app icon: a rounded square in a diagonal gradient that sweeps
    the hue wheel either side of `accent`, lit from the top-left, with a white
    sound wave on top.

    Shared by the live tray/window icon (tinted with the active skin's accent)
    and `tools/generate_icon.py` (fixed accent, baked into the static assets).
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    side = min(rect.width(), rect.height())
    radius = side * 0.26

    fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
    fill.setColorAt(0.0, _hue_shifted(accent, -45))
    fill.setColorAt(0.5, _hue_shifted(accent, 0))
    fill.setColorAt(1.0, _hue_shifted(accent, 75))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, radius, radius)

    glow = QRadialGradient(QPointF(rect.left() + side * 0.25, rect.top() + side * 0.15),
                           side * 0.75)
    glow.setColorAt(0.0, QColor(255, 255, 255, 90))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(glow)
    painter.drawRoundedRect(rect, radius, radius)

    shade = QLinearGradient(QPointF(rect.left(), rect.top() + side * 0.55), rect.bottomLeft())
    shade.setColorAt(0.0, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, QColor(0, 0, 0, 50))
    painter.setBrush(shade)
    painter.drawRoundedRect(rect, radius, radius)

    wave = _sound_wave(rect)
    painter.setBrush(QColor(0, 0, 0, 60))
    painter.drawPath(wave.translated(0, side * 0.025))
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(wave)
    painter.restore()
