"""Time-synced lyrics from lrclib.net.

Lookups run on a daemon thread (same pattern as updates.py) and come back as a
Qt signal; results, including "nothing found", are cached for the session so a
track is asked about once. Only artist, title and duration leave the machine,
and only when the user turned lyrics on.
"""

from __future__ import annotations

import bisect
import json
import re
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict

from PySide6.QtCore import QObject, Signal

from . import __version__

SEARCH_URL = "https://lrclib.net/api/search"
USER_AGENT = f"Tunetop {__version__} (https://github.com/PabloSensei/tunetop)"
REQUEST_TIMEOUT = 8.0
CACHE_SIZE = 64
DURATION_TOLERANCE = 4.0  # seconds a candidate's length may differ from the playing track

_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\]", re.IGNORECASE)
# "(Official Video)", "[Lyrics]", "(Remastered 2011)"… that video sites append to titles
_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(official|video|audio|lyrics?|visuali[sz]er|remaster(ed)?|hd|4k|mv)\b"
    r"[^\)\]]*[\)\]]",
    re.IGNORECASE,
)

Lyrics = list  # list[tuple[float, str]]: (start second, line), sorted


def parse_lrc(text: str) -> Lyrics:
    """LRC text -> [(seconds, line)], sorted. Metadata tags are skipped; `[offset:]` applies."""
    lines: list[tuple[float, str]] = []
    offset = 0.0
    for raw in text.splitlines():
        raw = raw.strip()
        match = _OFFSET.match(raw)
        if match:
            offset = int(match.group(1)) / 1000.0
            continue
        stamps = []
        position = 0
        while True:
            match = _TIMESTAMP.match(raw, position)
            if not match:
                break
            minutes, seconds = match.group(1), match.group(2).replace(":", ".")
            stamps.append(int(minutes) * 60 + float(seconds))
            position = match.end()
        if not stamps:
            continue
        words = raw[position:].strip()
        lines.extend((stamp, words) for stamp in stamps)
    # a positive offset means the lyrics should show earlier
    return sorted((max(0.0, stamp - offset), words) for stamp, words in lines)


def line_at(lyrics: Lyrics, position: float) -> tuple[int, str]:
    """(index, text) of the line being sung at `position`; (-1, "") before the first."""
    index = bisect.bisect_right([stamp for stamp, _ in lyrics], position) - 1
    if index < 0:
        return -1, ""
    return index, lyrics[index][1]


def clean_query(artist: str, title: str) -> tuple[str, str]:
    """Undo what video sites do to titles: "Artist - Song (Official Video)" by "Channel"."""
    title = _NOISE.sub("", title).strip()
    if " - " in title and (not artist or artist.lower().endswith(" - topic")
                           or title.lower().startswith(artist.lower() + " - ")):
        artist, title = (part.strip() for part in title.split(" - ", 1))
    if artist.lower().endswith(" - topic"):  # YouTube Music auto-generated channels
        artist = artist[: -len(" - topic")]
    return artist.strip(), title.strip()


def pick_result(results: list, duration: float) -> str:
    """The synced lyrics of the best search hit, or "" if none fits."""
    best, best_gap = "", None
    for item in results:
        if not isinstance(item, dict):
            continue
        synced = item.get("syncedLyrics")
        if not isinstance(synced, str) or not synced.strip():
            continue
        try:
            gap = abs(float(item.get("duration") or 0) - duration) if duration > 0 else 0.0
        except (TypeError, ValueError):
            continue
        if duration > 0 and gap > DURATION_TOLERANCE:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = synced, gap
    return best


def fetch_lyrics(artist: str, title: str, duration: float) -> Lyrics:
    """Raises on network/parse failure; returns [] when there is simply nothing synced."""
    artist, title = clean_query(artist, title)
    if not title:
        return []
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    request = urllib.request.Request(
        f"{SEARCH_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        results = json.loads(response.read().decode("utf-8"))
    if not isinstance(results, list):
        return []
    return parse_lrc(pick_result(results, duration))


class LyricsFetcher(QObject):
    """Looks lyrics up in the background; `ready(key, lyrics)` reports back."""

    ready = Signal(object, object)  # track key, Lyrics ([] if none)

    def __init__(self) -> None:
        super().__init__()
        self._cache: OrderedDict[tuple, Lyrics] = OrderedDict()
        self._pending: set[tuple] = set()
        self._lock = threading.Lock()

    def request(self, key: tuple, artist: str, title: str, duration: float) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                cached = self._cache[key]
            elif key in self._pending:
                return
            else:
                self._pending.add(key)
                cached = None
        if cached is not None:
            self.ready.emit(key, cached)
            return
        threading.Thread(target=self._run, args=(key, artist, title, duration),
                         name="lyrics", daemon=True).start()

    def _run(self, key: tuple, artist: str, title: str, duration: float) -> None:
        try:
            lyrics = fetch_lyrics(artist, title, duration)
        except Exception:  # offline or lrclib down: try again next time the track comes up
            with self._lock:
                self._pending.discard(key)
            return
        with self._lock:
            self._pending.discard(key)
            self._cache[key] = lyrics
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        self.ready.emit(key, lyrics)
