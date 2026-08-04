"""Tunetop — entry point."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.application import run  # noqa: E402


def main() -> int:
    try:  # own taskbar/tray identity instead of "Python"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Tunetop.Widget")
    except Exception:
        pass
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
