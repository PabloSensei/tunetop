"""A short-lived "now playing" card shown when the track changes.

Painted with the active skin's colours and fonts so it looks like a sibling of
the widget. It never takes focus, fades in and out, and a click on it brings
the widget up instead.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import icons
from .media import PlayerState, friendly_source_name
from .skins import Skin

TOAST_SIZE = (300, 76)
TOAST_MARGIN = 16  # from the screen edge or the widget
SHOW_FOR_MS = 4000
FADE_MS = 220


class TrackToast(QWidget):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(*TOAST_SIZE)
        self._skin: Skin | None = None
        self._state = PlayerState()
        self._art: QPixmap | None = None
        self._art_key = ""
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.finished.connect(self._on_fade_done)

    def popup(self, state: PlayerState, skin: Skin, anchor: QRect | None) -> None:
        """Show `state`; next to `anchor` (the widget's frame) if given, else in a corner."""
        self._skin = skin
        self.update_state(state)
        self.move(self._position(anchor))
        if not self.isVisible():
            self._fade.stop()
            self.setWindowOpacity(0.0)
            self.show()
        if self._fade.endValue() != 1.0:  # appearing, or caught while fading out
            self._fade.stop()
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(1.0)
            self._fade.start()
        self._hide_timer.start(SHOW_FOR_MS)

    def update_state(self, state: PlayerState) -> None:
        """Late-arriving artwork for the track already on show."""
        self._state = state
        if state.art_key != self._art_key:
            self._art_key = state.art_key
            self._art = None
            if state.art:
                pixmap = QPixmap()
                if pixmap.loadFromData(state.art):
                    self._art = pixmap
        self.update()

    def _position(self, anchor: QRect | None) -> QPoint:
        width, height = TOAST_SIZE
        screen = None
        if anchor is not None:
            screen = QApplication.screenAt(anchor.center())
        screen = screen or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        if anchor is None:
            return QPoint(area.right() - width - TOAST_MARGIN, area.bottom() - height - TOAST_MARGIN)
        x = max(area.left(), min(anchor.center().x() - width // 2, area.right() - width))
        above = anchor.top() - height - 4
        if above >= area.top():
            return QPoint(x, above)
        return QPoint(x, min(anchor.bottom() + 4, area.bottom() - height))

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_done(self) -> None:
        if self._fade.endValue() == 0.0:
            self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._hide_timer.stop()
        self.hide()
        self.clicked.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        skin = self._skin
        if skin is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = float(skin.metric("radius"))
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0.0, skin.color("bg"))
        gradient.setColorAt(1.0, skin.color("bg2"))
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        painter.fillPath(path, gradient)
        border = skin.color("border")
        if border.alpha():
            painter.setPen(border)
            painter.drawPath(path)

        pad = 10.0
        art = QRectF(pad, pad, card.height() - 2 * pad, card.height() - 2 * pad)
        art_path = QPainterPath()
        art_radius = float(skin.metric("art_radius"))
        art_path.addRoundedRect(art, art_radius, art_radius)
        painter.save()
        painter.setClipPath(art_path)
        painter.fillPath(art_path, skin.color("art_placeholder"))
        if self._art is not None and not self._art.isNull():
            scaled = self._art.scaled(int(art.width()), int(art.height()),
                                      Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(art, scaled, QRectF((scaled.width() - art.width()) / 2,
                                                   (scaled.height() - art.height()) / 2,
                                                   art.width(), art.height()))
        else:
            icons.paint_icon(painter, "note", art, skin.color("icon_disabled"), 0.5)
        painter.restore()

        state = self._state
        left = art.right() + pad
        width = card.right() - pad - left
        lines = (
            (state.title or "—", "title", "title"),
            (state.artist, "artist", "artist"),
            (friendly_source_name(state.app_id), "time", "time"),
        )
        y = pad
        row = (card.height() - 2 * pad) / 3
        for text, font_key, color_key in lines:
            painter.setFont(skin.font(font_key))
            painter.setPen(skin.color(color_key))
            metrics = QFontMetricsF(painter.font())
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width))
            painter.drawText(QRectF(left, y, width, row),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)
            y += row
        painter.end()
