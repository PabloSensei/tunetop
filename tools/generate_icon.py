"""Regenerate the static icon assets from the vector app icon.

The tray/window icon is drawn at runtime (`icons.paint_app_icon`, tinted with
the active skin's accent colour), but a few places need a real file on disk:
the .exe icon PyInstaller bakes in, and the logo shown in the README. This
renders that same vector art, fixed to the Dark skin's accent, into:

    docs/icon.png    256x256, for the README
    assets/icon.ico  16..256px, for --icon in build-exe.bat / release.yml

Run after changing the icon design in app/icons.py:

    .venv\\Scripts\\python tools\\generate_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import icons  # noqa: E402

ACCENT = "#6c8cff"  # the Dark skin's accent colour; static assets can't reskin
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    icons.paint_app_icon(painter, QRectF(0, 0, size, size), QColor(ACCENT))
    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path, sizes: tuple[int, ...]) -> None:
    """A minimal ICO container with PNG-compressed entries (supported since Vista)."""
    entries = [(size, _png_bytes(render(size))) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(entries))
    directory = b""
    data = b""
    offset = len(header) + 16 * len(entries)
    for size, payload in entries:
        wh = size if size < 256 else 0  # 0 means 256 in the ICO format
        directory += struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(payload), offset)
        data += payload
        offset += len(payload)
    path.write_bytes(header + directory + data)


def main() -> None:
    QApplication(sys.argv)

    docs_png = ROOT / "docs" / "icon.png"
    docs_png.parent.mkdir(parents=True, exist_ok=True)
    render(256).save(str(docs_png), "PNG")
    print(f"wrote {docs_png}")

    ico_path = ROOT / "assets" / "icon.ico"
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    write_ico(ico_path, ICO_SIZES)
    print(f"wrote {ico_path}")


if __name__ == "__main__":
    main()
