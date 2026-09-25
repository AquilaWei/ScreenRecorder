"""Detect available FFmpeg encoders and pick the best one for a codec.

Fallback order follows the feasibility study: hardware encoders first, software last.
VideoToolbox is macOS' own hardware encoder and never coexists with the vendor
ones or VAAPI, so its place among them doesn't matter.
VAAPI comes after the vendor encoders: it is Linux's one path to Intel and AMD
hardware encoding, and the only one a Flatpak's ffmpeg has. OpenH264 is the
last resort: lower quality per bit than x264, but it's what distributions that
leave out x264 for patent reasons (e.g. Fedora) ship.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from screenrec.recorder.ffmpeg_common import hardware_device_args, upload_filter
from screenrec.recorder.ffmpeg_exe import NO_WINDOW
from screenrec.recorder.spec import RecordingSpec, VideoCodec

_FALLBACK_CHAINS: dict[VideoCodec, tuple[str, ...]] = {
    VideoCodec.H264: (
        "h264_nvenc",
        "h264_qsv",
        "h264_amf",
        "h264_videotoolbox",
        "h264_vaapi",
        "libx264",
        "libopenh264",
    ),
    VideoCodec.HEVC: (
        "hevc_nvenc",
        "hevc_qsv",
        "hevc_amf",
        "hevc_videotoolbox",
        "hevc_vaapi",
        "libx265",
    ),
}

# `ffmpeg -encoders` lines look like " V..... libx264   <description>" - 6 capability
# flags (type + 5 modifiers) followed by the encoder name.
_ENCODER_LINE_RE = re.compile(r"^\s*[VAS][F.][S.][X.][B.][D.]\s+(\S+)\s")


def parse_encoder_names(ffmpeg_encoders_output: str) -> set[str]:
    """Parse the encoder name column out of `ffmpeg -encoders` output."""
    names: set[str] = set()
    for line in ffmpeg_encoders_output.splitlines():
        match = _ENCODER_LINE_RE.match(line)
        if match and match.group(1) != "=":  # skip the "V..... = Video" legend lines
            names.add(match.group(1))
    return names


def list_available_encoders(ffmpeg_path: str = "ffmpeg") -> set[str]:
    result = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=True,
        creationflags=NO_WINDOW,
    )
    return parse_encoder_names(result.stdout)


def select_video_encoder(available: set[str], codec: VideoCodec) -> str:
    """Pick the first available encoder in the hardware-first fallback chain."""
    chain = _FALLBACK_CHAINS[codec]
    for name in chain:
        if name in available:
            return name
    raise RuntimeError(f"no encoder available for {codec.value}; tried {', '.join(chain)}")


def probe_encoder(encoder_name: str, ffmpeg_path: str = "ffmpeg") -> bool:
    """Try a real one-frame encode with `encoder_name`.

    An encoder can be compiled into ffmpeg (and so appear in `-encoders`) but
    still fail at runtime - e.g. NVENC when the GPU driver is older than the
    NVENC SDK version this ffmpeg build expects. `select_video_encoder` alone
    can't catch that; this does.
    """
    upload = upload_filter(encoder_name)
    result = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            *hardware_device_args(encoder_name),
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=1",
            "-frames:v",
            "1",
            *(["-vf", upload] if upload else []),
            "-c:v",
            encoder_name,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    return result.returncode == 0


def select_working_encoder(
    available: set[str], codec: VideoCodec, probe: Callable[[str], bool]
) -> str:
    """Like `select_video_encoder`, but also skips encoders that fail `probe`
    (a real runtime check, e.g. `probe_encoder`) - not just ones missing from
    `available` (ffmpeg's compile-time encoder list).
    """
    chain = _FALLBACK_CHAINS[codec]
    tried = []
    for name in chain:
        if name not in available:
            continue
        tried.append(name)
        if probe(name):
            return name
    raise RuntimeError(f"no working encoder for {codec.value}; tried {', '.join(tried)}")


def choose_encoder(spec: RecordingSpec, ffmpeg_path: str = "ffmpeg") -> str:
    """The best encoder for `spec.codec` that really works with this ffmpeg.

    Raises RuntimeError if none of the candidates works, and CalledProcessError
    if `ffmpeg -encoders` itself fails.
    """
    available = list_available_encoders(ffmpeg_path)
    return select_working_encoder(
        available, spec.codec, probe=lambda name: probe_encoder(name, ffmpeg_path)
    )
