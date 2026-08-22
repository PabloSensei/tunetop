"""Windows SMTC (System Media Transport Controls) bridge.

Runs an asyncio loop on a background thread, listens to WinRT session events and
pushes immutable snapshots of the playback state to the Qt side via signals.
Works with any app that registers a media session: Spotify, browsers, foobar2000,
AIMP, VLC, Media Player, etc.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
)
from winsdk.windows.storage.streams import DataReader

# Some players (Electron ones especially) publish the new title before the new
# thumbnail, so a single read right after a track change hands back the previous
# cover. Keep re-reading for a few polls until the artwork catches up.
ART_SETTLE_POLLS = 5

# GlobalSystemMediaTransportControlsSessionPlaybackStatus
STATUS_NAMES = {
    0: "closed",
    1: "opened",
    2: "changing",
    3: "stopped",
    4: "playing",
    5: "paused",
}

# Pretty names for the source picker; matched case-insensitively as a substring.
KNOWN_SOURCES = {
    "spotify": "Spotify",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Mozilla Firefox",
    "opera": "Opera",
    "brave": "Brave",
    "yandex": "Yandex",
    "vivaldi": "Vivaldi",
    "zen": "Zen Browser",
    "vlc": "VLC",
    "aimp": "AIMP",
    "foobar2000": "foobar2000",
    "musicbee": "MusicBee",
    "feishin": "Feishin",
    "winamp": "Winamp",
    "itunes": "iTunes",
    "zunemusic": "Media Player",
    "windowsmediaplayer": "Windows Media Player",
    "deezer": "Deezer",
    "tidal": "TIDAL",
    "youtube": "YouTube Music",
    "telegram": "Telegram",
    "discord": "Discord",
    "steam": "Steam",
    "mpc-hc": "MPC-HC",
    "potplayer": "PotPlayer",
}


def friendly_source_name(app_id: str) -> str:
    """Turn an AppUserModelId into something a human wants to read."""
    if not app_id:
        return "—"
    low = app_id.lower()
    for key, name in KNOWN_SOURCES.items():
        if key in low:
            return name
    name = app_id.split("!")[-1].split("_")[0]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name or app_id


@dataclass
class PlayerState:
    """Snapshot of the currently controlled media session."""

    app_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    status: str = "closed"
    can_play: bool = False
    can_pause: bool = False
    can_next: bool = False
    can_prev: bool = False
    can_seek: bool = False
    position: float = 0.0
    duration: float = 0.0
    captured_at: float = field(default_factory=time.monotonic)
    art: bytes | None = None
    art_key: str = ""
    connected: bool = False

    @property
    def playing(self) -> bool:
        return self.status == "playing"

    @property
    def has_track(self) -> bool:
        return self.connected and bool(self.title or self.artist)

    def live_position(self) -> float:
        """Position interpolated between polls so the progress bar moves smoothly."""
        if not self.duration:
            return 0.0
        pos = self.position
        if self.playing:
            pos += time.monotonic() - self.captured_at
        return max(0.0, min(pos, self.duration))

    def identity(self) -> tuple:
        """Fields that matter for redraw decisions (position excluded)."""
        return (
            self.app_id, self.title, self.artist, self.status, self.can_play,
            self.can_pause, self.can_next, self.can_prev, self.art_key, self.connected,
        )


def _timeline_stamp(tl):
    """The timeline's last_updated_time, or None when the player blanked it.

    Players that reset their timeline report the FILETIME epoch (1601) rather
    than an empty value, which would otherwise read as a centuries-old report.
    """
    try:
        updated = tl.last_updated_time
    except Exception:
        return None
    if updated is None or updated.year < 2000:
        return None
    return updated


async def _read_thumbnail(props) -> bytes | None:
    ref = props.thumbnail
    if ref is None:
        return None
    try:
        stream = await ref.open_read_async()
        size = stream.size
        if not size:
            return None
        reader = DataReader(stream)
        await reader.load_async(size)
        return bytes(reader.read_buffer(size))
    except Exception:
        return None


class MediaController(QObject):
    """Qt-facing facade over the WinRT session manager."""

    state_changed = Signal(object)  # PlayerState
    sources_changed = Signal(object)  # list[dict(app_id=..., name=..., playing=bool)]
    failed = Signal(str)

    def __init__(self, source_mode: str = "auto", pinned_source: str = "") -> None:
        super().__init__()
        self._source_mode = source_mode
        self._pinned_source = pinned_source
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._manager = None
        self._session = None
        self._session_key = ""
        self._events_session = None
        self._tokens: list[tuple[str, object]] = []
        self._mgr_tokens: list[tuple[str, object]] = []
        self._wake: asyncio.Event | None = None
        self._stopping = False
        self._art_key = ""
        self._art_meta_key = ""
        self._art: bytes | None = None
        self._art_previous: bytes | None = None
        self._art_retries = 0
        self._pos = 0.0
        self._pos_at = 0.0
        self._pos_updated: datetime | None = None
        self._pos_playing = False
        self._duration = 0.0
        self._last_sources: list[dict] = []
        self.state = PlayerState()

    # ------------------------------------------------------------------ public

    @property
    def sources(self) -> list[dict]:
        """Last known media sessions (app_id / name / playing)."""
        return list(self._last_sources)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="smtc", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stopping = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    def set_source(self, mode: str, pinned: str = "") -> None:
        self._source_mode = mode
        self._pinned_source = pinned
        self._reset_art()  # force artwork refresh for the new source
        self._wake_loop()

    def command(self, action: str, value: float | None = None) -> None:
        """Fire a transport command (play_pause/next/prev/play/pause/stop/seek)."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._do_command(action, value), loop)

    def refresh(self) -> None:
        self._wake_loop()

    # ------------------------------------------------------------------ thread

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except RuntimeError:
            pass  # loop.stop() during shutdown
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run(self) -> None:
        self._wake = asyncio.Event()
        try:
            self._manager = await SessionManager.request_async()
        except Exception as exc:
            self.failed.emit(str(exc))  # the UI layer wraps this in a localised message
            return

        self._mgr_tokens = [
            ("sessions", self._manager.add_sessions_changed(self._on_manager_event)),
            ("current", self._manager.add_current_session_changed(self._on_manager_event)),
        ]

        await self._rebind()
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                self._wake.clear()
                await self._rebind()
            except asyncio.TimeoutError:
                await self._rebind(events_only=False)

    def _wake_loop(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is None or wake is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(wake.set)

    # ------------------------------------------------------------------ events

    def _on_manager_event(self, sender, args) -> None:
        self._wake_loop()

    def _on_session_event(self, sender, args) -> None:
        self._wake_loop()

    # ------------------------------------------------------------------ polling

    def _pick_session(self):
        sessions = list(self._manager.get_sessions())
        current = self._manager.get_current_session()

        payload = []
        for s in sessions:
            try:
                status = STATUS_NAMES.get(int(s.get_playback_info().playback_status), "closed")
            except Exception:
                status = "closed"
            payload.append(
                {
                    "app_id": s.source_app_user_model_id,
                    "name": friendly_source_name(s.source_app_user_model_id),
                    "playing": status == "playing",
                }
            )
        if payload != self._last_sources:
            self._last_sources = payload
            self.sources_changed.emit(payload)

        if self._source_mode == "pinned" and self._pinned_source:
            for s in sessions:
                if s.source_app_user_model_id == self._pinned_source:
                    return s
            return None
        return current

    async def _rebind(self, events_only: bool = True) -> None:
        if self._manager is None:
            return
        try:
            session = self._pick_session()
        except Exception:
            session = None

        # WinRT hands back a fresh wrapper on every call, so identity would flap
        # once per poll; the app id is what actually tells sessions apart.
        try:
            key = session.source_app_user_model_id if session is not None else ""
        except Exception:
            session, key = None, ""
        self._session = session  # always keep the newest wrapper
        if key != self._session_key:
            self._detach_session()
            self._session_key = key
            self._reset_art()
            self._reset_position()
            if session is not None:
                try:
                    self._tokens = [
                        ("props", session.add_media_properties_changed(self._on_session_event)),
                        ("playback", session.add_playback_info_changed(self._on_session_event)),
                        ("timeline", session.add_timeline_properties_changed(self._on_session_event)),
                    ]
                    self._events_session = session
                except Exception:
                    self._tokens = []
                    self._events_session = None
        await self._publish()

    def _detach_session(self) -> None:
        session = self._events_session
        self._events_session = None
        if session is None:
            return
        for kind, token in self._tokens:
            try:
                if kind == "props":
                    session.remove_media_properties_changed(token)
                elif kind == "playback":
                    session.remove_playback_info_changed(token)
                else:
                    session.remove_timeline_properties_changed(token)
            except Exception:
                pass
        self._tokens = []

    def _reset_position(self) -> None:
        self._pos = 0.0
        self._pos_at = 0.0
        self._pos_updated = None
        self._pos_playing = False
        self._duration = 0.0

    def _track_duration(self, duration: float) -> float:
        """Hold on to the last real duration; some players blank it while paused."""
        if duration > 0:
            self._duration = duration
        return self._duration

    def _report_age(self, updated, playing: bool, duration: float) -> float:
        """How long ago a timeline report was made, if that is worth trusting."""
        if updated is None or not playing:
            return 0.0
        try:
            age = (datetime.now(timezone.utc) - updated).total_seconds()
        except Exception:
            return 0.0
        limit = duration if duration > 0 else 3600.0
        return age if 0.0 <= age <= limit else 0.0

    def _advance_position(self, raw: float, updated, duration: float,
                          playing: bool, usable: bool) -> float:
        """Track the playback position even when the player stops publishing it.

        Several players (Feishin, some Electron apps) push their timeline once per
        track and never refresh it, so the reported position sits at whatever it
        was when the track started, and blank it out entirely while paused. A
        reading is only trusted when it is usable and its ``last_updated_time``
        has changed; the rest of the time we run our own clock.
        """
        now = time.monotonic()
        if not usable:
            if self._pos_playing and self._pos_at:
                self._pos += now - self._pos_at  # keep going on a blanked timeline
        elif updated is None or updated != self._pos_updated:
            self._pos_updated = updated
            self._pos = raw + self._report_age(updated, playing, duration)
        elif self._pos_playing:
            self._pos += now - self._pos_at
        if duration > 0:
            self._pos = min(self._pos, duration)
        self._pos = max(0.0, self._pos)
        self._pos_at = now
        self._pos_playing = playing
        return self._pos

    def _reset_art(self) -> None:
        self._art_key = ""
        self._art_meta_key = ""
        self._art = None
        self._art_previous = None
        self._art_retries = 0

    async def _read_art(self, session, props) -> None:
        """Re-read the thumbnail, retrying while it still shows the previous track."""
        try:
            if props is None:
                props = await session.try_get_media_properties_async()
            art = await _read_thumbnail(props)
        except Exception:
            art = None
        if self._art_retries > 0:
            self._art_retries -= 1
        if art is not None and art != self._art_previous:
            self._art_previous = None  # the player caught up; stop re-reading
            self._art_retries = 0
        self._art = art
        digest = hashlib.sha1(art).hexdigest()[:12] if art else "none"
        self._art_key = f"{self._art_meta_key}|{digest}"

    async def _publish(self) -> None:
        session = self._session
        if session is None:
            state = PlayerState(
                app_id=self._pinned_source if self._source_mode == "pinned" else "",
                connected=False,
            )
            self.state = state
            self.state_changed.emit(state)
            return

        state = PlayerState(app_id=session.source_app_user_model_id, connected=True)
        props = None
        try:
            props = await session.try_get_media_properties_async()
            state.title = props.title or ""
            state.artist = props.artist or ""
            state.album = props.album_title or ""
        except Exception:
            pass

        meta_key = f"{state.app_id}|{state.title}|{state.artist}|{state.album}"
        new_track = meta_key != self._art_meta_key

        try:
            info = session.get_playback_info()
            state.status = STATUS_NAMES.get(int(info.playback_status), "closed")
            controls = info.controls
            state.can_play = bool(controls.is_play_enabled)
            state.can_pause = bool(controls.is_pause_enabled)
            state.can_next = bool(controls.is_next_enabled)
            state.can_prev = bool(controls.is_previous_enabled)
            state.can_seek = bool(controls.is_playback_position_enabled)
        except Exception:
            pass

        if new_track:
            self._reset_position()
        try:
            tl = session.get_timeline_properties()
            start = tl.start_time.total_seconds()
            duration = max(0.0, tl.end_time.total_seconds() - start)
            raw_position = max(0.0, tl.position.total_seconds() - start)
            updated = _timeline_stamp(tl)
        except Exception:
            duration, raw_position, updated = 0.0, 0.0, None
        state.duration = self._track_duration(duration)
        state.position = self._advance_position(
            raw_position, updated, state.duration, state.playing, usable=duration > 0
        )

        if new_track:
            self._art_meta_key = meta_key
            self._art_previous = self._art  # what the *previous* track looked like
            self._art_retries = ART_SETTLE_POLLS
            await self._read_art(session, props)
        elif self._art_retries > 0:
            await self._read_art(session, props)
        state.art = self._art
        state.art_key = self._art_key
        state.captured_at = time.monotonic()

        self.state = state
        self.state_changed.emit(state)

    # ------------------------------------------------------------------ commands

    async def _do_command(self, action: str, value: float | None) -> None:
        session = self._session
        if session is None:
            return
        try:
            if action == "play_pause":
                await session.try_toggle_play_pause_async()
            elif action == "play":
                await session.try_play_async()
            elif action == "pause":
                await session.try_pause_async()
            elif action == "stop":
                await session.try_stop_async()
            elif action == "next_track":
                await session.try_skip_next_async()
            elif action == "prev_track":
                await session.try_skip_previous_async()
            elif action == "seek" and value is not None:
                await session.try_change_playback_position_async(int(value * 10_000_000))
                self._reset_position()  # take the player's word for it after a seek
        except Exception:
            return
        await asyncio.sleep(0.15)
        await self._publish()
