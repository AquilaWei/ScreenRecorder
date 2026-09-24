from pathlib import Path

import pytest

from screenrec.recorder.linux import (
    SLEEP_NOT_INHIBITED_WARNING,
    LinuxBackend,
    build_ffmpeg_args,
    build_gst_args,
)
from screenrec.recorder.spec import (
    AudioSource,
    CaptureMode,
    CaptureTarget,
    QualityPreset,
    RecordingSpec,
    Region,
    VideoCodec,
)


def _full_screen_spec(
    audio: AudioSource = AudioSource.NONE, quality: QualityPreset = QualityPreset.STANDARD
) -> RecordingSpec:
    return RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0),
        quality=quality,
        codec=VideoCodec.H264,
        audio=audio,
        output_path=Path("out.mkv"),
    )


def test_gst_reads_the_portal_stream_through_the_inherited_fd():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=False)
    assert "fd=7" in args
    assert "path=125" in args


def test_gst_resends_the_last_frame_so_a_still_screen_keeps_the_timeline_going():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=False)
    assert "keepalive-time=33" in args


def test_gst_outputs_constant_frame_rate_i420_at_the_preset_fps():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=60, with_audio=False)
    assert "video/x-raw,format=I420,framerate=60/1" in args


def test_gst_video_queue_is_limited_by_time_not_by_the_default_10mb():
    # One raw 2880x1800 frame is ~8MB: a byte limit would buffer about one frame.
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=False)
    assert "max-size-bytes=0" in args
    assert "max-size-time=1000000000" in args


def test_gst_system_audio_records_the_default_output_monitor():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=True)
    assert "device=@DEFAULT_MONITOR@" in args


def test_gst_without_audio_has_no_audio_source():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=False)
    assert "pulsesrc" not in args


def test_gst_ends_the_stream_cleanly_on_sigint_and_writes_matroska_to_stdout():
    args = build_gst_args(pipewire_fd=7, node_id=125, fps=30, with_audio=False)
    assert args[0] == "-e"
    assert args[-6:] == ["matroskamux", "name=mux", "streamable=true", "!", "fdsink", "fd=1"]


def test_ffmpeg_reads_matroska_from_stdin():
    args = build_ffmpeg_args(_full_screen_spec(), "libopenh264")
    assert args[args.index("-i") - 2 : args.index("-i") + 2] == ["-f", "matroska", "-i", "pipe:0"]


def test_ffmpeg_scales_to_the_preset_height():
    args = build_ffmpeg_args(_full_screen_spec(quality=QualityPreset.SAVER), "libopenh264")
    assert args[args.index("-vf") + 1] == "scale=-2:720"


def test_ffmpeg_keeps_native_resolution_for_the_high_preset():
    args = build_ffmpeg_args(_full_screen_spec(quality=QualityPreset.HIGH), "libopenh264")
    assert "-vf" not in args


def test_ffmpeg_encodes_aac_when_recording_system_audio():
    args = build_ffmpeg_args(_full_screen_spec(audio=AudioSource.SYSTEM), "libopenh264")
    assert "aac" in args
    assert "-an" not in args


def test_ffmpeg_drops_audio_when_not_recording_it():
    args = build_ffmpeg_args(_full_screen_spec(audio=AudioSource.NONE), "libopenh264")
    assert "-an" in args


def test_ffmpeg_output_is_matroska_at_the_given_path():
    args = build_ffmpeg_args(_full_screen_spec(), "libopenh264")
    assert args[-3:] == ["-f", "matroska", "out.mkv"]


def test_region_capture_mode_is_not_yet_implemented():
    spec = RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.REGION, region=Region(0, 0, 640, 480)),
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=AudioSource.NONE,
        output_path=Path("out.mkv"),
    )
    with pytest.raises(NotImplementedError, match="M2"):
        build_ffmpeg_args(spec, "libopenh264")


def test_start_warns_the_user_when_the_desktop_wont_keep_the_machine_awake(monkeypatch):
    # Regression test: this failure used to go only to stderr, which the GUI
    # never shows - a long recording could silently end at the next sleep.
    portal = pytest.importorskip("screenrec.recorder.portal")

    class _SessionWithoutInhibit:
        restore_token = None

        def __init__(self, restore_token):
            pass

        def open(self):
            return portal.ScreenStream(fd=-1, node_id=1)

        def inhibit_sleep(self, reason):
            raise RuntimeError("no Inhibit portal")

    monkeypatch.setattr(portal, "ScreenCastSession", _SessionWithoutInhibit)
    backend = LinuxBackend(ffmpeg_path="ffmpeg")

    backend._open_screen()

    assert backend.start_warnings == [SLEEP_NOT_INHIBITED_WARNING]
