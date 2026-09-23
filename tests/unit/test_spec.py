from pathlib import Path

import pytest

from screenrec.recorder.spec import (
    AudioSource,
    CaptureMode,
    CaptureTarget,
    QualityPreset,
    RecordingSpec,
    Region,
    VideoCodec,
    validate,
)


def _spec(target: CaptureTarget, output_path: Path = Path("out.mkv")) -> RecordingSpec:
    return RecordingSpec(
        target=target,
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=AudioSource.SYSTEM,
        output_path=output_path,
    )


def test_full_screen_target_without_monitor_index_is_invalid():
    target = CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=None)
    with pytest.raises(ValueError, match="monitor_index"):
        validate(_spec(target))


def test_full_screen_target_with_monitor_index_is_valid():
    target = CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0)
    validate(_spec(target))  # does not raise


def test_window_target_without_handle_is_invalid():
    target = CaptureTarget(mode=CaptureMode.WINDOW, window_handle=None)
    with pytest.raises(ValueError, match="window_handle"):
        validate(_spec(target))


def test_region_target_without_region_is_invalid():
    target = CaptureTarget(mode=CaptureMode.REGION, region=None)
    with pytest.raises(ValueError, match="region"):
        validate(_spec(target))


def test_region_target_with_region_is_valid():
    target = CaptureTarget(mode=CaptureMode.REGION, region=Region(x=0, y=0, width=800, height=600))
    validate(_spec(target))  # does not raise


def test_non_mkv_output_path_is_invalid():
    target = CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0)
    with pytest.raises(ValueError, match=".mkv"):
        validate(_spec(target, output_path=Path("out.mp4")))
