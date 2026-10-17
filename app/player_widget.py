"""The always-on-top player widget.

Frameless, translucent, fully custom painted: the active skin controls sizes,
colours, fonts and the optional background image. Layout adapts to whatever card
size the skin declares.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from . import icons
from .config import Settings
from .i18n import tr
from .lyrics import line_at
from .media import REPEAT_NONE, REPEAT_TRACK, PlayerState, friendly_source_name
from .skins import Skin, load_skin

SNAP_DISTANCE = 18
LYRIC_LEAD = 0.3  # show a lyric line this much early; reading lags hearing
MIN_TIME_WIDTH = 72  # room "12:34 / 56:78" needs beside the button row
AMBIENT_FADE = 0.6  # seconds to blend the art-tinted background into the next track's


def ambient_colors(image: QImage, dark: bool) -> tuple[QColor, QColor, QColor] | None:
    """(top, bottom, accent) colours for a card tinted by `image`.

    Top and bottom are the averages of the image's upper and lower halves, pushed
    dark (or light, for light skins) and muted enough to keep text readable; the
    accent is the image's most vivid colour, for the progress bar.
    """
    if image.isNull():
        return None
    small = image.convertToFormat(QImage.Format.Format_RGB32).scaled(
        12, 12, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    halves = [[0, 0, 0, 0], [0, 0, 0, 0]]
    vivid, vivid_score = QColor(), -1.0
    for y in range(small.height()):
        half = halves[0 if y < small.height() / 2 else 1]
        for x in range(small.width()):
            color = small.pixelColor(x, y)
            half[0] += color.red()
            half[1] += color.green()
            half[2] += color.blue()
            half[3] += 1
            score = color.hsvSaturationF() * color.valueF()
            if score > vivid_score:
                vivid, vivid_score = color, score

    def tone(color: QColor, value: float, saturation: float) -> QColor:
        hue, sat, _, _ = color.getHsvF()
        return QColor.fromHsvF(max(hue, 0.0), min(sat, saturation), value)

    top, bottom = (QColor(r // n, g // n, b // n) for r, g, b, n in halves)
    if dark:
        top, bottom = tone(top, 0.34, 0.65), tone(bottom, 0.2, 0.65)
        accent = tone(vivid, 0.95, 0.75)
    else:
        top, bottom = tone(top, 0.97, 0.18), tone(bottom, 0.9, 0.22)
        accent = tone(vivid, 0.7, 0.8)
    if vivid_score < 0.08:  # a greyscale cover has no colour worth borrowing
        accent = QColor()
    return top, bottom, accent


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


@dataclass
class HitButton:
    name: str
    action: str
    rect: QRectF
    enabled: bool = True
    role: str = "transport"


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


class PlayerWidget(QWidget):
    command = Signal(str, object)  # action, value
    open_settings = Signal()
    open_menu = Signal(QPoint)
    hide_to_tray = Signal()
    quit_requested = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__(None)
        self.settings = settings
        self.skin: Skin = load_skin(settings.skin)
        self.state = PlayerState()

        self._buttons: list[HitButton] = []
        self._hover: HitButton | None = None
        self._hovered = False
        self._drag_offset: QPoint | None = None
        self._art_pixmap: QPixmap | None = None
        self._art_key = ""
        self._bg_pixmap: QPixmap | None = None
        self._scroll = 0.0
        self._scroll_hold = 0.0
        self._seeking = False
        self._seek_ratio = 0.0
        self._card = QRectF()
        self._progress_rect = QRectF()
        self._art_rect = QRectF()
        self._title_rect = QRectF()
        self._artist_rect = QRectF()
        self._time_rect = QRectF()
        self._title_overflows = False
        self._progress_color = QColor()
        self._ambient: tuple[QColor, QColor, QColor] | None = None  # current target
        self._ambient_from: tuple[QColor, QColor, QColor] | None = None
        self._ambient_since = 0.0
        self._lyrics_key: tuple | None = None
        self._lyrics: list = []
        self._lyric_index = -1
        self._osd_text = ""  # short-lived notice (volume level) shown in place of the time
        self._osd_until = 0.0
        self._flags: Qt.WindowType | None = None

        self.setWindowTitle("Tunetop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._apply_window_flags()

        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self.apply_skin(settings.skin)
        self.restore_position()

    # ------------------------------------------------------------ appearance

    def _apply_window_flags(self) -> bool:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if self.settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        # setWindowFlags recreates the native window, hiding it on the way; doing
        # that on every opacity slider tick made the widget flicker.
        changed = flags != self._flags
        if changed:
            self._flags = flags
            self.setWindowFlags(flags)
        self.setWindowOpacity(max(0.2, min(1.0, self.settings.opacity)))
        return changed

    def refresh_window_flags(self) -> None:
        visible = self.isVisible()
        if self._apply_window_flags() and visible:
            self.show()

    def apply_skin(self, skin_id: str) -> None:
        self.skin = load_skin(skin_id)
        self._bg_pixmap = self.skin.background_pixmap()
        self._art_key = ""
        self._art_pixmap = None
        self._set_ambient(None, fade=False)
        width, height = self._card_size()
        margin = self.skin.metric("shadow")
        self.setFixedSize(QSize(width + margin * 2, height + margin * 2))
        self._relayout()
        self.update()

    def set_lyrics(self, key: tuple, lyrics: list) -> None:
        self._lyrics_key = key
        self._lyrics = list(lyrics or [])
        self._lyric_index = -1
        self.update()

    def _current_lyric(self) -> tuple[int, str]:
        state = self.state
        if (not self.settings.show_lyrics or not self._lyrics or not state.has_track
                or self._lyrics_key != (state.app_id, state.title, state.artist)):
            return -1, ""
        position = self._seek_ratio * state.duration if self._seeking else state.live_position()
        return line_at(self._lyrics, position + LYRIC_LEAD)

    def show_osd(self, text: str, seconds: float = 1.2) -> None:
        self._osd_text = text
        self._osd_until = time.monotonic() + seconds
        self.update()

    def _osd(self) -> str:
        return self._osd_text if time.monotonic() < self._osd_until else ""

    def set_compact(self, compact: bool) -> None:
        self.settings.compact = compact
        self.settings.cover_mode = False
        self.apply_skin(self.skin.id)

    def set_cover_mode(self, cover: bool) -> None:
        self.settings.cover_mode = cover
        self.apply_skin(self.skin.id)

    def cycle_view(self) -> None:
        """Double click: full -> compact -> cover only -> full."""
        if self.settings.cover_mode:
            self.settings.cover_mode = False
            self.settings.compact = False
        elif self.settings.compact:
            self.settings.cover_mode = True
        else:
            self.settings.compact = True
        self.apply_skin(self.skin.id)

    def _cover(self) -> bool:
        return self.settings.cover_mode

    def _card_size(self) -> tuple[int, int]:
        if self._cover():
            side = max(64, min(400, self.skin.metric("cover_size")))
            return side, side
        return self.skin.size(self.settings.compact)

    # ------------------------------------------------------------- geometry

    def _relayout(self) -> None:
        margin = self.skin.metric("shadow")
        card_w, card_h = self._card_size()
        self._card = QRectF(margin, margin, card_w, card_h)
        if self._cover():
            self._relayout_cover()
            return

        pad = self.skin.metric("padding")
        gap = self.skin.metric("spacing")
        btn = self.skin.metric("button_size")
        btn_gap = self.skin.metric("button_gap")
        prog_h = self.skin.metric("progress_height")
        compact = self.settings.compact
        if compact:
            btn = min(btn, int(card_h - pad))

        content = self._card.adjusted(pad, pad, -pad, -pad)
        buttons: list[HitButton] = []

        # top-right chrome (settings / hide / quit), shown on hover
        chrome = min(15, max(11, int(btn * 0.55)))
        chrome_y = self._card.top() + (pad * 0.55 if not compact else (card_h - chrome) / 2)
        chrome_x = self._card.right() - pad * 0.6 - chrome
        for name, action in (("close", "quit"), ("minimize", "hide"), ("gear", "settings")):
            buttons.append(
                HitButton(name, action, QRectF(chrome_x, chrome_y, chrome, chrome), True, "chrome")
            )
            chrome_x -= chrome + 5
        chrome_left = chrome_x + chrome - 3  # leave a gap between text and chrome

        show_art = self.settings.show_album_art and not compact
        if show_art:
            art = min(self.skin.metric("art_size"), int(content.height()))
            self._art_rect = QRectF(content.left(), content.top() + (content.height() - art) / 2,
                                    art, art)
            text_left = self._art_rect.right() + gap
        else:
            self._art_rect = QRectF()
            text_left = content.left()

        text_w = content.right() - text_left

        if compact:
            row_y = content.top() + (content.height() - btn) / 2
            x = content.left()
            for name, action in (("prev", "prev_track"), ("play", "play_pause"),
                                 ("next", "next_track")):
                buttons.append(HitButton(name, action, QRectF(x, row_y, btn, btn)))
                x += btn + btn_gap
            self._title_rect = QRectF(x + 2, content.top(),
                                      max(0.0, chrome_left - x - 8), content.height())
            self._artist_rect = QRectF()
            self._time_rect = QRectF()
            self._progress_rect = QRectF(
                self._card.left(), self._card.bottom() - prog_h, self._card.width(), prog_h
            ) if self.settings.show_progress else QRectF()
        else:
            prog_gap = 4.0
            prog_block = (prog_h + prog_gap) if self.settings.show_progress else 0.0
            free = content.height() - btn - prog_block
            title_h = max(16.0, free * 0.55)
            artist_h = max(12.0, free - title_h)

            y = content.top()
            self._title_rect = QRectF(text_left, y,
                                      max(0.0, min(text_w, chrome_left - text_left)), title_h)
            y += title_h
            self._artist_rect = QRectF(text_left, y, text_w, artist_h)
            y += artist_h

            row_w = 3 * btn + 2 * btn_gap
            x = text_left
            for name, action in (("prev", "prev_track"), ("play", "play_pause"),
                                 ("next", "next_track")):
                buttons.append(HitButton(name, action, QRectF(x, y, btn, btn)))
                x += btn + btn_gap
            # Shuffle/repeat sit after the transport row, smaller, if the time still fits.
            mode_btn = round(btn * 0.8)
            mode_w = 2 * (mode_btn + btn_gap) + 4
            if self.settings.show_mode_buttons and text_w - row_w - mode_w >= MIN_TIME_WIDTH:
                x += 4
                offset = (btn - mode_btn) / 2
                for name, action in (("shuffle", "shuffle"), ("repeat", "repeat")):
                    buttons.append(HitButton(name, action,
                                             QRectF(x, y + offset, mode_btn, mode_btn), False, "mode"))
                    x += mode_btn + btn_gap
                row_w += mode_w
            self._time_rect = QRectF(text_left + row_w + 8, y,
                                     max(0.0, text_w - row_w - 8), btn)
            y += btn + prog_gap
            self._progress_rect = (
                QRectF(text_left, y, text_w, prog_h) if self.settings.show_progress else QRectF()
            )

        self._buttons = buttons
        self._sync_button_state()

    def _relayout_cover(self) -> None:
        """Cover only: the art fills the card; buttons appear over it on hover."""
        card = self._card
        btn = min(self.skin.metric("button_size"), int(card.width() / 3.6))
        btn_gap = max(2, min(self.skin.metric("button_gap"), int(card.width() / 20)))
        buttons: list[HitButton] = []
        chrome = 12
        chrome_x = card.right() - 6 - chrome
        for name, action in (("close", "quit"), ("minimize", "hide"), ("gear", "settings")):
            buttons.append(HitButton(name, action,
                                     QRectF(chrome_x, card.top() + 6, chrome, chrome), True, "chrome"))
            chrome_x -= chrome + 4
        x = card.center().x() - (3 * btn + 2 * btn_gap) / 2
        y = card.center().y() - btn / 2 + 4
        for name, action in (("prev", "prev_track"), ("play", "play_pause"), ("next", "next_track")):
            buttons.append(HitButton(name, action, QRectF(x, y, btn, btn)))
            x += btn + btn_gap
        self._art_rect = QRectF(card)
        self._title_rect = QRectF()
        self._artist_rect = QRectF()
        self._time_rect = QRectF()
        prog_h = self.skin.metric("progress_height")
        self._progress_rect = (QRectF(card.left(), card.bottom() - prog_h, card.width(), prog_h)
                               if self.settings.show_progress else QRectF())
        self._buttons = buttons
        self._sync_button_state()

    def _sync_button_state(self) -> None:
        state = self.state
        for button in self._buttons:
            if button.role != "transport":
                continue
            if button.action == "play_pause":
                button.name = "pause" if state.playing else "play"
                button.enabled = state.connected and (state.can_play or state.can_pause)
            elif button.action == "next_track":
                button.enabled = state.connected and state.can_next
            elif button.action == "prev_track":
                button.enabled = state.connected and state.can_prev
        for button in self._buttons:
            if button.role != "mode":
                continue
            if button.action == "shuffle":
                button.enabled = state.connected and state.can_shuffle
            else:
                button.enabled = state.connected and state.can_repeat
                button.name = "repeat_one" if state.repeat == REPEAT_TRACK else "repeat"

    # ---------------------------------------------------------------- state

    def set_state(self, state: PlayerState) -> None:
        changed = state.identity() != self.state.identity()
        self.state = state
        if state.art_key != self._art_key:
            self._art_key = state.art_key
            self._art_pixmap = None
            if state.art:
                pixmap = QPixmap()
                if pixmap.loadFromData(state.art):
                    self._art_pixmap = pixmap
            self._set_ambient(self._art_pixmap)
        if changed:
            self._scroll = 0.0
            self._scroll_hold = time.monotonic() + 1.2
            self._sync_button_state()
            source = friendly_source_name(state.app_id) if state.app_id else ""
            tip = " — ".join(p for p in (state.artist, state.title) if p) or tr("widget.no_player")
            self.setToolTip(f"{tip}\n{source}" if source else tip)
        self.update()

    # -------------------------------------------------------------- ambient

    def _set_ambient(self, pixmap: QPixmap | None, fade: bool = True) -> None:
        colors = None
        if pixmap is not None and not pixmap.isNull():
            colors = ambient_colors(pixmap.toImage(), self.skin.color("bg").lightness() < 128)
        self._ambient_from = self._ambient_now() if fade else None
        self._ambient = colors
        self._ambient_since = time.monotonic()

    def _skin_colors(self) -> tuple[QColor, QColor, QColor]:
        return self.skin.color("bg"), self.skin.color("bg2"), self.skin.color("progress_fg")

    def _ambient_now(self) -> tuple[QColor, QColor, QColor]:
        """Background top/bottom and progress colours as they should be painted now."""
        skin = self._skin_colors()
        target = self._ambient if self.settings.art_background and self._ambient else skin
        # keep the skin's own translucency (Glass) and its accent when the art has none
        target = tuple(
            QColor(color.red(), color.green(), color.blue(), base.alpha())
            if color.isValid() else base
            for color, base in zip(target, skin)
        )
        start = self._ambient_from
        t = (time.monotonic() - self._ambient_since) / AMBIENT_FADE
        if start is None or t >= 1.0:
            return target  # type: ignore[return-value]
        t = t * t * (3 - 2 * t)  # smoothstep
        return tuple(_mix(a, b, t) for a, b in zip(start, target))  # type: ignore[return-value]

    def _ambient_fading(self) -> bool:
        return (self._ambient_from is not None
                and time.monotonic() - self._ambient_since < AMBIENT_FADE)

    # ---------------------------------------------------------------- paint

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        radius = float(self.skin.metric("radius"))
        card_path = QPainterPath()
        card_path.addRoundedRect(self._card, radius, radius)

        self._paint_shadow(painter, radius)

        # background
        painter.save()
        painter.setClipPath(card_path)
        top, bottom, self._progress_color = self._ambient_now()
        gradient = QLinearGradient(self._card.topLeft(), self._card.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(card_path, QBrush(gradient))
        if self._bg_pixmap is not None:
            mode = self.skin.data.get("background_image_mode", "stretch")
            if mode == "tile":
                painter.fillRect(self._card, QBrush(self._bg_pixmap))
            elif mode == "center":
                pos = self._card.center() - QPointF(self._bg_pixmap.width() / 2,
                                                    self._bg_pixmap.height() / 2)
                painter.drawPixmap(pos, self._bg_pixmap)
            else:
                painter.drawPixmap(self._card, self._bg_pixmap, QRectF(self._bg_pixmap.rect()))
        painter.restore()

        border = self.skin.color("border")
        if border.alpha():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(self._card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if not self._art_rect.isEmpty():
            self._paint_art(painter)
        if self._cover() and self._hovered:
            painter.fillPath(card_path, QColor(0, 0, 0, 120))  # so the buttons read on any cover
        self._paint_text(painter)
        if not self._progress_rect.isEmpty():
            painter.save()
            painter.setClipPath(card_path)  # keeps edge-to-edge bars inside the rounded card
            self._paint_progress(painter)
            painter.restore()
        self._paint_buttons(painter)
        if self._cover():
            self._paint_cover_osd(painter)
        painter.end()

    def _paint_cover_osd(self, painter: QPainter) -> None:
        """Cover mode has no text slots, so the volume level gets a pill at the bottom."""
        osd = self._osd()
        if not osd:
            return
        painter.setFont(self.skin.font("time"))
        metrics = QFontMetricsF(painter.font())
        width = min(self._card.width() - 12, metrics.horizontalAdvance(osd) + 14)
        height = metrics.height() + 6
        pill = QRectF(self._card.center().x() - width / 2, self._card.bottom() - height - 10,
                      width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), osd)

    def _paint_shadow(self, painter: QPainter, radius: float) -> None:
        blur = self.skin.metric("shadow")
        if blur <= 0:
            return
        color = self.skin.color("shadow")
        if not color.alpha():
            return
        steps = min(blur, 14)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(steps, 0, -1):
            spread = blur * i / steps
            alpha = int(color.alpha() * (1.0 - i / (steps + 1.0)) ** 2 * 0.9)
            if alpha <= 0:
                continue
            tint = QColor(color)
            tint.setAlpha(alpha)
            painter.setBrush(tint)
            painter.drawRoundedRect(
                self._card.adjusted(-spread, -spread * 0.6, spread, spread),
                radius + spread, radius + spread,
            )
        painter.restore()

    def _paint_art(self, painter: QPainter) -> None:
        radius = float(self.skin.metric("radius" if self._cover() else "art_radius"))
        path = QPainterPath()
        path.addRoundedRect(self._art_rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.fillPath(path, self.skin.color("art_placeholder"))
        if self._art_pixmap is not None and not self._art_pixmap.isNull():
            side = int(max(self._art_rect.width(), self._art_rect.height()))
            scaled = self._art_pixmap.scaled(
                side, side,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            src = QRectF(
                (scaled.width() - self._art_rect.width()) / 2,
                (scaled.height() - self._art_rect.height()) / 2,
                self._art_rect.width(), self._art_rect.height(),
            )
            painter.drawPixmap(self._art_rect, scaled, src)
        else:
            icons.paint_icon(painter, "note", self._art_rect, self.skin.color("icon_disabled"), 0.5)
        painter.restore()

    def _paint_text(self, painter: QPainter) -> None:
        state = self.state
        if state.has_track:
            title = state.title or "—"
            artist = state.artist or friendly_source_name(state.app_id)
        elif state.connected:
            title = friendly_source_name(state.app_id)
            artist = tr("widget.no_track_data")
        else:
            title = tr("widget.no_player")
            artist = tr("widget.start_music")

        osd = self._osd()
        if osd and self._time_rect.isEmpty():
            title = osd  # compact mode has no time slot; borrow the title's

        painter.setFont(self.skin.font("title"))
        self._draw_scrolling(painter, self._title_rect, title, self.skin.color("title"))

        if not self._artist_rect.isEmpty():
            painter.setFont(self.skin.font("artist"))
            painter.setPen(self.skin.color("artist"))
            index, lyric = self._current_lyric()
            self._lyric_index = index
            if lyric:
                artist = lyric
                painter.setPen(self.skin.color("title"))  # sung words stand out from the artist
            metrics = QFontMetricsF(painter.font())
            elided = metrics.elidedText(artist, Qt.TextElideMode.ElideRight,
                                        int(self._artist_rect.width()))
            painter.drawText(self._artist_rect, int(Qt.AlignmentFlag.AlignLeft |
                                                    Qt.AlignmentFlag.AlignVCenter), elided)

        if self._time_rect.isEmpty():
            return
        if osd:
            text = osd
        elif state.duration > 0:
            position = self._seek_ratio * state.duration if self._seeking else state.live_position()
            text = f"{_fmt_time(position)} / {_fmt_time(state.duration)}"
        else:
            return
        painter.setFont(self.skin.font("time"))
        painter.setPen(self.skin.color("time"))
        painter.drawText(self._time_rect,
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)

    def _draw_scrolling(self, painter: QPainter, rect: QRectF, text: str, color: QColor) -> None:
        if rect.isEmpty():
            return
        metrics = QFontMetricsF(painter.font())
        width = metrics.horizontalAdvance(text)
        painter.setPen(color)
        align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._title_overflows = width > rect.width()
        if not self._title_overflows or not self.settings.scroll_long_titles:
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
            painter.drawText(rect, align, elided)
            return
        painter.save()
        painter.setClipRect(rect)
        span = width + 48.0
        offset = self._scroll % span
        painter.drawText(rect.adjusted(-offset, 0, span, 0), align, text)
        painter.drawText(rect.adjusted(-offset + span, 0, span * 2, 0), align, text)
        painter.restore()

    def _paint_progress(self, painter: QPainter) -> None:
        state = self.state
        if state.duration <= 0:
            return  # source publishes no timeline (foobar2000 etc.) - no empty bar
        radius = float(self.skin.metric("progress_radius"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.skin.color("progress_bg"))
        painter.drawRoundedRect(self._progress_rect, radius, radius)
        ratio = self._seek_ratio if self._seeking else state.live_position() / state.duration
        ratio = max(0.0, min(1.0, ratio))
        filled = QRectF(self._progress_rect)
        filled.setWidth(self._progress_rect.width() * ratio)
        painter.setBrush(self._progress_color)
        painter.drawRoundedRect(filled, radius, radius)
        if self._hovered and state.can_seek:
            painter.setBrush(self._progress_color)
            knob = radius + 2.5
            painter.drawEllipse(QPointF(filled.right(), filled.center().y()), knob, knob)

    def _paint_buttons(self, painter: QPainter) -> None:
        for button in self._buttons:
            if button.role == "chrome" and not self._hovered:
                continue
            if button.role == "mode" and not button.enabled:
                continue  # the player can't do it; an inert icon would only confuse
            if self._cover() and not self._hovered:
                continue  # the cover itself is the point of this mode
            hovered = button is self._hover
            if button.role == "mode":
                active = (self.state.shuffle if button.action == "shuffle"
                          else self.state.repeat != REPEAT_NONE)
                color = self._progress_color if active else self.skin.color("icon_disabled")
                if hovered:
                    color = color.lighter(125) if active else self.skin.color("icon")
                scale = 0.78
            elif button.role == "chrome":
                color = self.skin.color("chrome")
                if hovered:
                    color = self.skin.color("close_hover" if button.action == "quit"
                                            else "chrome_hover")
                scale = 0.95
            elif not button.enabled:
                color = self.skin.color("icon_disabled")
                scale = 0.62
            else:
                color = self.skin.color("icon_hover" if hovered else "icon")
                scale = 0.62
            if self._cover() and button.role == "transport":
                color = QColor(255, 255, 255, 255 if hovered else 225 if button.enabled else 110)
            if hovered and button.enabled and button.role in ("transport", "mode"):
                bg = self.skin.color("icon_bg_hover")
                if bg.alpha():
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(bg)
                    painter.drawEllipse(button.rect)
            custom = self.skin.icon_pixmap(button.name)
            if custom is not None:
                target = button.rect.adjusted(2, 2, -2, -2)
                painter.drawPixmap(target, custom, QRectF(custom.rect()))
            else:
                icons.paint_icon(painter, button.name, button.rect, color, scale)

    # ---------------------------------------------------------------- input

    def _button_at(self, pos) -> HitButton | None:
        for button in self._buttons:
            if button.role == "chrome" and not self._hovered:
                continue
            if button.role == "mode" and not button.enabled:
                continue
            if button.rect.adjusted(-2, -2, 2, 2).contains(pos):
                return button
        return None

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if not self._card.contains(pos):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.open_menu.emit(event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.command.emit("play_pause", None)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        button = self._button_at(pos)
        if button is not None:
            if button.role == "chrome":
                if button.action == "settings":
                    self.open_settings.emit()
                elif button.action == "hide":
                    self.hide_to_tray.emit()
                else:
                    self.quit_requested.emit()
            elif button.enabled:
                self.command.emit(button.action, None)
            return

        if self._seekable_at(pos):
            self._seeking = True
            self._update_seek(pos)
            return

        if not self.settings.lock_position:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._seeking:
            self._update_seek(pos)
            return
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return
        button = self._button_at(pos)
        if button is not self._hover:
            self._hover = button
            self.setCursor(Qt.CursorShape.PointingHandCursor if button
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._seeking:
            self._seeking = False
            if self.state.duration > 0:
                self.command.emit("seek", self._seek_ratio * self.state.duration)
            return
        if self._drag_offset is not None:
            self._drag_offset = None
            if self.settings.snap_to_edges:
                self._snap_to_edges()
            self.save_position()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() != Qt.MouseButton.LeftButton or self._button_at(pos) is not None:
            return
        if self._seekable_at(pos):
            return  # a fast double seek is not a request for compact mode
        self.cycle_view()
        self.settings.save()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self.settings.wheel_volume:
            return
        delta = event.angleDelta().y()
        if delta:
            self.command.emit("volume_up" if delta > 0 else "volume_down", None)

    def _seekable_at(self, pos) -> bool:
        return (not self._progress_rect.isEmpty() and self.state.can_seek
                and self.state.duration > 0
                and self._progress_rect.adjusted(0, -5, 0, 5).contains(pos))

    def _update_seek(self, pos) -> None:
        if self._progress_rect.width() <= 0:
            return
        ratio = (pos.x() - self._progress_rect.left()) / self._progress_rect.width()
        self._seek_ratio = max(0.0, min(1.0, ratio))
        self.update()

    # ------------------------------------------------------------- position

    def _snap_to_edges(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        geo = self.frameGeometry()
        margin = self.skin.metric("shadow")
        x, y = geo.x(), geo.y()
        if abs(geo.left() + margin - area.left()) < SNAP_DISTANCE:
            x = area.left() - margin
        elif abs(geo.right() - margin - area.right()) < SNAP_DISTANCE:
            x = area.right() - geo.width() + margin + 1
        if abs(geo.top() + margin - area.top()) < SNAP_DISTANCE:
            y = area.top() - margin
        elif abs(geo.bottom() - margin - area.bottom()) < SNAP_DISTANCE:
            y = area.bottom() - geo.height() + margin + 1
        self.move(x, y)

    def save_position(self) -> None:
        if not self.settings.remember_position:
            return
        self.settings.pos_x = self.x()
        self.settings.pos_y = self.y()
        self.settings.save()

    def restore_position(self) -> None:
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        x, y = self.settings.pos_x, self.settings.pos_y
        if x is None or y is None or not self.settings.remember_position:
            if area is None:
                return
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
            return
        point = QPoint(int(x), int(y))
        if area is not None:
            visible = any(s.availableGeometry().contains(
                QPoint(point.x() + self.width() // 2, point.y() + self.height() // 2))
                for s in QApplication.screens())
            if not visible:
                point = QPoint(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
        self.move(point)

    # ----------------------------------------------------------------- tick

    def _on_tick(self) -> None:
        if not self.isVisible():
            return
        needs_repaint = False
        # Only a title that actually scrolls needs frames; repainting a static one
        # 30 times a second just burns CPU.
        if (self.settings.scroll_long_titles and self._title_overflows
                and time.monotonic() > self._scroll_hold):
            self._scroll += 0.6
            needs_repaint = True
        if self.state.playing and self.state.duration > 0 and not self._progress_rect.isEmpty():
            needs_repaint = True
        if self._ambient_fading():
            needs_repaint = True
        if self.state.playing and self._current_lyric()[0] != self._lyric_index:
            needs_repaint = True  # next line, even with the progress bar hidden
        if self._osd_text and not self._osd():
            self._osd_text = ""  # expired: one last repaint to take it down
            needs_repaint = True
        if needs_repaint:
            self.update()
