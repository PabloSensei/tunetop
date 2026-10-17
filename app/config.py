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


def _fits(value: object, default: object) -> bool:
    """Whether a hand-edited `value` has the shape of the field whose default is `default`.

    A wrong type (say, "opacity": "high") would otherwise crash the app on the
    first use of the field, long after loading looked fine.
    """
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, dict):
        return isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )
    if default is None:  # the optional window position
        return value is None or (isinstance(value, int) and not isinstance(value, bool))
    return isinstance(value, type(default))


@dataclass
class Settings:
    # appearance
    language: str = "auto"  # "auto" follows Windows, otherwise a locale code
    skin: str = "dark"
    opacity: float = 1.0
    compact: bool = False
    cover_mode: bool = False  # album art only, controls on hover; wins over `compact`
    show_album_art: bool = True
    art_background: bool = False  # tint the card with colours taken from the album art
    show_progress: bool = True
    show_mode_buttons: bool = True  # shuffle/repeat, when the player supports them
    scroll_long_titles: bool = True
    show_lyrics: bool = False  # synced lyrics from lrclib.net in place of the artist line
    track_toast: str = "off"  # "off" | "hidden" (only while the widget is hidden) | "always"

    # window behaviour
    always_on_top: bool = True
    lock_position: bool = False
    snap_to_edges: bool = True
    remember_position: bool = True
    pos_x: int | None = None
    pos_y: int | None = None
    # "x,y" per monitor layout ("1920x1080@0,0|2560x1440@1920,0"), so docking a
    # laptop puts the widget back where it lived on that desk
    positions: dict[str, str] = field(default_factory=dict)
    start_in_tray: bool = False
    autostart: bool = False
    hide_when_no_music: bool = False

    # input
    hotkeys_enabled: bool = True
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    wheel_volume: bool = True
    volume_target: str = "app"  # "app" (the player's own volume) | "system"

    # media source
    source_mode: str = "auto"  # "auto" | "pinned"
    pinned_source: str = ""  # AppUserModelId of the pinned session

    # updates
    check_for_updates: bool = True
    auto_install_updates: bool = False  # installed build only: download and install unasked
    skipped_update_version: str = ""
    last_update_check: str = ""  # ISO timestamp of the last completed check; "" means never
    latest_known_version: str = ""  # newest version GitHub reported, so a restart can say so offline

    @classmethod
    def load(cls) -> "Settings":
        path = config_file()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # ValueError covers bad JSON and bad UTF-8
            return cls()
        if not isinstance(raw, dict):
            return cls()
        defaults = cls()
        data = {
            k: v for k, v in raw.items()
            if k in cls.__dataclass_fields__ and _fits(v, getattr(defaults, k))
        }
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
