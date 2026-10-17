"""Render the README screenshots from the real widget code.

Everything is painted offscreen with fake tracks and generated cover art, so
the images can be refreshed after any visual change without a media player:

    docs/skins.png      every bundled skin, plus compact mode
    docs/views.png      full, compact and cover-only views
    docs/art-tint.png   the background tinted by two different covers
    docs/extras.png     synced lyrics, the track change card, the volume level

Run (any OS; set QT_QPA_PLATFORM=offscreen on a headless machine):

    .venv\\Scripts\\python tools\\render_screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.config as config  # noqa: E402

_SANDBOX = Path(tempfile.mkdtemp(prefix="tunetop-shots-"))
config.config_dir = lambda: _SANDBOX  # never touch the real settings

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.lyrics import parse_lrc  # noqa: E402
from app.media import REPEAT_LIST, PlayerState  # noqa: E402
from app.player_widget import AMBIENT_FADE, PlayerWidget  # noqa: E402
from app.skins import load_skin  # noqa: E402
from app.toast import TrackToast  # noqa: E402

DOCS = ROOT / "docs"
BACKDROP = ("#5a5e69", "#2b2d33")
LABEL = QColor("#d7dbe3")
GAP = 14

# Stand-ins for the Windows fonts the skins ask for, used only when missing.
FONT_FALLBACKS = {"Segoe UI": ("Inter", "Liberation Sans", "DejaVu Sans"),
                  "Consolas": ("DejaVu Sans Mono", "Liberation Mono")}


def substitute_fonts() -> None:
    families = set(QFontDatabase.families())
    for wanted, options in FONT_FALLBACKS.items():
        if wanted not in families:
            QFont.insertSubstitutions(wanted, [f for f in options if f in families])


def cover(colors: tuple[str, ...], size: int = 240) -> bytes:
    """A vinyl-ish placeholder cover: diagonal gradient, rings and a centre dot."""
    image = QImage(size, size, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    fill = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    for index, color in enumerate(colors):
        fill.setColorAt(index / max(1, len(colors) - 1), QColor(color))
    painter.fillRect(image.rect(), fill)
    glow = QRadialGradient(QPointF(size * 0.3, size * 0.25), size * 0.8)
    glow.setColorAt(0, QColor(255, 255, 255, 60))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    painter.fillRect(image.rect(), glow)
    centre = QPointF(size / 2, size / 2)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for ring in range(1, 5):
        painter.setPen(QPen(QColor(255, 255, 255, 70 - ring * 10), size * 0.008))
        painter.drawEllipse(centre, size * 0.1 * ring + size * 0.05, size * 0.1 * ring + size * 0.05)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(centre, size * 0.05, size * 0.05)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


COVER_NEON = cover(("#ff4f8b", "#8a3dff", "#22d3ff"))
COVER_SUNSET = cover(("#ffb31f", "#ff5a3c", "#c2185b"))
COVER_FOREST = cover(("#29e0a0", "#14866d", "#0b3a6e"))


def track(art: bytes = COVER_NEON, title: str = "Midnight City Lights",
          artist: str = "Parallel Dreams", **extra) -> PlayerState:
    base = dict(
        app_id="Spotify.exe", title=title, artist=artist, connected=True, status="playing",
        duration=228.0, position=97.0, can_play=True, can_pause=True, can_next=True,
        can_prev=True, can_seek=True, can_shuffle=True, can_repeat=True,
        repeat=REPEAT_LIST, art=art, art_key=title + str(len(art)),
    )
    base.update(extra)
    return PlayerState(**base)


def widget_image(state: PlayerState, hovered: bool = False, osd: str = "",
                 lyrics: str = "", **settings) -> QImage:
    options = Settings()
    for key, value in settings.items():
        setattr(options, key, value)
    widget = PlayerWidget(options)
    widget.set_state(state)
    widget._ambient_since -= AMBIENT_FADE  # skip the fade-in
    if lyrics:
        widget.set_lyrics((state.app_id, state.title, state.artist), parse_lrc(lyrics))
    if osd:
        widget.show_osd(osd, seconds=60)
    widget._hovered = hovered
    image = widget.grab().toImage()
    widget.deleteLater()
    return image


def toast_image(state: PlayerState, skin: str) -> QImage:
    toast = TrackToast()
    toast._skin = load_skin(skin)
    toast.update_state(state)
    image = toast.grab().toImage()
    toast.deleteLater()
    return image


def sheet(rows: list[list[tuple[str, QImage]]], path: Path) -> None:
    """Lay out labelled images in rows on the dark backdrop and save as PNG."""
    font = QFont("Segoe UI", 9)
    label_h = 22
    widths = [sum(img.width() for _, img in row) + GAP * (len(row) + 1) for row in rows]
    heights = [max(img.height() for _, img in row) + label_h for row in rows]
    width, height = max(widths), sum(heights) + GAP
    canvas = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    backdrop = QLinearGradient(QPointF(0, 0), QPointF(0, height))
    backdrop.setColorAt(0, QColor(BACKDROP[0]))
    backdrop.setColorAt(1, QColor(BACKDROP[1]))
    painter.fillRect(canvas.rect(), backdrop)
    painter.setFont(font)
    y = GAP // 2
    for row, row_height in zip(rows, heights):
        x = GAP
        for caption, image in row:
            painter.setPen(LABEL)
            painter.drawText(QRectF(x + 12, y, image.width(), label_h),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             caption)
            painter.drawImage(x, y + label_h, image)
            x += image.width() + GAP
        y += row_height
    painter.end()
    canvas.save(str(path), "PNG")
    print(f"wrote {path}")


def main() -> None:
    QApplication(sys.argv)
    substitute_fonts()
    DOCS.mkdir(exist_ok=True)

    skins = ["dark", "light", "neon", "glass", "minimal-dark", "minimal-light"]
    shots = [(skin, widget_image(track(shuffle=index % 2 == 1), skin=skin))
             for index, skin in enumerate(skins)]
    rows = [shots[i:i + 2] for i in range(0, len(shots), 2)]
    rows.append([("dark · compact", widget_image(track(), compact=True))])
    sheet(rows, DOCS / "skins.png")

    sheet([
        [("full", widget_image(track()))],
        [("compact", widget_image(track(), compact=True)),
         ("cover only", widget_image(track(), cover_mode=True)),
         ("cover only · hover", widget_image(track(), cover_mode=True, hovered=True))],
    ], DOCS / "views.png")

    sheet([
        [("tinted by the cover", widget_image(track(COVER_SUNSET, "Golden Hour Drive",
                                                     "Coastal Static"), art_background=True)),
         ("", widget_image(track(COVER_FOREST, "Under the Canopy", "Northern Fern"),
                           art_background=True))],
        [("light skin", widget_image(track(COVER_SUNSET, "Golden Hour Drive", "Coastal Static"),
                                     art_background=True, skin="light")),
         ("glass skin", widget_image(track(COVER_FOREST, "Under the Canopy", "Northern Fern"),
                                     art_background=True, skin="glass"))],
    ], DOCS / "art-tint.png")

    lyrics = "[01:30.00]Neon rivers running through the night\n[01:41.00]Hold on"
    sheet([
        [("synced lyrics", widget_image(track(), lyrics=lyrics, show_lyrics=True)),
         ("per-player volume", widget_image(track(), osd="Volume 45%"))],
        [("track change card", toast_image(track(COVER_SUNSET, "Golden Hour Drive",
                                                  "Coastal Static"), "dark")),
         ("", toast_image(track(COVER_FOREST, "Under the Canopy", "Northern Fern"), "light"))],
    ], DOCS / "extras.png")


if __name__ == "__main__":
    main()
