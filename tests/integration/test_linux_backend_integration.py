"""LinuxBackend with real gst-launch-1.0 and ffmpeg, but test sources standing in
for the portal's PipeWire stream and the PulseAudio monitor - neither exists on
a headless CI runner. The portal itself needs a real desktop session and is
verified by hand."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux backend")


@pytest.fixture
def gst_launch() -> str:
    path = shutil.which("gst-launch-1.0")
    if path is None:
        pytest.skip("gst-launch-1.0 not found on PATH")
    return path


@pytest.fixture
def backend(monkeypatch, ffmpeg_path: str, gst_launch: str):
    from screenrec.recorder import linux
    from screenrec.recorder.portal import ScreenStream

    real_build_gst_args = linux.build_gst_args

    def with_test_sources(*args, **kwargs) -> list[str]:
        gst_args = real_build_gst_args(*args, **kwargs)
        video = gst_args.index("pipewiresrc")
        gst_args[video : gst_args.index("!", video)] = ["videotestsrc", "is-live=true"]
        audio = gst_args.index("pulsesrc")
        gst_args[audio : gst_args.index("!", audio)] = ["audiotestsrc", "is-live=true"]
        return gst_args

    monkeypatch.setattr(linux, "build_gst_args", with_test_sources)
    backend = linux.LinuxBackend(ffmpeg_path)
    stand_in_fd = os.open(os.devnull, os.O_RDONLY)  # only has to be inheritable
    monkeypatch.setattr(backend, "_open_screen", lambda: ScreenStream(stand_in_fd, node_id=1))
    yield backend
    os.close(stand_in_fd)


def _spec(output_path: Path):
    from screenrec.recorder.spec import (
        AudioSource,
        CaptureMode,
        CaptureTarget,
        QualityPreset,
        RecordingSpec,
        VideoCodec,
    )

    return RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0),
        quality=QualityPreset.SAVER,
        codec=VideoCodec.H264,
        audio=AudioSource.SYSTEM,
        output_path=output_path,
    )


def _probe(ffprobe_path: str, path: Path, entries: str) -> str:
    return subprocess.run(
        [ffprobe_path, "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_stopping_finishes_a_readable_recording_with_video_and_audio(
    backend, tmp_path: Path, ffprobe_path: str
):
    output = tmp_path / "screenrec_test.mkv"
    backend.start(_spec(output), lambda _event: None)
    time.sleep(2)
    backend.stop()

    assert _probe(ffprobe_path, output, "stream=codec_type").split() == ["video", "audio"]


def test_recording_lasts_as_long_as_it_ran(backend, tmp_path: Path, ffprobe_path: str):
    output = tmp_path / "screenrec_test.mkv"
    backend.start(_spec(output), lambda _event: None)
    time.sleep(2)
    backend.stop()

    duration = float(_probe(ffprobe_path, output, "format=duration"))
    assert 1.5 < duration < 3.5
