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

    class _PortalWithoutInhibit:
        def start_cast(self):
            return portal.ScreenStream(fd=-1, node_id=1)

        def inhibit_sleep(self, reason):
            raise RuntimeError("no Inhibit portal")

    monkeypatch.setattr(portal, "ScreenCastPortal", _PortalWithoutInhibit)
    backend = LinuxBackend(ffmpeg_path="ffmpeg")

    backend._open_screen()

    assert backend.start_warnings == [SLEEP_NOT_INHIBITED_WARNING]


class _DesktopBus:
    """Stands in for the session bus: answers every portal call and request
    the way KDE does once the user has picked a screen. Records what was sent."""

    unique_name = ":1.42"

    def __init__(self):
        self.methods_called = []
        self._last_request = None

    def send_and_get_reply(self, message, timeout=None):
        import os

        from jeepney import HeaderFields, new_method_return

        member = message.header.fields[HeaderFields.member]
        self.methods_called.append(member)
        if member in ("CreateSession", "SelectSources", "Start"):
            self._last_request = member
        if member == "Get":  # AvailableCursorModes
            return new_method_return(message, "v", (("u", 7),))
        if member == "OpenPipeWireRemote":
            return new_method_return(message, "h", (_Fd(os.open(os.devnull, os.O_RDONLY)),))
        if member == "Inhibit":
            return new_method_return(message, "o", ("/org/freedesktop/portal/desktop/request/i",))
        return new_method_return(message, "o", ("/org/freedesktop/portal/desktop/request/x",))

    def filter(self, rule):
        from contextlib import nullcontext

        return nullcontext(None)

    def recv_until_filtered(self, queue, timeout=None):
        from types import SimpleNamespace

        results = {
            "CreateSession": {"session_handle": ("s", "/org/freedesktop/portal/desktop/session/s")},
            "SelectSources": {},
            "Start": {
                "streams": ("a(ua{sv})", [(125, {})]),
                "restore_token": ("s", "token-from-kde"),
            },
        }[self._last_request]
        return SimpleNamespace(body=(0, results))

    def close(self):
        pass


class _Fd:
    def __init__(self, fd):
        self._fd = fd

    def to_raw_fd(self):
        return self._fd


@pytest.fixture
def desktop(monkeypatch):
    portal = pytest.importorskip("screenrec.recorder.portal")
    connections = []

    def open_dbus_connection(**kwargs):
        connections.append(_DesktopBus())
        return connections[-1]

    monkeypatch.setattr(portal, "open_dbus_connection", open_dbus_connection)
    return connections


def test_later_recordings_reuse_the_bus_connection_that_holds_the_screen_choice(desktop):
    # Regression test: the portal only honours the remembered screen for the
    # connection that chose it, and each recording opened a new one - so the
    # "which screen?" dialog came back every time.
    backend = LinuxBackend(ffmpeg_path="ffmpeg")

    backend._open_screen()
    backend._kill()
    backend._open_screen()

    assert len(desktop) == 1


def test_finishing_a_recording_tells_the_desktop_to_stop_sharing_the_screen(desktop):
    backend = LinuxBackend(ffmpeg_path="ffmpeg")
    backend._open_screen()

    backend._kill()

    assert desktop[0].methods_called[-2:] == ["Close", "Close"]  # inhibition, then session
