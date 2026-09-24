"""Integration tests that invoke a real ffmpeg. Skipped when ffmpeg isn't on PATH."""

from __future__ import annotations

import subprocess
from pathlib import Path

from screenrec.recorder.finalize import remux_to_mp4


def _make_test_mkv(
    path: Path, ffmpeg_path: str, duration_sec: float = 1.0, audio_sec: float | None = None
) -> None:
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration_sec}:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            f"sine=duration={audio_sec or duration_sec}",
            "-c:v",
            "mpeg4",  # built into every ffmpeg; libx264 is missing from e.g. Fedora's
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def test_remux_to_mp4_preserves_playable_video_and_audio(
    tmp_path: Path, ffmpeg_path: str, ffprobe_path: str
):
    mkv_path = tmp_path / "screenrec_test.mkv"
    _make_test_mkv(mkv_path, ffmpeg_path)

    mp4_path = remux_to_mp4(mkv_path, ffmpeg_path)

    assert mp4_path.exists()
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream_types = set(probe.stdout.split())
    assert {"video", "audio"} <= stream_types


def _video_duration(path: Path, ffprobe_path: str) -> float:
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(probe.stdout)


def test_remux_trims_video_tail_that_outlasts_the_audio(
    tmp_path: Path, ffmpeg_path: str, ffprobe_path: str
):
    # Stopping a recording ends the audio slightly before the video.
    mkv_path = tmp_path / "screenrec_test.mkv"
    _make_test_mkv(mkv_path, ffmpeg_path, duration_sec=3.0, audio_sec=2.0)

    mp4_path = remux_to_mp4(mkv_path, ffmpeg_path)

    assert _video_duration(mp4_path, ffprobe_path) < 2.3


def test_remux_to_mp4_leaves_source_mkv_in_place(tmp_path: Path, ffmpeg_path: str):
    mkv_path = tmp_path / "screenrec_test.mkv"
    _make_test_mkv(mkv_path, ffmpeg_path)

    remux_to_mp4(mkv_path, ffmpeg_path)

    assert mkv_path.exists()


def test_forcibly_killed_mkv_recording_is_still_readable(
    tmp_path: Path, ffmpeg_path: str, ffprobe_path: str
):
    mkv_path = tmp_path / "screenrec_test.mkv"
    process = subprocess.Popen(
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=10",
            "-c:v",
            "mpeg4",  # built into every ffmpeg; libx264 is missing from e.g. Fedora's
            str(mkv_path),
        ]
    )
    try:
        process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(mkv_path),
        ],
        capture_output=True,
        text=True,
    )
    assert "video" in probe.stdout
