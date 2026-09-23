"""Remux a finished MKV recording to MP4, and find crash-orphaned recordings."""

from __future__ import annotations

import subprocess
from pathlib import Path

from screenrec.recorder.ffmpeg_exe import NO_WINDOW


def remux_to_mp4(mkv_path: Path, ffmpeg_path: str = "ffmpeg") -> Path:
    """Losslessly remux `mkv_path` to an MP4 next to it and return the MP4 path.

    Raises subprocess.CalledProcessError if ffmpeg fails; the source MKV is left
    untouched so the caller can fall back to keeping it.
    """
    mp4_path = mkv_path.with_suffix(".mp4")
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mkv_path),
            "-c",
            "copy",
            # Stopping ends the audio (stdin closed) slightly before the video
            # capture, leaving a short silent-video tail; trim it off here.
            "-shortest",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ],
        check=True,
        creationflags=NO_WINDOW,
    )
    return mp4_path


def find_unfinished_recordings(output_dir: Path) -> list[Path]:
    """MKV files in `output_dir` with no matching finalized MP4 - likely crash leftovers."""
    return sorted(
        mkv_path
        for mkv_path in output_dir.glob("screenrec_*.mkv")
        if not mkv_path.with_suffix(".mp4").exists()
    )
