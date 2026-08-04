"""System-wide hotkeys through the Win32 RegisterHotKey API.

Hotkeys are stored as human readable strings ("Ctrl+Alt+M", "Media Play") so the
settings file stays hand-editable. WM_HOTKEY messages are picked up by a native
event filter installed on the QApplication.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QWidget

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

MODIFIER_FLAGS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}

# Canonical display order of modifiers.
MODIFIER_ORDER = ["Ctrl", "Alt", "Shift", "Win"]

NAME_TO_VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "pause": 0x13,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pgup": 0x21, "pageup": 0x21,
    "pgdown": 0x22, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
    "numlock": 0x90, "scrolllock": 0x91, "capslock": 0x14,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "media play": 0xB3, "media next": 0xB0, "media prev": 0xB1, "media stop": 0xB2,
    "volume up": 0xAF, "volume down": 0xAE, "volume mute": 0xAD,
}
for _i in range(10):
    NAME_TO_VK[str(_i)] = 0x30 + _i
for _i in range(26):
    NAME_TO_VK[chr(ord("a") + _i)] = 0x41 + _i
for _i in range(1, 25):
    NAME_TO_VK[f"f{_i}"] = 0x6F + _i

VK_TO_NAME: dict[int, str] = {}
for _name, _vk in NAME_TO_VK.items():
    VK_TO_NAME.setdefault(_vk, _name.title() if len(_name) > 1 else _name.upper())
VK_TO_NAME.update({0x0D: "Enter", 0x1B: "Esc", 0x2E: "Del", 0x2D: "Ins", 0x21: "PgUp",
                   0x22: "PgDown", 0x20: "Space", 0x09: "Tab", 0x08: "Backspace"})


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """"Ctrl+Alt+M" -> (modifier flags, virtual key code). None if unparsable."""
    if not text or not text.strip():
        return None
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        # the key itself is "+"
        parts = ["="]
    mods = 0
    key = None
    for part in parts:
        flag = MODIFIER_FLAGS.get(part.lower())
        if flag:
            mods |= flag
        else:
            key = part
    if key is None:
        return None
    vk = NAME_TO_VK.get(key.lower())
    if vk is None and len(key) == 1:
        vk = ord(key.upper())
    if vk is None:
        return None
    return mods, vk


def format_hotkey(mods: int, vk: int) -> str:
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    name = VK_TO_NAME.get(vk)
    if name is None:
        name = chr(vk) if 0x20 < vk < 0x7F else f"VK{vk:02X}"
    parts.append(name)
    return "+".join(parts)


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers hotkeys and emits `triggered(action)` when one fires."""

    triggered = Signal(str)
    conflict = Signal(str, str)  # action, hotkey text

    def __init__(self, app) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._app = app
        self._sink = QWidget()
        self._sink.setWindowTitle("Tunetop hotkey sink")
        self._hwnd = int(self._sink.winId())  # forces native handle creation
        self._registered: dict[int, str] = {}
        self._next_id = 0xB000
        app.installNativeEventFilter(self)

    # -- registration -----------------------------------------------------

    def apply(self, hotkeys: dict[str, str], enabled: bool = True) -> list[tuple[str, str]]:
        """Re-register the whole set. Returns [(action, text)] that failed."""
        self.unregister_all()
        failures: list[tuple[str, str]] = []
        if not enabled:
            return failures
        for action, text in hotkeys.items():
            if not text:
                continue
            parsed = parse_hotkey(text)
            if parsed is None:
                failures.append((action, text))
                continue
            mods, vk = parsed
            hotkey_id = self._next_id
            self._next_id += 1
            ok = user32.RegisterHotKey(
                wintypes.HWND(self._hwnd), hotkey_id, mods | MOD_NOREPEAT, vk
            )
            if ok:
                self._registered[hotkey_id] = action
            else:
                failures.append((action, text))
                self.conflict.emit(action, text)
        return failures

    def unregister_all(self) -> None:
        for hotkey_id in list(self._registered):
            user32.UnregisterHotKey(wintypes.HWND(self._hwnd), hotkey_id)
        self._registered.clear()

    def shutdown(self) -> None:
        self.unregister_all()
        try:
            self._app.removeNativeEventFilter(self)
        except Exception:
            pass
        self._sink.deleteLater()

    # -- message pump -----------------------------------------------------

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt naming)
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                action = self._registered.get(int(msg.wParam))
                if action:
                    self.triggered.emit(action)
                    return True, 0
        return False, 0
