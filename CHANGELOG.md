# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
