"""Locate the ffmpeg executable and launch it without flashing console windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# In the packaged (windowed) app there's no console, so every ffmpeg child would
# otherwise pop up its own console window.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_EXE_NAME = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def bundled_ffmpeg_dir() -> Path | None:
    """Where the installer puts ffmpeg: an `ffmpeg/` folder next to the app exe."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).parent / "ffmpeg"


def find_ffmpeg() -> str:
    """$SCREENREC_FFMPEG, else the bundled copy, else whatever is on PATH."""
    override = os.environ.get("SCREENREC_FFMPEG")
    if override:
        return override
    bundled = bundled_ffmpeg_dir()
    if bundled is not None and (bundled / _EXE_NAME).is_file():
        return str(bundled / _EXE_NAME)
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    raise FileNotFoundError("找不到 ffmpeg，請重新安裝或把 ffmpeg 加入 PATH")
