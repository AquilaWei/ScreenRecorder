import pytest

from screenrec.presets import get_encoding_params
from screenrec.recorder.spec import QualityPreset, VideoCodec


def test_standard_h264_targets_1080p_30fps():
    params = get_encoding_params(QualityPreset.STANDARD, VideoCodec.H264)
    assert params.fps == 30
    assert params.scale_height == 1080


def test_saver_hevc_targets_720p():
    params = get_encoding_params(QualityPreset.SAVER, VideoCodec.HEVC)
    assert params.scale_height == 720


def test_high_quality_has_no_scale_cap_native_resolution():
    params = get_encoding_params(QualityPreset.HIGH, VideoCodec.H264)
    assert params.scale_height is None


def test_hevc_uses_lower_max_bitrate_than_h264_at_same_preset():
    h264 = get_encoding_params(QualityPreset.STANDARD, VideoCodec.H264)
    hevc = get_encoding_params(QualityPreset.STANDARD, VideoCodec.HEVC)
    assert hevc.max_bitrate_kbps < h264.max_bitrate_kbps


def test_unknown_combo_raises_value_error():
    class FakeCodec:
        value = "vp9"

    with pytest.raises(ValueError, match="no preset defined"):
        get_encoding_params(QualityPreset.STANDARD, FakeCodec())
