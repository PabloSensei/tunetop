"""Translations.

A locale is a single JSON file: `_meta` plus flat `key: text` pairs. Built-in
locales live in `locales/`, user-supplied ones in `%APPDATA%\\Tunetop\\locales`
and shadow the built-ins, so a translation can be added or fixed without a rebuild.

Lookup order: selected language -> English -> the key itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QLocale

from .config import app_root, config_dir

BUILTIN_LOCALES_DIR = app_root() / "locales"
FALLBACK = "en"


def user_locales_dir() -> Path:
    path = config_dir() / "locales"
    path.mkdir(parents=True, exist_ok=True)
    return path


def locale_files() -> dict[str, Path]:
    """Language code -> file. User files shadow built-ins of the same code."""
    files: dict[str, Path] = {}
    for root in (BUILTIN_LOCALES_DIR, user_locales_dir()):
        if not root.exists():
            continue
        for child in sorted(root.glob("*.json")):
            files[child.stem] = child
    return files


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class Translator:
    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._fallback: dict[str, str] = {}
        self._language = FALLBACK
        self._requested = "auto"
        # Nothing is read here on purpose: touching the config folder at import
        # time would create it before migrate_legacy_config() gets a chance.
        self._loaded = False

    # -- selection --------------------------------------------------------

    @property
    def language(self) -> str:
        """The language actually in use (never "auto")."""
        return self._language

    @property
    def requested(self) -> str:
        return self._requested

    def resolve(self, requested: str) -> str:
        """Turn "auto" or a code into a language that exists on disk."""
        files = locale_files()
        if requested and requested != "auto":
            if requested in files:
                return requested
            base = requested.replace("_", "-").split("-")[0]
            if base in files:
                return base
        system = QLocale.system().name().replace("_", "-")  # e.g. "pt-BR"
        if system in files:
            return system
        base = system.split("-")[0]
        if base in files:
            return base
        for code in files:
            if code.split("-")[0] == base:
                return code
        return FALLBACK if FALLBACK in files else (next(iter(files), FALLBACK))

    def set_language(self, requested: str) -> str:
        self._requested = requested or "auto"
        files = locale_files()
        self._language = self.resolve(self._requested)
        self._fallback = _read(files[FALLBACK]) if FALLBACK in files else {}
        path = files.get(self._language)
        self._strings = _read(path) if path is not None else {}
        self._loaded = True
        return self._language

    # -- lookup -----------------------------------------------------------

    def tr(self, key: str, **kwargs) -> str:
        if not self._loaded:
            self.set_language(self._requested)
        text = self._strings.get(key) or self._fallback.get(key) or key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text


_translator = Translator()


def tr(key: str, **kwargs) -> str:
    return _translator.tr(key, **kwargs)


def set_language(requested: str) -> str:
    return _translator.set_language(requested)


def current_language() -> str:
    return _translator.language


def resolve_language(requested: str) -> str:
    """Which language "auto" (or a code) actually maps to on this machine."""
    return _translator.resolve(requested)


def available_languages() -> list[tuple[str, str]]:
    """[(code, native name)] sorted by native name."""
    out = []
    for code, path in locale_files().items():
        meta = _read(path).get("_meta", {})
        name = meta.get("name") if isinstance(meta, dict) else None
        out.append((code, str(name or code)))
    return sorted(out, key=lambda item: item[1].lower())


def language_name(code: str) -> str:
    for existing, name in available_languages():
        if existing == code:
            return name
    return code
