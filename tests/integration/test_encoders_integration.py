"""Integration tests that invoke a real ffmpeg. Skipped when ffmpeg isn't on PATH."""

from __future__ import annotations

from screenrec.recorder.encoders import choose_encoder, probe_encoder
from screenrec.recorder.spec import VideoCodec


def test_choose_encoder_returns_an_encoder_that_really_encodes(
    ffmpeg_path: str, tmp_path, monkeypatch
):
    from screenrec.recorder.spec import (
        AudioSource,
        CaptureMode,
        CaptureTarget,
        QualityPreset,
        RecordingSpec,
    )

    spec = RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0),
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=AudioSource.NONE,
        output_path=tmp_path / "out.mkv",
    )
    encoder = choose_encoder(spec, ffmpeg_path)
    # Regression test: being listed in `ffmpeg -encoders` isn't enough - on this
    # dev machine h264_nvenc is compiled in but rejected at runtime (NVIDIA
    # driver too old for this build's NVENC SDK), and used to be picked anyway.
    assert probe_encoder(encoder, ffmpeg_path)
