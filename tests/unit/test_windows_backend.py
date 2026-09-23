import io
import socket
import threading
import time
from pathlib import Path

import pytest

from screenrec.recorder.spec import (
    AudioSource,
    CaptureMode,
    CaptureTarget,
    QualityPreset,
    RecordingSpec,
    VideoCodec,
)
from screenrec.recorder.windows import (
    BYTES_PER_FRAME,
    AudioSocketSink,
    FfmpegLogReader,
    SilencePadder,
    WasapiLoopbackCapture,
    audio_clock,
    build_ffmpeg_args,
    is_first_frame_line,
    silence_chunk,
    wait_for_output,
)


def _full_screen_spec(
    monitor_index: int = 0, audio: AudioSource = AudioSource.NONE
) -> RecordingSpec:
    return RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=monitor_index),
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=audio,
        output_path=Path("out.mkv"),
    )


def test_full_screen_capture_selects_correct_monitor_index():
    args = build_ffmpeg_args(_full_screen_spec(monitor_index=1), "libx264", audio_url=None)
    assert "ddagrab=output_idx=1" in " ".join(args)


def test_no_audio_source_omits_audio_input_and_disables_audio_track():
    args = build_ffmpeg_args(_full_screen_spec(audio=AudioSource.NONE), "libx264", audio_url=None)
    assert args.count("-i") == 1
    assert "-an" in args


def test_system_audio_reads_from_the_audio_url_and_encodes_aac():
    args = build_ffmpeg_args(
        _full_screen_spec(audio=AudioSource.SYSTEM), "libx264", audio_url="tcp://127.0.0.1:5000"
    )
    assert "tcp://127.0.0.1:5000" in args
    assert "aac" in args
    assert "-an" not in args


def test_software_encoder_uses_crf_quality_flag():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert "-crf" in args


def test_nvenc_encoder_uses_cq_quality_flag():
    args = build_ffmpeg_args(_full_screen_spec(), "h264_nvenc", audio_url=None)
    assert "-cq" in args
    assert "-crf" not in args


def test_software_encoder_gets_a_fast_preset():
    # Regression test: left unset, libx264 defaults to "medium", which isn't
    # reliably fast enough for real-time 1080p+ screen encoding - found live
    # as dropped video frames that got worse over the course of a recording.
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert "-preset" in args
    assert args[args.index("-preset") + 1] == "veryfast"


def test_hardware_encoder_does_not_get_a_libx264_style_preset():
    args = build_ffmpeg_args(_full_screen_spec(), "h264_nvenc", audio_url=None)
    assert "-preset" not in args


def test_output_forces_constant_frame_rate_at_the_preset_fps():
    # Regression test: without an explicit target, ffmpeg's default frame-rate
    # conversion heuristics against ddagrab's capture timestamps produced
    # sporadic dropped/duplicated frames.
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert "-fps_mode" in args
    assert args[args.index("-fps_mode") + 1] == "cfr"
    assert "-r" in args
    assert args[args.index("-r") + 1] == "30"  # STANDARD preset's fps


def test_output_forces_standard_yuv420p_pixel_format():
    # Regression test: without forcing this, the encoder keeps the capture's
    # full-chroma BGRA source and produces High 4:4:4 Predictive H.264, which
    # ffmpeg itself decodes fine but almost no real player supports - found
    # live when recordings "couldn't play" despite passing every ffmpeg check.
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert "-pix_fmt" in args
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"


def test_output_is_matroska_container_at_the_given_path():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert args[-3:] == ["-f", "matroska", "out.mkv"]


def test_window_capture_mode_is_not_yet_implemented():
    spec = RecordingSpec(
        target=CaptureTarget(mode=CaptureMode.WINDOW, window_handle=12345),
        quality=QualityPreset.STANDARD,
        codec=VideoCodec.H264,
        audio=AudioSource.NONE,
        output_path=Path("out.mkv"),
    )
    with pytest.raises(NotImplementedError, match="M2"):
        build_ffmpeg_args(spec, "libx264", audio_url=None)


def test_silence_chunk_is_correct_byte_length_for_16bit_stereo():
    assert len(silence_chunk(chunk_frames=100)) == 100 * 2 * 2  # frames * channels * bytes/sample


def test_silence_chunk_is_all_zero_bytes():
    assert silence_chunk(chunk_frames=10) == b"\x00" * 40


class _SlowSink:
    """Stands in for ffmpeg's stdin while ffmpeg is still starting up."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        time.sleep(self.delay)
        self.written += data


def test_on_audio_returns_immediately_while_the_sink_write_is_blocked():
    # Regression test: capture and write used to share one thread, so a blocked
    # write (ffmpeg not reading audio yet) overflowed the device buffer and
    # dropped audio - measured live as audio drifting ~250ms ahead of video.
    capture = WasapiLoopbackCapture(_SlowSink(delay=0.5), timeline_start=audio_clock)
    thread = threading.Thread(target=capture._run, args=(4800,))
    thread.start()
    started = time.monotonic()
    capture.on_audio(b"\x01" * 8, 2, None, 0)
    capture.on_audio(b"\x02" * 8, 2, None, 0)
    capture.on_audio(b"\x03" * 8, 2, None, 0)
    elapsed = time.monotonic() - started
    capture._stop_event.set()
    thread.join(timeout=5)
    assert elapsed < 0.1


def test_audio_queued_while_the_sink_is_blocked_is_written_in_order():
    sink = _SlowSink(delay=0.2)
    timeline_start = audio_clock() - 1.0  # well before any audio arrives
    capture = WasapiLoopbackCapture(sink, timeline_start=lambda: timeline_start)
    thread = threading.Thread(target=capture._run, args=(4800,))
    thread.start()
    capture.on_audio(b"\x01" * 8, 2, None, 0)
    capture.on_audio(b"\x02" * 8, 2, None, 0)
    capture.on_audio(b"\x03" * 8, 2, None, 0)
    capture._stop_event.set()
    thread.join(timeout=5)
    assert bytes(sink.written).endswith(b"\x01" * 8 + b"\x02" * 8 + b"\x03" * 8)


def test_on_audio_callback_tells_portaudio_to_continue():
    capture = WasapiLoopbackCapture(_SlowSink(delay=0), timeline_start=audio_clock)
    assert capture.on_audio(b"\x01" * 8, 2, None, 0) == (None, 0)


def test_recording_does_not_use_shortest():
    # Regression test: -shortest with the live ddagrab input made ffmpeg buffer
    # ~10s before emitting any video (measured live: first frame at 11.6s vs
    # 1.8s without it), which also backed up the audio queue and made stop()
    # time out and kill ffmpeg. The tail is trimmed at remux time instead.
    args = build_ffmpeg_args(
        _full_screen_spec(audio=AudioSource.SYSTEM), "libx264", audio_url="tcp://127.0.0.1:5000"
    )
    assert "-shortest" not in args


def test_wait_for_output_true_once_file_has_content(tmp_path):
    out = tmp_path / "a.mkv"
    out.write_bytes(b"x")
    assert wait_for_output(out, lambda: True, timeout=1)


def test_wait_for_output_false_when_process_exits_first(tmp_path):
    assert not wait_for_output(tmp_path / "a.mkv", lambda: False, timeout=1)


def test_wait_for_output_false_on_timeout_when_ffmpeg_hangs_silently(tmp_path):
    # Regression test: ffmpeg once hung at startup with no error and no output
    # file, leaving the GUI stuck forever.
    assert not wait_for_output(tmp_path / "a.mkv", lambda: True, timeout=0.3, poll_interval=0.05)


_RATE = 48_000


def _chunk(seconds: float) -> bytes:
    return b"\x01" * (round(seconds * _RATE) * BYTES_PER_FRAME)


def _seconds(data: bytes) -> float:
    return len(data) / BYTES_PER_FRAME / _RATE


def test_padder_does_not_pad_a_53ms_gap_between_chunks():
    # Regression test: chunks normally arrive every ~50ms but sometimes 53ms
    # apart (seen live); padding after one 50ms period inserted silence
    # between real chunks, stretching audio ~3% vs video.
    padder = SilencePadder(timeline_start=0.0)
    padder.on_data(0.05, _chunk(0.05))
    assert padder.on_idle(0.103) is None


def test_padder_waits_out_the_grace_period_before_padding():
    padder = SilencePadder(timeline_start=0.0)
    padder.on_data(1.0, _chunk(0.05))
    assert padder.on_idle(1.19) is None


def test_padder_pads_silence_up_to_now_during_a_silent_gap():
    # e.g. a quiet gap between sentences - WASAPI delivers nothing at all
    padder = SilencePadder(timeline_start=0.95)
    padder.on_data(1.0, _chunk(0.05))
    assert _seconds(padder.on_idle(2.5)) == pytest.approx(1.5, abs=0.0001)


def test_padder_fills_the_rest_of_the_gap_before_resumed_audio():
    padder = SilencePadder(timeline_start=0.95)
    padder.on_data(1.0, _chunk(0.05))
    padder.on_idle(2.5)  # padded up to 2.5
    resumed = padder.on_data(2.6, _chunk(0.05))  # real audio covers [2.55, 2.6]
    assert _seconds(resumed) == pytest.approx(0.1, abs=0.0001)


def test_padder_trims_resumed_audio_if_it_over_padded():
    padder = SilencePadder(timeline_start=0.95)
    padder.on_data(1.0, _chunk(0.05))
    padded = _seconds(padder.on_idle(2.0))  # padded up to 2.0
    resumed = padder.on_data(2.03, _chunk(0.05))  # but real audio covers [1.98, 2.03]
    assert padded + _seconds(resumed) == pytest.approx(1.03, abs=0.002)


def test_output_flushes_packets_immediately():
    # Regression test: with default buffering the output file took ~7s to
    # appear, so start() (which waits for it) looked frozen.
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert args[args.index("-flush_packets") + 1] == "1"


def test_padder_trims_audio_captured_before_the_first_video_frame():
    # Regression test: audio capture starts before ffmpeg grabs its first
    # frame, which made audio play ~100ms late (measured live).
    padder = SilencePadder(timeline_start=1.0)
    out = padder.on_data(1.02, _chunk(0.05))  # covers [0.97, 1.02]
    assert _seconds(out) == pytest.approx(0.02, abs=0.0001)


def test_padder_drops_chunks_entirely_before_the_first_video_frame():
    padder = SilencePadder(timeline_start=1.0)
    assert padder.on_data(0.9, _chunk(0.05)) == b""
    assert _seconds(padder.on_data(1.05, _chunk(0.05))) == pytest.approx(0.05, abs=0.0001)


def test_padder_prepends_silence_when_audio_starts_after_the_first_video_frame():
    padder = SilencePadder(timeline_start=1.0)
    out = padder.on_data(1.13, _chunk(0.05))  # covers [1.08, 1.13]
    assert _seconds(out) == pytest.approx(0.13, abs=0.0001)
    assert out.startswith(b"\x00" * (round(0.08 * _RATE) * BYTES_PER_FRAME))


_SHOWINFO_FIRST = b"[Parsed_showinfo_3 @ 000001f2] n:   0 pts:      0 pts_time:0    duration:1\n"
_SHOWINFO_LATER = b"[Parsed_showinfo_3 @ 000001f2] n:  10 pts: 333333 pts_time:0.33 duration:1\n"


def test_first_frame_line_matches_only_frame_zero():
    assert is_first_frame_line(_SHOWINFO_FIRST)
    assert not is_first_frame_line(_SHOWINFO_LATER)
    assert not is_first_frame_line(b"Input #0, lavfi, from 'ddagrab': n:   0 \n")


def test_log_reader_records_first_frame_and_keeps_other_lines():
    stream = io.BytesIO(b"Input #0, lavfi\n" + _SHOWINFO_FIRST + _SHOWINFO_LATER + b"boom\n")
    reader = FfmpegLogReader(stream)
    reader.start()
    assert reader.wait_first_frame(timeout=2) is not None
    reader._thread.join(timeout=2)
    assert list(reader.tail) == ["Input #0, lavfi", "boom"]


def test_capture_filter_logs_frames_for_av_alignment():
    args = build_ffmpeg_args(_full_screen_spec(), "libx264", audio_url=None)
    assert "showinfo" in args[args.index("-i") + 1]
    assert "-nostats" in args


def test_audio_socket_sink_delivers_bytes_to_the_connecting_client():
    sink = AudioSocketSink(accept_timeout=5)
    port = int(sink.url.rsplit(":", 1)[1])
    client = socket.create_connection(("127.0.0.1", port))
    sink.write(b"abc")
    sink.write(b"def")
    sink.close()
    with client, client.makefile("rb") as received:
        assert received.read() == b"abcdef"


def test_audio_socket_sink_write_fails_once_closed_before_ffmpeg_connected():
    sink = AudioSocketSink(accept_timeout=5)
    sink.close()
    with pytest.raises(OSError):
        sink.write(b"abc")


def test_audio_arrival_timestamps_are_high_resolution():
    # Regression test: time.monotonic() on Windows before Python 3.13 ticks in
    # 15.6ms steps, so chunks arriving microseconds apart got equal timestamps
    # and were misplaced against the first video frame (failed in CI on 3.12).
    capture = WasapiLoopbackCapture(_SlowSink(delay=0), timeline_start=audio_clock)
    capture.on_audio(b"\x01" * 8, 2, None, 0)
    capture.on_audio(b"\x02" * 8, 2, None, 0)
    first_arrival, _ = capture._queue.get_nowait()
    second_arrival, _ = capture._queue.get_nowait()
    assert second_arrival > first_arrival
