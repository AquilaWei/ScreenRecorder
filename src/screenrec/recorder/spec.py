"""Immutable description of a single recording request.

Kept as plain dataclasses so `spec -> ffmpeg args` / `spec -> gst pipeline` stays a pure,
easily-tested function per backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CaptureMode(Enum):
    FULL_SCREEN = "full_screen"
    WINDOW = "window"
    REGION = "region"


class QualityPreset(Enum):
    SAVER = "saver"
    STANDARD = "standard"
    HIGH = "high"


class VideoCodec(Enum):
    H264 = "h264"
    HEVC = "hevc"


class AudioSource(Enum):
    NONE = "none"
    SYSTEM = "system"
    MIC = "mic"
    SYSTEM_AND_MIC = "system_and_mic"


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class CaptureTarget:
    mode: CaptureMode
    monitor_index: int | None = None
    window_handle: int | None = None
    region: Region | None = None


@dataclass(frozen=True)
class RecordingSpec:
    target: CaptureTarget
    quality: QualityPreset
    codec: VideoCodec
    audio: AudioSource
    output_path: Path
    keep_mkv: bool = False


def validate(spec: RecordingSpec) -> None:
    """Raise ValueError if `spec` is internally inconsistent."""
    target = spec.target
    if target.mode is CaptureMode.FULL_SCREEN and target.monitor_index is None:
        raise ValueError("full_screen capture requires monitor_index")
    if target.mode is CaptureMode.WINDOW and target.window_handle is None:
        raise ValueError("window capture requires window_handle")
    if target.mode is CaptureMode.REGION and target.region is None:
        raise ValueError("region capture requires region")
    if spec.output_path.suffix.lower() != ".mkv":
        raise ValueError(f"recording output must be .mkv, got {spec.output_path.suffix!r}")
