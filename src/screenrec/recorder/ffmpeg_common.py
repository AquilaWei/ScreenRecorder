"""ffmpeg pieces shared by every platform backend: the encoding/output half of the
command line, and waiting for ffmpeg to actually start writing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from screenrec.presets import AUDIO_BITRATE_KBPS, EncodingParams

# ffmpeg's flag for "constant quality" differs per encoder family.
_QUALITY_FLAG = {
    "libx264": "-crf",
    "libx265": "-crf",
    "h264_nvenc": "-cq",
    "hevc_nvenc": "-cq",
}

# Encoders without a constant-quality mode that honours -maxrate get a
# variable bitrate instead. OpenH264 has no quality mode at all. QSV's
# -global_quality selects constant QP, which ignores -maxrate: measured live at
# ~125 Mbps on busy 1080p content against an 8 Mbps ceiling.
_BITRATE_TARGET_ENCODERS = {"libopenh264", "h264_qsv", "hevc_qsv"}

# Software encoders only (hardware encoders have their own, differently-named
# speed/quality tradeoff options). Left unset, libx264/libx265 default to the
# "medium" preset, which is not reliably fast enough for real-time 1080p+
# screen encoding - found live: recordings dropped video frames (and the
# backlog worsened over the course of the recording) on a 6-core/12-thread
# desktop CPU because the encoder couldn't keep up in real time.
_SOFTWARE_ENCODERS = {"libx264", "libx265"}


def encoding_args(
    params: EncodingParams, video_encoder: str, has_audio: bool, output_path: Path
) -> list[str]:
    """Everything after the inputs: encoders, rate control, and the MKV output.
    Pure - no subprocess, no I/O."""
    args = [
        "-c:v",
        video_encoder,
        # Without this, the encoder keeps the capture's full-chroma BGRA source
        # as-is and produces High 4:4:4 Predictive H.264 - which ffmpeg itself
        # decodes fine, but almost no real player (Windows' own Movies & TV,
        # browsers, phones, hardware decoders) supports. yuv420p (standard
        # 4:2:0) is what "H.264 plays everywhere" actually depends on.
        "-pix_fmt",
        "yuv420p",
        *_rate_control_args(params, video_encoder),
        "-g",
        str(params.fps * params.keyframe_interval_sec),
    ]
    if video_encoder in _SOFTWARE_ENCODERS:
        args += ["-preset", "veryfast"]

    # NOTE: no -shortest here - with a live lavfi video input it made ffmpeg
    # buffer ~10s before emitting the first video frame (measured live). The
    # short silent-video tail it would trim is trimmed at remux time instead.
    args += ["-c:a", "aac", "-b:a", f"{AUDIO_BITRATE_KBPS}k"] if has_audio else ["-an"]
    # Explicit CFR output at the target fps instead of leaving ffmpeg's default
    # frame-rate-conversion heuristics to decide when to drop/duplicate frames
    # against the capture's (not perfectly clock-aligned) timestamps.
    args += ["-fps_mode", "cfr", "-r", str(params.fps)]
    # Write packets out as they're muxed instead of buffering in memory: start()
    # waits for the file to appear, which took ~7s with default buffering, and
    # a crash/kill now loses at most a moment of recording.
    args += ["-flush_packets", "1", "-f", "matroska", str(output_path)]
    return args


def _rate_control_args(params: EncodingParams, video_encoder: str) -> list[str]:
    ceiling = [
        "-maxrate",
        f"{params.max_bitrate_kbps}k",
        "-bufsize",
        f"{params.max_bitrate_kbps * 2}k",
    ]
    if video_encoder in _BITRATE_TARGET_ENCODERS:
        # Target below the ceiling: a target equal to -maxrate makes ffmpeg
        # pick constant bitrate, which spends the full rate on a still screen.
        return ["-b:v", f"{params.max_bitrate_kbps * 3 // 4}k", *ceiling]
    return [_QUALITY_FLAG.get(video_encoder, "-crf"), str(params.crf), *ceiling]


def wait_for_output(
    path: Path,
    is_running: Callable[[], bool],
    timeout: float,
    poll_interval: float = 0.2,
) -> bool:
    """Wait until ffmpeg has actually started writing `path`. False if it exits
    first or `timeout` passes - ffmpeg can hang at startup without any error
    (found live: no output file, no I/O, audio writer blocked forever)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        if not is_running():
            return False
        time.sleep(poll_interval)
    return False
