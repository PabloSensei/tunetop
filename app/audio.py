"""Per-application volume through the Windows Core Audio session API.

Plain ctypes COM, since the project takes no dependency beyond PySide6 and
winsdk: walk the default output device's audio sessions, find the ones whose
process belongs to the media session's app, and nudge their volume. That way
the wheel and volume hotkeys turn down Spotify without touching a call or a game.

Every entry point swallows failures and reports "no match" instead, so the
caller can fall back to the system volume keys; like the WinRT bridge, a
misbehaving audio stack must never take down the UI.
"""

from __future__ import annotations

import ctypes
import functools
from ctypes import wintypes
from pathlib import PureWindowsPath

# AUMIDs whose app id has nothing in common with the executable that plays the audio.
PROCESS_ALIASES = {
    "zunemusic": ("microsoft.media.player",),
    "windowsmediaplayer": ("wmplayer",),
}

CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
E_RENDER, E_MULTIMEDIA = 0, 1

# vtable slots (IUnknown takes 0..2)
_ENUM_GET_DEFAULT_ENDPOINT = 4
_DEVICE_ACTIVATE = 3
_MANAGER2_GET_SESSION_ENUMERATOR = 5
_SESSIONS_GET_COUNT = 3
_SESSIONS_GET_SESSION = 4
_CONTROL2_GET_PROCESS_ID = 14
_VOLUME_SET_MASTER = 3
_VOLUME_GET_MASTER = 4
_QUERY_INTERFACE = 0
_RELEASE = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        hexes = text.replace("-", "")
        tail = bytes.fromhex(hexes[16:])
        return cls(int(hexes[:8], 16), int(hexes[8:12], 16), int(hexes[12:16], 16),
                   (ctypes.c_ubyte * 8)(*tail))


CLSID_MMDeviceEnumerator = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = GUID.parse("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID.parse("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_ISimpleAudioVolume = GUID.parse("87CE5498-68D6-44E5-9215-6DA47EF883D8")


def _app_tokens(app_id: str) -> set[str]:
    """Names an AppUserModelId might go by as an executable.

    "Spotify.exe" -> spotify; "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify" ->
    spotifyab.spotifymusic, spotifymusic, spotify; "Chrome" -> chrome.
    """
    tokens: set[str] = set()
    for part in app_id.lower().replace("\\", "/").split("!"):
        part = part.rsplit("/", 1)[-1]
        if part.endswith(".exe"):
            part = part[:-4]
        part = part.split("_", 1)[0]  # package family suffix
        if not part:
            continue
        tokens.add(part)
        tokens.add(part.rsplit(".", 1)[-1])
    for token in list(tokens):
        tokens.update(PROCESS_ALIASES.get(token, ()))
    return {token for token in tokens if len(token) >= 3}


def process_matches(app_id: str, exe_path: str) -> bool:
    """Whether the process at `exe_path` plausibly plays the audio of `app_id`."""
    if not app_id or not exe_path:
        return False
    stem = PureWindowsPath(exe_path).name.lower()
    if stem.endswith(".exe"):
        stem = stem[:-4]
    if len(stem) < 3:
        return False
    return any(stem.startswith(token) or token.startswith(stem) for token in _app_tokens(app_id))


# ------------------------------------------------------------------ COM plumbing

def _method(pointer: ctypes.c_void_p, index: int, *argtypes):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    function = prototype(vtable[index])
    return lambda *args: function(pointer, *args)


def _release(pointer: ctypes.c_void_p | None) -> None:
    if pointer:
        try:
            _method(pointer, _RELEASE)()
        except Exception:
            pass


def _require(pointer: ctypes.c_void_p) -> ctypes.c_void_p:
    """Calling through a NULL interface pointer is an access violation, not an exception."""
    if not pointer.value:
        raise OSError("COM call returned no interface")
    return pointer


def _query(pointer: ctypes.c_void_p, iid: GUID) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    _method(pointer, _QUERY_INTERFACE, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
        ctypes.byref(iid), ctypes.byref(out))
    return _require(out)


@functools.lru_cache(maxsize=1)
def _dlls():
    """Private handles with proper prototypes, leaving the shared ctypes.windll ones alone."""
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.restype = ctypes.HRESULT
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    ole32.CoCreateInstance.argtypes = (ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return ole32, kernel32


def _process_path(kernel32, pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _session_volumes(app_id: str) -> list[ctypes.c_void_p]:
    """ISimpleAudioVolume pointers of every render session belonging to `app_id`.

    The caller owns (and must release) what is returned.
    """
    ole32, kernel32 = _dlls()
    try:
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except OSError:
        pass  # RPC_E_CHANGED_MODE: COM is already up on this thread, which is all we need
    enumerator = ctypes.c_void_p()
    device = ctypes.c_void_p()
    manager = ctypes.c_void_p()
    sessions = ctypes.c_void_p()
    found: list[ctypes.c_void_p] = []
    try:
        ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                               ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enumerator))
        _require(enumerator)
        _method(enumerator, _ENUM_GET_DEFAULT_ENDPOINT, ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p))(E_RENDER, E_MULTIMEDIA, ctypes.byref(device))
        _require(device)
        _method(device, _DEVICE_ACTIVATE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, ctypes.byref(manager))
        _require(manager)
        _method(manager, _MANAGER2_GET_SESSION_ENUMERATOR, ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(sessions))
        _require(sessions)
        count = ctypes.c_int()
        _method(sessions, _SESSIONS_GET_COUNT, ctypes.POINTER(ctypes.c_int))(ctypes.byref(count))
        for index in range(count.value):
            control = ctypes.c_void_p()
            control2 = ctypes.c_void_p()
            try:
                _method(sessions, _SESSIONS_GET_SESSION, ctypes.c_int,
                        ctypes.POINTER(ctypes.c_void_p))(index, ctypes.byref(control))
                _require(control)
                control2 = _query(control, IID_IAudioSessionControl2)
                pid = wintypes.DWORD()
                _method(control2, _CONTROL2_GET_PROCESS_ID, ctypes.POINTER(wintypes.DWORD))(
                    ctypes.byref(pid))
                if pid.value and process_matches(app_id, _process_path(kernel32, pid.value)):
                    found.append(_query(control, IID_ISimpleAudioVolume))
            except OSError:
                pass  # one odd session (system sounds, a process that just exited)
            finally:
                _release(control2)
                _release(control)
    except OSError:
        pass
    finally:
        for pointer in (sessions, manager, device, enumerator):
            _release(pointer)
    return found


def app_volume_step(app_id: str, delta: float) -> float | None:
    """Move the volume of `app_id`'s audio sessions by `delta` (0..1 scale).

    Returns the new level of the loudest matching session, or None when the
    app has no audio session (or anything at all went wrong).
    """
    try:
        volumes = _session_volumes(app_id)
    except Exception:
        return None
    if not volumes:
        return None
    level = None
    try:
        current = []
        for volume in volumes:
            value = ctypes.c_float()
            _method(volume, _VOLUME_GET_MASTER, ctypes.POINTER(ctypes.c_float))(ctypes.byref(value))
            current.append(value.value)
        level = max(0.0, min(1.0, max(current) + delta))
        for volume in volumes:
            _method(volume, _VOLUME_SET_MASTER, ctypes.c_float, ctypes.c_void_p)(level, None)
    except Exception:
        level = None
    finally:
        for volume in volumes:
            _release(volume)
    return level
