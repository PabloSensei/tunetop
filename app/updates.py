"""Checks GitHub Releases for a newer Tunetop version.

The network request runs on a plain daemon thread (same pattern as
`MediaController` in media.py) and reports back to the GUI thread via Qt
signals — a slow or unreachable GitHub must never stall the UI.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from . import __version__
from .config import Settings
from .i18n import tr

REPO = "PabloSensei/tunetop"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
REQUEST_TIMEOUT = 8.0


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" / "1.2.3-beta" -> (1, 2, 3). Non-numeric trailing bits are ignored."""
    text = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in text.split(".")[:4]:
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


@dataclass
class ReleaseInfo:
    version: str
    url: str


def fetch_latest_release() -> ReleaseInfo:
    """Raises on any network/parsing failure — callers decide how to report it."""
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Tunetop"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release has no tag_name")
    url = str(data.get("html_url") or RELEASES_PAGE_URL)
    return ReleaseInfo(version=tag.lstrip("vV"), url=url)


class UpdateChecker(QObject):
    """One-shot background release check; safe to fire-and-forget."""

    available = Signal(object)  # ReleaseInfo — a newer version exists
    up_to_date = Signal()  # checked fine, already on the latest
    failed = Signal(str)

    def __init__(self, current_version: str = __version__) -> None:
        super().__init__()
        self._current_version = current_version

    def start(self) -> None:
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def _run(self) -> None:
        try:
            release = fetch_latest_release()
        except Exception as exc:  # network is inherently flaky; never raise into the caller
            self.failed.emit(str(exc))
            return
        if is_newer(release.version, self._current_version):
            self.available.emit(release)
        else:
            self.up_to_date.emit()


def offer_update(parent: QWidget | None, settings: Settings, release: ReleaseInfo) -> None:
    """Show the "a new version is available" dialog and act on the user's choice."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(tr("update.title"))
    box.setText(tr("update.available_text", version=release.version, current=__version__))
    download = box.addButton(tr("update.download"), QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton(tr("update.skip"), QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(tr("update.later"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(download)
    box.exec()
    clicked = box.clickedButton()
    if clicked is download:
        QDesktopServices.openUrl(QUrl(release.url))
    elif clicked is skip:
        settings.skipped_update_version = release.version
        settings.save()
