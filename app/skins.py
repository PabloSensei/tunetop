"""Skin loading.

A skin is a folder with a `skin.json` manifest (plus optional images). Manifests
are merged on top of DEFAULT_SKIN, so a skin only has to declare what it changes,
and may `extend` another skin.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPixmap

from .config import app_root, user_skins_dir

BUILTIN_SKINS_DIR = app_root() / "skins"

DEFAULT_SKIN: dict = {
    "name": "Default",
    "author": "",
    "size": [340, 92],
    "compact_size": [252, 40],
    "radius": 14,
    "padding": 10,
    "spacing": 10,
    "art_size": 64,
    "art_radius": 8,
    "button_size": 26,
    "button_gap": 6,
    "progress_height": 4,
    "progress_radius": 2,
    "shadow": 18,
    "background_image": "",
    "background_image_mode": "stretch",  # stretch | tile | center
    "colors": {
        "bg": "#1c1e26",
        "bg2": "#14161c",
        "border": "#3a3f4b",
        "shadow": "#66000000",
        "title": "#f3f5f9",
        "artist": "#98a0b0",
        "time": "#787f8d",
        "icon": "#e4e8f0",
        "icon_hover": "#ffffff",
        "icon_disabled": "#4b515e",
        "icon_bg_hover": "#1affffff",  # colours accept #RRGGBB or #AARRGGBB
        "accent": "#6c8cff",
        "progress_bg": "#3a3f4b",
        "progress_fg": "#6c8cff",
        "art_placeholder": "#2a2e38",
        "chrome": "#7a8290",
        "chrome_hover": "#ffffff",
        "close_hover": "#ff5f57",
    },
    "fonts": {
        "title": {"family": "Segoe UI", "size": 10, "bold": True},
        "artist": {"family": "Segoe UI", "size": 9, "bold": False},
        "time": {"family": "Segoe UI", "size": 8, "bold": False},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Skin:
    id: str
    path: Path
    data: dict = field(default_factory=dict)

    # -- accessors --------------------------------------------------------

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.id)

    @property
    def author(self) -> str:
        return str(self.data.get("author") or "")

    def color(self, key: str) -> QColor:
        raw = self.data.get("colors", {}).get(key)
        if raw is None:
            raw = DEFAULT_SKIN["colors"].get(key, "#ff00ff")
        color = QColor(raw)
        if not color.isValid():
            color = QColor(DEFAULT_SKIN["colors"].get(key, "#ff00ff"))
        return color

    def metric(self, key: str) -> int:
        value = self.data.get(key, DEFAULT_SKIN.get(key, 0))
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(DEFAULT_SKIN.get(key, 0))

    def size(self, compact: bool = False) -> tuple[int, int]:
        raw = self.data.get("compact_size" if compact else "size")
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raw = DEFAULT_SKIN["compact_size" if compact else "size"]
        try:
            return max(120, int(raw[0])), max(28, int(raw[1]))
        except (TypeError, ValueError):
            return tuple(DEFAULT_SKIN["compact_size" if compact else "size"])  # type: ignore

    def font(self, key: str) -> QFont:
        spec = self.data.get("fonts", {}).get(key, {})
        default = DEFAULT_SKIN["fonts"].get(key, {"family": "Segoe UI", "size": 9, "bold": False})
        font = QFont(str(spec.get("family", default["family"])))
        font.setPointSizeF(float(spec.get("size", default["size"])))
        font.setBold(bool(spec.get("bold", default["bold"])))
        if spec.get("italic"):
            font.setItalic(True)
        if spec.get("letter_spacing"):
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                  float(spec["letter_spacing"]))
        return font

    def background_pixmap(self) -> QPixmap | None:
        name = self.data.get("background_image") or ""
        if not name:
            return None
        image_path = self.path / name
        if not image_path.exists():
            return None
        pixmap = QPixmap(str(image_path))
        return None if pixmap.isNull() else pixmap

    def icon_pixmap(self, key: str) -> QPixmap | None:
        name = (self.data.get("icons") or {}).get(key)
        if not name:
            return None
        image_path = self.path / name
        if not image_path.exists():
            return None
        pixmap = QPixmap(str(image_path))
        return None if pixmap.isNull() else pixmap


def _load_manifest(folder: Path) -> dict | None:
    manifest = folder / "skin.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def skin_folders() -> dict[str, Path]:
    """Skin id -> folder. User skins shadow built-ins with the same id."""
    folders: dict[str, Path] = {}
    for root in (BUILTIN_SKINS_DIR, user_skins_dir()):
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "skin.json").exists():
                folders[child.name] = child
    return folders


def load_skin(skin_id: str) -> Skin:
    folders = skin_folders()
    folder = folders.get(skin_id)
    if folder is None:
        folder = folders.get("dark") or next(iter(folders.values()), None)
    if folder is None:  # nothing on disk - fall back to the built-in defaults
        return Skin(id="default", path=Path("."), data=copy.deepcopy(DEFAULT_SKIN))

    manifest = _load_manifest(folder) or {}
    data = DEFAULT_SKIN
    parent = manifest.get("extends")
    seen = {folder.name}
    while parent and parent in folders and parent not in seen:
        seen.add(parent)
        parent_manifest = _load_manifest(folders[parent]) or {}
        data = _deep_merge(data, parent_manifest)
        parent = parent_manifest.get("extends")
    data = _deep_merge(data, manifest)
    return Skin(id=folder.name, path=folder, data=data)


def available_skins() -> list[Skin]:
    skins = []
    for skin_id in skin_folders():
        skins.append(load_skin(skin_id))
    return sorted(skins, key=lambda s: s.name.lower())
