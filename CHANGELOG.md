# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] — 2026-08-22

### Fixed

- Album art could keep showing the previous track's cover after a track change.
  Artwork was cached under a key built from the track metadata and read exactly
  once, but players such as Feishin publish the new title before the new
  thumbnail — so that single read returned the old cover and it stuck until the
  next track. The thumbnail is now re-read for a few polls after a metadata
  change, until it stops matching the previous track, and the artwork key
  includes a digest of the image bytes so late-arriving covers still trigger a
  repaint.
- The media session was detached and re-subscribed once per second. WinRT returns
  a fresh wrapper object from every `get_current_session()` call, so the identity
  check in `_rebind` never matched; sessions are now compared by their app id.
- The progress bar stuck at a fixed second instead of following the song. Players
  such as Feishin publish their timeline once per track and never refresh it, and
  every poll re-stamped that stale reading as if it were current, cancelling the
  interpolation. Readings are now only trusted when their `last_updated_time`
  changes; otherwise Tunetop runs its own clock. Blanked timelines (a zeroed
  duration, or the FILETIME epoch of 1601 in place of a timestamp) are ignored
  rather than taken at face value, which previously produced positions billions
  of seconds long after a seek.
- With "hide the widget when nothing is playing" enabled, showing the widget by
  hand (hotkey, tray, second launch) hid it again on the next poll a second
  later. An explicit show now sticks until a track actually appears.

### Added

- Feishin is recognised by name in the source picker.

## [1.2.0] — 2026-08-05

### Added

- Update check: on startup (once a day) and on demand from Settings → About,
  Tunetop checks the GitHub releases page for a newer version and offers to
  download it, with an option to skip a specific version. Can be turned off
  in the settings.
- New app icon (a note glyph on a gradient rounded square, tinted with the active
  skin's accent) used for the tray icon, window icons and the built .exe, plus a
  matching fix for a fill-rule bug that punched a small crescent-shaped hole where
  the note's stem met its head — also visible in the widget's "no album art"
  placeholder.
- Windows installer (`TunetopSetup-<version>.exe`, built with Inno Setup) is now
  published alongside the standalone `Tunetop.exe` on every release. A raw
  PyInstaller `--onefile` exe is a common false-positive trigger for antivirus
  heuristics; the installer is the recommended way to get Tunetop.

## [1.1.0] — 2026-08-04

### Added

- Two new bundled skins: **Minimal Dark** and **Minimal Light** — flat, minimalist
  skins with no drop shadow (`shadow: 0`), using a thin 1px border for edge
  definition instead of a blurred shadow.

## [1.0.1] — 2026-08-04

### Fixed

- `tests/test_basics.py` crashed on Windows runners whose console defaults to
  `cp1252` (non-ASCII locale names such as `Español` or `日本語` could not be
  printed). Output is now forced to UTF-8.
- Replaced a leftover Russian word in the `docs/skins.png` screenshot used by
  the README.

## [1.0.0] — 2026-08-03

First release.

### Added

- Always-on-top frameless widget with previous / play-pause / next, album art,
  title and artist, drawn entirely with QPainter.
- Control of any app registered with the Windows System Media Transport Controls
  (Spotify, browsers, foobar2000, AIMP, MusicBee, VLC, Media Player, …).
- Track progress bar with click-to-seek for sources that publish a timeline.
- Skin system: a folder with `skin.json` (colours with alpha, sizes, fonts, corner
  radius, shadow, background image, custom icons) plus `extends` inheritance.
  Bundled skins: Dark, Light, Neon, Glass.
- 13 interface languages, following the Windows language by default, switchable
  at runtime. User locales can be dropped into `%APPDATA%\Tunetop\locales`.
- Global hotkeys via `RegisterHotKey` with in-place capture, conflict detection
  between actions, and a tray warning when Windows refuses a combination.
- Tray icon with the current track in its tooltip and a full command menu.
- Source picker: follow the current Windows player or pin a specific app.
- Compact mode, snapping to screen edges, opacity, position lock, scrolling titles,
  mouse wheel volume, hide-when-idle.
- Start with Windows, start minimized to tray, single-instance guard.
