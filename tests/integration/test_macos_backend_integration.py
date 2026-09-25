"""MacBackend with real ffmpeg, but a stand-in for ScreenCaptureKit that
generates frames and audio - CI runners have no Screen Recording permission.
The real capture is exercised by the last test, which only runs on a Mac that
has granted the permission (to the terminal running the tests)."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS backend")

# Padded rows, as ScreenCaptureKit delivers them: ffmpeg has to crop 64 pixels.
_WIDTH, _HEIGHT, _STRIDE = 320, 180, 384


class _FakeCapture:
    """Stands in for screencapture.ScreenCapture: a new frame every 1/fps (or
    only the first one, like ScreenCaptureKit on a still screen) and
    audio buffers of about 20ms, all timestamped with the real host clock."""

    still_screen = False

    def __init__(self, on_video, on_audio) -> None:
        self._on_video = on_video
        self._on_audio = on_audio
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self, display_index: int, scale_height: int | None, fps: int) -> bool:
        self._threads.append(threading.Thread(target=self._video, args=(fps,), daemon=True))
        if self._on_audio is not None:
            self._threads.append(threading.Thread(target=self._audio, daemon=True))
        for thread in self._threads:
            thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)

    def _video(self, fps: int) -> None:
        from screenrec.recorder.macos import FrameLayout
        from screenrec.recorder.screencapture import host_clock

        layout = FrameLayout(width=_WIDTH, height=_HEIGHT, stride=_STRIDE)
        frame = bytes([128]) * (_STRIDE * _HEIGHT * 3 // 2)
        self._on_video(host_clock(), layout, frame)
        while not self._stop.wait(1 / fps):
            if not self.still_screen:
                self._on_video(host_clock(), layout, frame)

    def _audio(self) -> None:
        # Sized by the clock, not by the loop: each wait() overruns a little,
        # and fixed-size chunks would fall behind like no real device does.
        from screenrec.recorder.screencapture import host_clock

        started_at = host_clock()
        sent_frames = 0
        while not self._stop.wait(0.02):
            frames = int((host_clock() - started_at) * 48_000) - sent_frames
            self._on_audio(started_at + sent_frames / 48_000, bytes(frames * 8))
            sent_frames += frames


@pytest.fixture
def backend(monkeypatch, ffmpeg_path: str):
    from screenrec.recorder import macos, screencapture

    monkeypatch.setattr(screencapture, "ScreenCapture", _FakeCapture)
    monkeypatch.setattr(_FakeCapture, "still_screen", False)
    return macos.MacBackend(ffmpeg_path)


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


def _probe(ffprobe_path: str, path: Path, entries: str, *options: str) -> str:
    return subprocess.run(
        [ffprobe_path, "-v", "error", *options, "-show_entries", entries, "-of", "csv=p=0"]
        + [str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _has_screen_recording_permission() -> bool:
    if sys.platform != "darwin":
        return False
    import Quartz

    return Quartz.CGPreflightScreenCaptureAccess()


def _record(backend, path: Path, seconds: float) -> None:
    backend.start(_spec(path), lambda _event: None)
    threading.Event().wait(seconds)
    backend.stop()


def test_stopping_finishes_a_readable_recording_with_video_and_audio(
    backend, tmp_path: Path, ffprobe_path: str
):
    out = tmp_path / "rec.mkv"
    _record(backend, out, seconds=2)
    assert _probe(ffprobe_path, out, "stream=codec_type").splitlines() == ["video", "audio"]


def test_recording_crops_the_row_padding_off(backend, tmp_path: Path, ffprobe_path: str):
    out = tmp_path / "rec.mkv"
    _record(backend, out, seconds=1)
    assert _probe(ffprobe_path, out, "stream=width,height", "-select_streams", "v:0") == "320,180"


def test_a_still_screen_still_fills_the_whole_recording_with_video(
    backend, monkeypatch, tmp_path: Path, ffprobe_path: str
):
    monkeypatch.setattr(_FakeCapture, "still_screen", True)
    out = tmp_path / "rec.mkv"
    _record(backend, out, seconds=3)
    frames = int(
        _probe(
            ffprobe_path, out, "stream=nb_read_frames", "-select_streams", "v:0", "-count_frames"
        )
    )
    assert frames >= 80  # ~3s at 30fps, from a single captured frame


def test_video_and_audio_last_equally_long(
    backend, tmp_path: Path, ffmpeg_path: str, ffprobe_path: str
):
    out = tmp_path / "rec.mkv"
    _record(backend, out, seconds=3)
    remuxed = tmp_path / "rec.mp4"  # MKV streams carry no duration; MP4's do
    subprocess.run(
        [ffmpeg_path, "-v", "error", "-i", str(out), "-c", "copy", str(remuxed)], check=True
    )
    durations = _probe(ffprobe_path, remuxed, "stream=duration").splitlines()
    video, audio = (float(value) for value in durations)
    assert abs(video - audio) < 0.2


@pytest.mark.skipif(
    not _has_screen_recording_permission(), reason="needs the Screen Recording permission"
)
def test_real_capture_delivers_frames_of_the_requested_height():
    from screenrec.recorder.screencapture import ScreenCapture

    heights: list[int] = []
    got_frame = threading.Event()

    def on_video(presented_at, layout, data) -> None:
        heights.append(layout.height)
        got_frame.set()

    capture = ScreenCapture(on_video=on_video, on_audio=None)
    capture.start(display_index=0, scale_height=720, fps=30)
    try:
        assert got_frame.wait(5)
    finally:
        capture.stop()
    assert heights[0] == 720
