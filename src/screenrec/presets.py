"""Quality preset -> encoding parameters. Pure lookup, no I/O.

Numbers are first estimates from the feasibility study; M0/M1 real-device testing on
Windows will tune them against actual output file sizes.
"""

from __future__ import annotations

from dataclasses import dataclass

from screenrec.recorder.spec import QualityPreset, VideoCodec


@dataclass(frozen=True)
class EncodingParams:
    fps: int
    crf: int
    max_bitrate_kbps: int
    scale_height: int | None
    keyframe_interval_sec: int = 2


_PRESETS: dict[tuple[QualityPreset, VideoCodec], EncodingParams] = {
    (QualityPreset.SAVER, VideoCodec.H264): EncodingParams(
        fps=30, crf=26, max_bitrate_kbps=4000, scale_height=720
    ),
    (QualityPreset.SAVER, VideoCodec.HEVC): EncodingParams(
        fps=30, crf=29, max_bitrate_kbps=2200, scale_height=720
    ),
    (QualityPreset.STANDARD, VideoCodec.H264): EncodingParams(
        fps=30, crf=23, max_bitrate_kbps=8000, scale_height=1080
    ),
    (QualityPreset.STANDARD, VideoCodec.HEVC): EncodingParams(
        fps=30, crf=26, max_bitrate_kbps=5000, scale_height=1080
    ),
    (QualityPreset.HIGH, VideoCodec.H264): EncodingParams(
        fps=60, crf=20, max_bitrate_kbps=20000, scale_height=None
    ),
    (QualityPreset.HIGH, VideoCodec.HEVC): EncodingParams(
        fps=60, crf=23, max_bitrate_kbps=14000, scale_height=None
    ),
}

AUDIO_BITRATE_KBPS = 160


def get_encoding_params(quality: QualityPreset, codec: VideoCodec) -> EncodingParams:
    try:
        return _PRESETS[(quality, codec)]
    except KeyError:
        raise ValueError(f"no preset defined for {quality.value} + {codec.value}") from None
