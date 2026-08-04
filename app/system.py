"""Small Windows integrations: autostart entry and system volume keys."""

from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Tunetop"

# Autostart entries written by earlier names of the app.
LEGACY_RUN_VALUES = ("AlwaysTopMusic",)

user32 = ctypes.windll.user32

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


def _launch_command() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller build
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    # prefer pythonw.exe so no console window pops up at logon
    windowless = exe.with_name("pythonw.exe")
    if windowless.exists():
        exe = windowless
    entry = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{exe}" "{entry}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Add/remove the HKCU Run entry. Returns True on success."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def migrate_legacy_autostart() -> bool:
    """Rename an autostart entry left by a previous app name.

    Without this an upgraded install would start twice: once under the old value
    and once under the new one. Returns True if an old entry was carried over.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            carried = False
            for legacy in LEGACY_RUN_VALUES:
                try:
                    winreg.QueryValueEx(key, legacy)
                except FileNotFoundError:
                    continue
                winreg.DeleteValue(key, legacy)
                carried = True
            if carried:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            return carried
    except OSError:
        return False


def _tap(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def volume_up(steps: int = 1) -> None:
    for _ in range(max(1, steps)):
        _tap(VK_VOLUME_UP)


def volume_down(steps: int = 1) -> None:
    for _ in range(max(1, steps)):
        _tap(VK_VOLUME_DOWN)


def volume_mute() -> None:
    _tap(VK_VOLUME_MUTE)
