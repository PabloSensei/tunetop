# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tunetop is a Windows-only, always-on-top music control widget (PySide6 + winsdk). It drives
the Windows System Media Transport Controls (SMTC), so it controls whatever app currently
owns a media session — Spotify, browsers, foobar2000, etc. — with no per-player plugins.
Windows 10/11 only; there is no cross-platform path.

## Commands

Setup and run (first `run.bat` creates `.venv` and installs deps):

```bat
run.bat
```

`run-debug.bat` is the same launch with a visible console. Manual equivalent:
`.venv\Scripts\python main.py`.

Tests — a single hand-rolled script, no pytest:

```bat
.venv\Scripts\python tests\test_basics.py
```

It prints `PASS`/`FAIL` per check and exits non-zero on any failure. There is no
per-test selector; edit `main()` in [tests/test_basics.py](tests/test_basics.py) to run a
subset. Headless environments need `QT_QPA_PLATFORM=offscreen` (CI sets this).

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs `python -m compileall -q app main.py tests`
plus the test script on Python 3.10 and 3.12 — byte-compile failures count as test failures.
There is no linter or formatter configured.

Standalone exe: `build-exe.bat` (PyInstaller `--onefile --windowed`, bundling `skins/` and
`locales/` via `--add-data`). Releases are cut by pushing a `v*` tag.

## Architecture

`main.py` sets the AppUserModelID (so the taskbar/tray identity isn't "Python") and calls
`app.application.run()`, which is the composition root: it constructs `MediaController`,
`PlayerWidget`, `HotkeyManager` and the tray icon, then wires them together with Qt signals.
Nothing but `application.py` knows about more than one of those.

Threading model: `MediaController` ([app/media.py](app/media.py)) owns an asyncio loop on a
daemon thread. It subscribes to WinRT session events, and each event just sets an
`asyncio.Event` that wakes a loop which re-polls and emits an immutable `PlayerState`
snapshot over a Qt signal. There is also a 1 s timeout poll as a safety net, since some
players fire no events. Everything Qt-side is single-threaded; never touch WinRT objects
from the GUI thread, and never touch widgets from the media thread.

`PlayerState.live_position()` interpolates position from `captured_at` so the progress bar
animates between polls. `PlayerState.identity()` deliberately excludes position — it is the
comparison key for "does this need a repaint".

Rendering: [app/player_widget.py](app/player_widget.py) is a frameless translucent `QWidget`
painted entirely by hand in `paintEvent`; there are no child widgets and no stylesheets.
Hit testing is done against a `list[HitButton]` rebuilt during layout. Icons are
`QPainterPath`s defined in a 24×24 space ([app/icons.py](app/icons.py)) and scaled/tinted at
draw time, unless the skin supplies image overrides.

Settings ([app/config.py](app/config.py)) are a dataclass persisted as JSON in
`%APPDATA%\Tunetop\settings.json` via atomic write (`.tmp` then `replace`). `Settings.load()`
is deliberately forgiving: unknown keys are dropped, corrupt files fall back to defaults, and
hotkeys added by newer versions are merged in. The settings dialog applies changes live and
saves immediately — no OK/Cancel — and tells `application.py` what changed via
`applied(hint)` where hint is one of `language` / `window` / `skin` / `layout` / `source` /
`visibility` / `hotkeys_preview` / `refresh`. `language` forces a full rebuild of the dialog
since Qt widgets don't re-translate in place.

Hotkeys ([app/hotkeys.py](app/hotkeys.py)) use Win32 `RegisterHotKey` against a hidden sink
window, with `WM_HOTKEY` picked up by a `QAbstractNativeEventFilter` on the QApplication.
Combos are stored as human strings ("Ctrl+Alt+M", "Media Play") so the settings file stays
hand-editable. Registration failure (another app owns the combo) surfaces as a tray warning,
not silence. The settings dialog unregisters everything while it is open so the capture field
can see the keys.

Single instance: a `QLocalServer` named `Tunetop.singleton`. A second launch connects, writes
`show`, and exits 0.

## Data-driven resources

Skins ([app/skins.py](app/skins.py)) and locales ([app/i18n.py](app/i18n.py)) follow the same
pattern: bundled copies under `skins/` and `locales/`, user copies under
`%APPDATA%\Tunetop\{skins,locales}` that **shadow** bundled ones with the same id/code. Both
resolve their root through `config.app_root()`, which returns `sys._MEIPASS` when frozen — use
it rather than `__file__` for anything that must survive the PyInstaller build.

A skin manifest is deep-merged onto `DEFAULT_SKIN`, optionally through an `extends` chain
(cycle-guarded), so a skin declares only what it changes. Skin accessors never raise: bad
colours, sizes and fonts fall back to defaults. Adding a key to `DEFAULT_SKIN` is enough to
make it available to every skin.

A locale is one flat JSON file plus `_meta`. Lookup order is selected language → English →
the key itself. Every user-facing string must go through `tr()` and have a key in
`locales/en.json`; the tests assert that **every** locale file has exactly the keys of
`en.json` with matching `{placeholders}`, so adding a string means adding it to `en.json`
and to all 13 locale files (other languages may carry the English text until translated).

## Conventions

- Python 3.10+, stdlib plus PySide6 and winsdk only. Don't add dependencies.
- Type hints on public functions; `from __future__ import annotations` everywhere.
- WinRT and registry calls are wrapped in broad `except` on purpose — a flaky media session
  must never take down the UI. Match that when touching `media.py` / `system.py`.
- `migrate_legacy_config()` and `migrate_legacy_autostart()` must run before anything else
  touches `%APPDATA%` (creating the new folder would make migration look unnecessary).
  Add older app names to `LEGACY_APP_NAMES` / `LEGACY_RUN_VALUES` if the app is renamed again.
- Licence is PolyForm Noncommercial 1.0.0 (source-available, not OSI open source).
