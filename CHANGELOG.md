# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- New, brighter app icon: a sound wave on a gradient that sweeps the hue wheel
  around the skin's accent colour, instead of a flat single-colour square. The
  tray icon still follows the active skin.

### Fixed

- With "hide the widget when nothing is playing" on, hiding the widget by hand
  while music played was undone by the next poll a second later. Only a hide the
  idle rule made itself is now undone when a track appears.
- Dragging the opacity slider recreated the widget's window on every step, making
  it flicker; the window is now only rebuilt when its flags actually change.
- A remembered update was offered on every start without GitHub ever being asked
  again, so a release that superseded it was never noticed.
- One media session vanishing mid-read (a player closing at the wrong moment)
  could stop the media thread for good and show the "SMTC failed" error.
- A transport command published its own state in parallel with the poll loop,
  which could scramble position and artwork bookkeeping.
- The tray menu could be replaced, and freed, while it was open; it is now one
  menu refilled each time it opens, so it never shows a stale play/pause label.
- A settings file that was not valid UTF-8, not a JSON object, or had a value of
  the wrong type (`"opacity": "high"`) crashed the app on start instead of
  falling back to defaults. Skin manifests and locale files with similar damage
  (unreadable bytes, a non-numeric font size, `colors` that is not an object)
  no longer crash either.
- The numpad "+" key could be captured as a hotkey but never registered, because
  it was saved as `Num+` and the `+` was read back as a separator. It is now
  saved as `NumPlus`. Keys without a name (saved as `VKE2` and similar) can now
  be registered too.
- Choosing an unsupported hotkey still took the same combination away from the
  action that had it.
- The autostart checkbox stayed ticked when writing the registry entry failed.
- Double-clicking compact mode on/off was not saved until the app quit, and a
  quick double click on the progress bar toggled compact mode.
- The widget repainted 30 times a second whenever title scrolling was enabled,
  even when the title fit and nothing moved.

### Build

- The release workflow refuses a tag that does not match `__version__` in
  `app/__init__.py` (such a build would offer itself as an update forever), and
  manual runs no longer name the installer after the branch.

## [1.2.3] — 2026-08-22

### Fixed

- The widget blinked on every track change. Players drop their media session for
  a few dozen milliseconds between tracks, which was published as a "nothing is
  playing" state — long enough for "hide the widget when nothing is playing" to
  hide and immediately reshow the window. A session is now only given up on after
  it has stayed gone for 1.5 s, and the idle hide waits a further 2 s and
  re-checks before acting.
- The startup update check silently did nothing once it had run earlier the same
  day, so launching an outdated build often reported nothing until the check was
  triggered by hand from Settings → About. The date was also stamped *before* the
  request, so a check that failed offline was not retried until the next day.
  The stamp is now a timestamp written only after a completed check, with a six
  hour interval.

### Added

- An update found by an earlier check is remembered, so a newer version is
  reported right at startup without waiting on the network.

## [1.2.2] — 2026-08-22

### Fixed

- The licence shown by the installer had an unfilled `<YOUR NAME>` placeholder
  where the copyright holder belongs.

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
