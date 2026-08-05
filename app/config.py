"""Application settings: dataclass + JSON persistence in %APPDATA%."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "Tunetop"

# Folders used by earlier names of the app, newest first. Their contents are
# adopted once, on first start after an upgrade.
LEGACY_APP_NAMES = ("AlwaysTopMusic",)


def app_root() -> Path:
    """Folder holding the bundled `skins/` and `locales/`.

    Under PyInstaller those are unpacked next to the frozen modules, so the
    path has to come from _MEIPASS rather than from __file__.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _config_base() -> Path:
    return Path(os.environ.get("APPDATA") or str(Path.home()))


def config_dir() -> Path:
    path = _config_base() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_config() -> Path | None:
    """Adopt the settings folder of a previous app name, once.

    Must run before anything calls config_dir(), which would create the new
    folder and make the migration look unnecessary. Returns the folder that was
    taken over, or None if there was nothing to do.
    """
    base = _config_base()
    target = base / APP_NAME
    if target.exists():
        return None
    for legacy in LEGACY_APP_NAMES:
        source = base / legacy
        if not source.is_dir():
            continue
        try:
            source.rename(target)
            return source
        except OSError:
            try:  # different volume, or the folder is in use
                shutil.copytree(source, target)
                return source
            except OSError:
                return None
    return None


def config_file() -> Path:
    return config_dir() / "settings.json"


def user_skins_dir() -> Path:
    path = config_dir() / "skins"
    path.mkdir(parents=True, exist_ok=True)
    return path


DEFAULT_HOTKEYS: dict[str, str] = {
    "toggle_widget": "Ctrl+Alt+M",
    "play_pause": "Ctrl+Alt+P",
    "next_track": "Ctrl+Alt+Right",
    "prev_track": "Ctrl+Alt+Left",
    "volume_up": "Ctrl+Alt+Up",
    "volume_down": "Ctrl+Alt+Down",
}

# Display order in the settings UI; labels come from the "hotkey.<action>" keys.
HOTKEY_ACTIONS: tuple[str, ...] = (
    "toggle_widget", "play_pause", "next_track", "prev_track", "volume_up", "volume_down",
)


@dataclass
class Settings:
    # appearance
    language: str = "auto"  # "auto" follows Windows, otherwise a locale code
    skin: str = "dark"
    opacity: float = 1.0
    compact: bool = False
    show_album_art: bool = True
    show_progress: bool = True
    scroll_long_titles: bool = True

    # window behaviour
    always_on_top: bool = True
    lock_position: bool = False
    snap_to_edges: bool = True
    remember_position: bool = True
    pos_x: int | None = None
    pos_y: int | None = None
    start_in_tray: bool = False
    autostart: bool = False
    hide_when_no_music: bool = False

    # input
    hotkeys_enabled: bool = True
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    wheel_volume: bool = True

    # media source
    source_mode: str = "auto"  # "auto" | "pinned"
    pinned_source: str = ""  # AppUserModelId of the pinned session

    # updates
    check_for_updates: bool = True
    skipped_update_version: str = ""
    last_update_check: str = ""  # ISO date "YYYY-MM-DD"; "" means never checked

    @classmethod
    def load(cls) -> "Settings":
        path = config_file()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in raw.items() if k in known}
        settings = cls(**data)
        # merge in hotkeys added by newer versions
        merged = dict(DEFAULT_HOTKEYS)
        merged.update(settings.hotkeys or {})
        settings.hotkeys = merged
        return settings

    def save(self) -> None:
        path = config_file()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
