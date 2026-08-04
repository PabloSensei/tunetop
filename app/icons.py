"""Vector icons drawn with QPainter.

Everything is defined in a 24x24 space and scaled into the target rect, so icons
stay crisp at any size and can be tinted by the active skin. A skin may override
any icon with its own image file (see Skin.icon_pixmap).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

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
