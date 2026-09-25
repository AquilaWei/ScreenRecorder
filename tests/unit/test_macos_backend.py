import struct
from pathlib import Path

import pytest

from screenrec.recorder.macos import (
    AudioWriter,
    FrameLayout,
    FramePacer,
    LatestFrame,
    build_ffmpeg_args,
    caffeinate_args,
    frame_layout,
    interleave_f32,
    output_size,
)
from screenrec.recorder.spec import (
    AudioSource,
    CaptureMode,
    CaptureTarget,
    QualityPreset,
    RecordingSpec,
    VideoCodec,
)

LAYOUT_1080P = FrameLayout(width=1660, height=1080, stride=1664)
UNPADDED_1080P = FrameLayout(width=1920, height=1080, stride=1920)


def _full_screen_spec(
    quality: QualityPreset = QualityPreset.STANDARD, audio: AudioSource = AudioSource.NONE
) -> RecordingSpec:
    return RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0),
        quality=quality,
        codec=VideoCodec.H264,
        audio=audio,
        output_path=Path("out.mkv"),
    )


def test_output_size_scales_a_retina_display_down_to_the_preset_height():
    assert output_size(2940, 1912, scale_height=1080) == (1660, 1080)


def test_output_size_keeps_the_native_size_without_a_preset_height():
    assert output_size(2940, 1912, scale_height=None) == (2940, 1912)


def test_output_size_never_scales_up():
    assert output_size(1280, 800, scale_height=1080) == (1280, 800)


def test_output_size_rounds_the_width_down_to_even():
    assert output_size(1366, 768, scale_height=720) == (1280, 720)


def test_frame_layout_uses_the_padded_row_length_as_stride():
    assert frame_layout(1660, 1080, 1664, 1664) == FrameLayout(1660, 1080, 1664)


def test_frame_layout_rejects_planes_with_different_row_lengths():
    with pytest.raises(ValueError):
        frame_layout(1660, 1080, 1664, 1728)


def test_interleave_f32_alternates_left_and_right_samples():
    left = struct.pack("<2f", 0.25, 0.5)
    right = struct.pack("<2f", -0.25, -0.5)
    assert interleave_f32(left, right) == struct.pack("<4f", 0.25, -0.25, 0.5, -0.5)


def test_caffeinate_keeps_display_and_system_awake_until_the_app_exits():
    assert caffeinate_args(4321) == ["caffeinate", "-d", "-i", "-w", "4321"]


def test_ffmpeg_reads_padded_nv12_rows_from_stdin():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", LAYOUT_1080P, audio_url=None)
    assert args[args.index("-pix_fmt") : args.index("-i") + 2] == [
        "-pix_fmt",
        "nv12",
        "-video_size",
        "1664x1080",
        "-framerate",
        "30",
        "-i",
        "pipe:0",
    ]


def test_ffmpeg_crops_the_row_padding_off():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", LAYOUT_1080P, audio_url=None)
    assert args[args.index("-vf") + 1].startswith("crop=1660:1080:0:0,")


def test_ffmpeg_does_not_crop_unpadded_frames():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", UNPADDED_1080P, audio_url=None)
    assert "crop" not in args[args.index("-vf") + 1]


def test_ffmpeg_does_not_scale_because_the_capture_already_has_the_preset_size():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", LAYOUT_1080P, audio_url=None)
    assert "scale" not in args[args.index("-vf") + 1]


def test_ffmpeg_tags_the_video_as_bt709_video_range():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", LAYOUT_1080P, audio_url=None)
    assert args[args.index("-vf") + 1].endswith(
        "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"
    )


def test_ffmpeg_reads_float_stereo_audio_from_the_socket():
    args = build_ffmpeg_args(
        _full_screen_spec(audio=AudioSource.SYSTEM),
        "libx264",
        LAYOUT_1080P,
        audio_url="tcp://127.0.0.1:5000",
    )
    audio_input = args.index("tcp://127.0.0.1:5000")
    assert args[audio_input - 7 : audio_input + 1] == [
        "-f",
        "f32le",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-i",
        "tcp://127.0.0.1:5000",
    ]


def test_ffmpeg_encodes_aac_when_recording_system_audio():
    args = build_ffmpeg_args(
        _full_screen_spec(audio=AudioSource.SYSTEM),
        "libx264",
        LAYOUT_1080P,
        audio_url="tcp://127.0.0.1:5000",
    )
    assert args[args.index("-c:a") + 1] == "aac"


def test_ffmpeg_drops_audio_when_not_recording_it():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", LAYOUT_1080P, audio_url=None)
    assert "-an" in args


def test_ffmpeg_reads_frames_at_the_preset_fps():
    args = build_ffmpeg_args(
        _full_screen_spec(quality=QualityPreset.HIGH), "libx264", LAYOUT_1080P, audio_url=None
    )
    assert args[args.index("-framerate") + 1] == "60"


def test_region_capture_mode_is_not_yet_implemented():
    spec = RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.WINDOW, window_handle=12345),
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=AudioSource.NONE,
        output_path=Path("out.mkv"),
    )
    with pytest.raises(NotImplementedError, match="M2"):
        build_ffmpeg_args(spec, "libx264", LAYOUT_1080P, audio_url=None)


def test_pacer_sends_the_first_frame_right_away():
    pacer = FramePacer(fps=10, first_frame_at=100.0)
    assert pacer.frames_due(100.0) == 1


def test_pacer_sends_nothing_before_the_next_frame_is_due():
    pacer = FramePacer(fps=10, first_frame_at=100.0)
    pacer.frames_due(100.0)
    assert pacer.frames_due(100.05) == 0


def test_pacer_repeats_frames_to_cover_a_still_screen():
    # ScreenCaptureKit sends nothing while the screen doesn't change.
    pacer = FramePacer(fps=10, first_frame_at=100.0)
    pacer.frames_due(100.0)
    assert pacer.frames_due(101.0) == 10


def test_pacer_schedules_the_next_frame_one_interval_after_the_last_sent():
    pacer = FramePacer(fps=10, first_frame_at=100.0)
    pacer.frames_due(100.25)
    assert pacer.next_frame_at() == pytest.approx(100.3)


def test_latest_frame_hands_out_the_newest_frame():
    frames = LatestFrame()
    frames.put(1.0, LAYOUT_1080P, b"old")
    frames.put(1.1, LAYOUT_1080P, b"new")
    assert frames.get() == b"new"


def test_latest_frame_remembers_when_the_first_frame_was_presented():
    frames = LatestFrame()
    frames.put(1.0, LAYOUT_1080P, b"old")
    frames.put(1.1, LAYOUT_1080P, b"new")
    assert frames.first_frame_at == 1.0


class _Sink:
    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        self.written += data


def test_audio_writer_aligns_audio_to_the_first_video_frame_by_timestamp():
    # 0.05s of audio presented at 0.98 overlaps the first frame (1.0) by 0.03s.
    sink = _Sink()
    writer = AudioWriter(sink, clock=lambda: 1.0)
    writer.on_audio(0.98, b"\x01" * (2400 * 8))
    writer.start(timeline_start=1.0)
    writer.stop()
    assert bytes(sink.written) == b"\x01" * (1440 * 8)
