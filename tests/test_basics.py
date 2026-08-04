"""Headless checks that need no live media session — safe to run in CI.

Run with:  python tests/test_basics.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Locale names and translated strings are non-ASCII; the default Windows console
# encoding (cp1252) can't print them and would crash the check() below.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

import app.config as config  # noqa: E402

_SANDBOX = Path(tempfile.mkdtemp(prefix="atm-tests-"))
config.config_dir = lambda: _SANDBOX  # keep the real settings file untouched

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import HOTKEY_ACTIONS, Settings  # noqa: E402
from app.hotkeys import format_hotkey, parse_hotkey  # noqa: E402
from app.i18n import (  # noqa: E402
    BUILTIN_LOCALES_DIR, available_languages, resolve_language, set_language, tr,
)
from app.media import friendly_source_name  # noqa: E402
from app.skins import DEFAULT_SKIN, available_skins, load_skin  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, extra: object = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f" -> {extra}" if extra != "" else ""))
    if not condition:
        FAILURES.append(name)


def test_settings() -> None:
    settings = Settings()
    settings.skin = "neon"
    settings.opacity = 0.75
    settings.pos_x, settings.pos_y = 111, 222
    settings.language = "de"
    settings.save()
    check("settings file written", (_SANDBOX / "settings.json").exists())

    loaded = Settings.load()
    check("skin persisted", loaded.skin == "neon", loaded.skin)
    check("opacity persisted", abs(loaded.opacity - 0.75) < 1e-9, loaded.opacity)
    check("position persisted", (loaded.pos_x, loaded.pos_y) == (111, 222))
    check("language persisted", loaded.language == "de", loaded.language)

    raw = json.loads((_SANDBOX / "settings.json").read_text(encoding="utf-8"))
    raw["option_from_the_future"] = 42
    del raw["hotkeys"]["volume_up"]
    (_SANDBOX / "settings.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = Settings.load()
    check("unknown keys ignored", loaded.skin == "neon")
    check("missing hotkey backfilled", "volume_up" in loaded.hotkeys)

    (_SANDBOX / "settings.json").write_text("{ not json at all", encoding="utf-8")
    check("corrupt settings fall back to defaults", Settings.load().skin == "dark")


def test_legacy_migration() -> None:
    base = Path(tempfile.mkdtemp(prefix="atm-migration-"))
    original_base = config._config_base
    config._config_base = lambda: base
    try:
        legacy = base / config.LEGACY_APP_NAMES[0]
        (legacy / "skins" / "my-skin").mkdir(parents=True)
        (legacy / "settings.json").write_text('{"skin": "neon"}', encoding="utf-8")

        adopted = config.migrate_legacy_config()
        target = base / config.APP_NAME
        check("legacy folder adopted", adopted is not None and adopted.name == legacy.name, adopted)
        check("settings carried over", (target / "settings.json").exists())
        check("settings content intact",
              json.loads((target / "settings.json").read_text(encoding="utf-8"))["skin"] == "neon")
        check("user skins carried over", (target / "skins" / "my-skin").is_dir())
        check("legacy folder no longer there", not legacy.exists())
        check("running again is a no-op", config.migrate_legacy_config() is None)

        fresh = Path(tempfile.mkdtemp(prefix="atm-migration-none-"))
        config._config_base = lambda: fresh
        check("nothing to migrate is fine", config.migrate_legacy_config() is None)
    finally:
        config._config_base = original_base


def test_skins() -> None:
    ids = {skin.id for skin in available_skins()}
    check("built-in skins load", {"dark", "light", "neon", "glass"} <= ids, sorted(ids))
    check("unknown skin falls back", load_skin("does-not-exist").id == "dark")

    light, dark = load_skin("light"), load_skin("dark")
    check("extends inherits size", light.size() == dark.size(), light.size())
    check("extends overrides colour", light.color("title").name() == "#171b23",
          light.color("title").name())
    check("alpha colour parsed", load_skin("glass").color("bg").alpha() == 0xB3,
          load_skin("glass").color("bg").alpha())
    check("child overrides metric", load_skin("neon").metric("radius") == 6)
    check("unknown colour key falls back", dark.color("no_such_colour").isValid())
    for key in DEFAULT_SKIN["colors"]:
        if not dark.color(key).isValid():
            check(f"colour {key} valid", False)
            return
    check("every default colour resolves", True)


def test_hotkeys() -> None:
    cases = [
        ("Ctrl+Alt+M", (3, 0x4D)),
        ("Shift+F5", (4, 0x74)),
        ("Win+Alt+Right", (9, 0x27)),
        ("Media Play", (0, 0xB3)),
        ("Ctrl+Alt+Num5", (3, 0x65)),
    ]
    for text, expected in cases:
        check(f"parse {text}", parse_hotkey(text) == expected, parse_hotkey(text))
    check("parse empty", parse_hotkey("") is None)
    check("parse junk", parse_hotkey("Ctrl+Nonsense") is None)
    check("format round trip", format_hotkey(3, 0x4D) == "Ctrl+Alt+M", format_hotkey(3, 0x4D))
    check("format arrows", format_hotkey(3, 0x27) == "Ctrl+Alt+Right", format_hotkey(3, 0x27))


def test_sources() -> None:
    cases = [
        ("Spotify.exe", "Spotify"),
        ("Chrome", "Google Chrome"),
        ("msedge.exe", "Microsoft Edge"),
        ("foobar2000.exe", "foobar2000"),
        ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Media Player"),
        ("SomeUnknownApp.exe", "SomeUnknownApp"),
        ("", "—"),
    ]
    for app_id, expected in cases:
        check(f"source name {app_id!r}", friendly_source_name(app_id) == expected,
              friendly_source_name(app_id))


def test_locales() -> None:
    reference = json.loads((BUILTIN_LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
    expected_keys = {key for key in reference if not key.startswith("_")}
    check("reference locale is not empty", len(expected_keys) > 50, len(expected_keys))

    codes = [code for code, _ in available_languages()]
    check("locales discovered", len(codes) >= 10, codes)

    for path in sorted(BUILTIN_LOCALES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = {key for key in data if not key.startswith("_")}
        missing = sorted(expected_keys - keys)
        extra = sorted(keys - expected_keys)
        meta = data.get("_meta", {})
        check(f"{path.name}: complete", not missing, missing[:5])
        check(f"{path.name}: no stray keys", not extra, extra[:5])
        check(f"{path.name}: has _meta name", bool(meta.get("name")), meta)
        check(f"{path.name}: code matches file", meta.get("code") == path.stem, meta.get("code"))
        bad_placeholders = []
        for key in expected_keys & keys:
            want = {p.split("}")[0] for p in reference[key].split("{")[1:]}
            got = {p.split("}")[0] for p in data[key].split("{")[1:]}
            if want != got:
                bad_placeholders.append(f"{key}: {sorted(want)} != {sorted(got)}")
        check(f"{path.name}: placeholders match", not bad_placeholders, bad_placeholders[:3])

    set_language("de")
    check("german string", tr("menu.quit") == "Beenden", tr("menu.quit"))
    check("formatting works", "{" not in tr("settings.sources_found", count=2, names="a, b"),
          tr("settings.sources_found", count=2, names="a, b"))
    set_language("ru")
    check("russian string", tr("menu.quit") == "Выход", tr("menu.quit"))
    check("missing key returns the key", tr("no.such.key") == "no.such.key")
    check("auto resolves to a real locale", resolve_language("auto") in codes,
          resolve_language("auto"))
    check("unknown code falls back", resolve_language("xx-YY") in codes,
          resolve_language("xx-YY"))
    check("regional code falls back to base", resolve_language("de-AT") == "de",
          resolve_language("de-AT"))
    for action in HOTKEY_ACTIONS:
        if tr(f"hotkey.{action}") == f"hotkey.{action}":
            check(f"hotkey label for {action}", False)
            return
    check("every hotkey action has a label", True)
    set_language("en")


def main() -> int:
    QApplication(sys.argv)  # QColor/QFont need an application instance
    test_settings()
    test_legacy_migration()
    test_skins()
    test_hotkeys()
    test_sources()
    test_locales()
    print()
    print("FAILURES:", FAILURES if FAILURES else "none")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
