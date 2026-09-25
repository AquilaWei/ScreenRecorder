import pytest

from screenrec.recorder.encoders import (
    parse_encoder_names,
    select_video_encoder,
    select_working_encoder,
)
from screenrec.recorder.spec import VideoCodec

FAKE_FFMPEG_ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ....B. = Supports draw_horiz_band
 .....D = Supports direct rendering method 1
 ------
 V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10
 V..... libx265              libx265 H.265 / HEVC
 V..X.. h264_nvenc            NVIDIA NVENC H.264 encoder (codec h264)
 A..... aac                  AAC (Advanced Audio Coding)
"""


def test_parse_encoder_names_extracts_video_encoder_names():
    names = parse_encoder_names(FAKE_FFMPEG_ENCODERS_OUTPUT)
    assert "libx264" in names
    assert "h264_nvenc" in names


def test_parse_encoder_names_ignores_legend_lines():
    names = parse_encoder_names(FAKE_FFMPEG_ENCODERS_OUTPUT)
    assert "=" not in names
    assert "Video" not in names


def test_parse_encoder_names_includes_audio_encoders_too():
    names = parse_encoder_names(FAKE_FFMPEG_ENCODERS_OUTPUT)
    assert "aac" in names  # not selected for video, but parsing doesn't filter by type


def test_select_video_encoder_prefers_hardware_when_available():
    available = {"h264_nvenc", "libx264"}
    assert select_video_encoder(available, VideoCodec.H264) == "h264_nvenc"


def test_select_video_encoder_falls_back_to_software_x264():
    available = {"libx264"}
    assert select_video_encoder(available, VideoCodec.H264) == "libx264"


def test_select_video_encoder_raises_when_nothing_available():
    with pytest.raises(RuntimeError, match="no encoder available"):
        select_video_encoder(set(), VideoCodec.H264)


def test_select_working_encoder_skips_compiled_but_non_functional_hardware_encoder():
    # h264_nvenc is compiled in but fails probe (e.g. GPU driver too old) - must
    # fall through to the next entry in the chain, not just return the first match.
    available = {"h264_nvenc", "libx264"}
    working = {"libx264"}
    encoder = select_working_encoder(available, VideoCodec.H264, probe=lambda name: name in working)
    assert encoder == "libx264"


def test_select_working_encoder_raises_when_all_probes_fail():
    available = {"h264_nvenc", "libx264"}
    with pytest.raises(RuntimeError, match="no working encoder"):
        select_working_encoder(available, VideoCodec.H264, probe=lambda name: False)


def test_select_working_encoder_ignores_probe_for_unavailable_encoders():
    probed = []
    available = {"libx264"}

    def probe(name: str) -> bool:
        probed.append(name)
        return True

    select_working_encoder(available, VideoCodec.H264, probe=probe)
    assert probed == ["libx264"]  # h264_nvenc/qsv/amf never probed - not compiled in


def test_select_video_encoder_falls_back_to_openh264_without_x264():
    # Fedora's ffmpeg ships no libx264; OpenH264 is its only software H.264.
    available = {"h264_v4l2m2m", "libopenh264"}
    assert select_video_encoder(available, VideoCodec.H264) == "libopenh264"


def test_select_video_encoder_prefers_x264_over_openh264():
    available = {"libx264", "libopenh264"}
    assert select_video_encoder(available, VideoCodec.H264) == "libx264"


def test_select_video_encoder_prefers_vaapi_over_software():
    # Linux on Intel/AMD: VAAPI is the hardware path, and a Flatpak's only one.
    available = {"h264_vaapi", "libx264", "libopenh264"}
    assert select_video_encoder(available, VideoCodec.H264) == "h264_vaapi"


def test_select_video_encoder_prefers_qsv_over_vaapi():
    available = {"h264_qsv", "h264_vaapi"}
    assert select_video_encoder(available, VideoCodec.H264) == "h264_qsv"


def test_select_video_encoder_prefers_videotoolbox_over_software():
    # macOS: VideoToolbox is the hardware path; the bundled ffmpeg also has x264.
    available = {"h264_videotoolbox", "libx264", "libopenh264"}
    assert select_video_encoder(available, VideoCodec.H264) == "h264_videotoolbox"


def test_select_video_encoder_picks_videotoolbox_for_hevc():
    available = {"hevc_videotoolbox", "libx265"}
    assert select_video_encoder(available, VideoCodec.HEVC) == "hevc_videotoolbox"
