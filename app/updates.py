"""Checks GitHub Releases for a newer Tunetop version, and installs it.

Network requests run on plain daemon threads (same pattern as
`MediaController` in media.py) and report back to the GUI thread via Qt
signals — a slow or unreachable GitHub must never stall the UI.

Self-update only applies to the installed build: the release's
`TunetopSetup-X.Y.Z.exe` is downloaded, checked against the `.sha256` file
published next to it, and run silently; the installer closes this process,
replaces the exe and starts the new version. The portable exe can't be
replaced while it runs, so it is pointed at the releases page instead.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

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
# How long a completed check stays good for. Startup still reports an already
# known update immediately, so this only limits how often GitHub is asked.
CHECK_INTERVAL = timedelta(hours=6)
INSTALLER_PREFIX = "TunetopSetup-"
DOWNLOAD_CHUNK = 64 * 1024
# Inno Setup switches: no wizard pages or prompts, close the running Tunetop
# instead of asking, and (our own /restartapp, see Tunetop.iss) start it again.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                  "/restartapp=1")


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


def check_is_due(last_check: str, now: datetime | None = None) -> bool:
    """True when the last completed check is old enough to run another one.

    Tolerates the plain "YYYY-MM-DD" that versions up to 1.2.2 wrote, and treats
    anything unparseable as "never checked".
    """
    if not last_check:
        return True
    try:
        stamp = datetime.fromisoformat(last_check)
    except ValueError:
        return True
    return (now or datetime.now()) - stamp >= CHECK_INTERVAL


def check_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class ReleaseInfo:
    version: str
    url: str
    installer_url: str = ""
    checksum_url: str = ""


def parse_release(data: dict) -> ReleaseInfo:
    """A GitHub "latest release" payload -> ReleaseInfo. Raises ValueError if unusable."""
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release has no tag_name")
    installer = checksum = ""
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        link = str(asset.get("browser_download_url") or "")
        if not name.startswith(INSTALLER_PREFIX.lower()) or not link.startswith("https://"):
            continue
        if name.endswith(".exe"):
            installer = link
        elif name.endswith(".exe.sha256"):
            checksum = link
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or RELEASES_PAGE_URL),
        installer_url=installer,
        checksum_url=checksum,
    )


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "Tunetop"})
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)


def fetch_latest_release() -> ReleaseInfo:
    """Raises on any network/parsing failure — callers decide how to report it."""
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Tunetop"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected release payload")
    return parse_release(data)


def parse_checksum(text: str) -> str:
    """The digest from a `sha256sum`-style line ("<hex>  <name>"); "" if there is none."""
    token = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    if len(token) == 64 and all(ch in "0123456789abcdef" for ch in token):
        return token
    return ""


def installed_build() -> bool:
    """True for the exe the installer put in place (it can replace itself).

    Inno Setup always leaves its uninstaller next to the program; the portable
    exe and a source checkout have none.
    """
    if not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).resolve().parent / "unins000.exe").exists()


def launch_installer(path: Path) -> bool:
    """Start the downloaded installer detached from this process. True on success."""
    try:
        subprocess.Popen([str(path), *INSTALLER_ARGS], close_fds=True)
        return True
    except OSError:
        return False


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


class UpdateDownloader(QObject):
    """Downloads and verifies a release installer on a background thread."""

    progress = Signal(int, int)  # bytes received, total (0 if unknown)
    finished = Signal(object, object)  # Path of the verified installer, ReleaseInfo
    failed = Signal(str)

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self._release = release
        self._cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, name="update-download", daemon=True).start()

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        try:
            release = self._release
            if not (release.installer_url and release.checksum_url):
                # e.g. an update remembered from an earlier run, known by version only
                release = fetch_latest_release()
            if not (release.installer_url and release.checksum_url):
                raise ValueError(tr("update.no_installer"))
            with _open(release.checksum_url) as response:
                expected = parse_checksum(response.read(4096).decode("utf-8", "replace"))
            if not expected:
                raise ValueError(tr("update.no_installer"))
            path = self._download(release, expected)
        except Exception as exc:  # network is inherently flaky; never raise into the caller
            if not self._cancelled:
                self.failed.emit(str(exc))
            return
        if not self._cancelled:
            self.finished.emit(path, release)

    def _download(self, release: ReleaseInfo, expected: str) -> Path:
        folder = Path(tempfile.gettempdir()) / "Tunetop-update"
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob(INSTALLER_PREFIX + "*"):
            try:
                stale.unlink()
            except OSError:
                pass
        target = folder / f"{INSTALLER_PREFIX}{release.version}.exe"
        partial = target.with_suffix(".part")
        digest = hashlib.sha256()
        with _open(release.installer_url) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            while True:
                if self._cancelled:
                    raise InterruptedError("cancelled")
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                self.progress.emit(received, total)
        if digest.hexdigest() != expected:
            partial.unlink(missing_ok=True)
            raise ValueError(tr("update.checksum_mismatch"))
        partial.replace(target)
        return target


def offer_update(parent: QWidget | None, settings: Settings, release: ReleaseInfo) -> bool:
    """Show the "a new version is available" dialog and act on the user's choice.

    Returns True when the user asked to install the update right away (only
    offered by the installed build); the caller then runs `install_update`.
    """
    can_install = installed_build()
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(tr("update.title"))
    key = "update.available_install" if can_install else "update.available_text"
    box.setText(tr(key, version=release.version, current=__version__))
    accept = box.addButton(tr("update.install" if can_install else "update.download"),
                           QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton(tr("update.skip"), QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(tr("update.later"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(accept)
    box.exec()
    clicked = box.clickedButton()
    if clicked is accept:
        if can_install:
            return True
        QDesktopServices.openUrl(QUrl(release.url))
    elif clicked is skip:
        settings.skipped_update_version = release.version
        settings.save()
    return False
