from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        pytest.skip("ffmpeg not found on PATH")
    return path


@pytest.fixture
def ffprobe_path(ffmpeg_path: str) -> str:
    # Derive from the resolved ffmpeg binary's own directory - a naive string
    # replace on the path is unsafe when an install directory also contains
    # "ffmpeg" (e.g. ".../FFmpeg/ffmpeg-4.3.2-full_build/bin/ffmpeg.exe").
    candidate = Path(ffmpeg_path).with_name(Path(ffmpeg_path).name.replace("ffmpeg", "ffprobe"))
    if not candidate.exists():
        pytest.skip(f"ffprobe not found next to ffmpeg at {candidate}")
    return str(candidate)
