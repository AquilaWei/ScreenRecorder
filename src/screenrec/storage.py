"""Output filenames, free-space checks, and filesystem constraints."""

from __future__ import annotations

import ctypes
import shutil
import sys
from datetime import datetime
from pathlib import Path

FAT32_MAX_FILE_BYTES = 4 * 1024**3 - 1


def default_filename(now: datetime | None = None, extension: str = "mkv") -> str:
    now = now or datetime.now()
    return f"screenrec_{now:%Y-%m-%d_%H%M%S}.{extension}"


def free_space_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def estimate_recordable_seconds(free_bytes: int, total_bitrate_kbps: int) -> float:
    if total_bitrate_kbps <= 0:
        raise ValueError("total_bitrate_kbps must be positive")
    bytes_per_second = total_bitrate_kbps * 1000 / 8
    return free_bytes / bytes_per_second


def filesystem_name(path: Path) -> str | None:
    """Best-effort filesystem name for the drive containing `path` (Windows only)."""
    if sys.platform != "win32":
        return None
    root = str(Path(path).resolve().anchor)
    volume_name_buf = ctypes.create_unicode_buffer(261)
    fs_name_buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), volume_name_buf, 260, None, None, None, fs_name_buf, 260
    )
    if not ok:
        return None
    return fs_name_buf.value or None


def is_fat32(path: Path) -> bool:
    """True if `path`'s filesystem caps single files at 4 GiB (FAT32)."""
    return filesystem_name(path) == "FAT32"
