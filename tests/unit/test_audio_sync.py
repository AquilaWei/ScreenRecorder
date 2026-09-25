import socket

import pytest

from screenrec.recorder.audio_sync import (
    BYTES_PER_FRAME,
    AudioSocketSink,
    SilencePadder,
    silence_chunk,
)


def test_silence_chunk_is_correct_byte_length_for_16bit_stereo():
    assert len(silence_chunk(chunk_frames=100)) == 100 * 2 * 2  # frames * channels * bytes/sample


def test_silence_chunk_is_all_zero_bytes():
    assert silence_chunk(chunk_frames=10) == b"\x00" * 40


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


def test_silence_chunk_sizes_frames_by_the_given_frame_size():
    assert len(silence_chunk(chunk_frames=100, bytes_per_frame=8)) == 800


def test_padder_prepends_silence_in_whole_32bit_float_stereo_frames():
    padder = SilencePadder(timeline_start=1.0, bytes_per_frame=8)
    out = padder.on_data(1.13, b"\x01" * (2400 * 8))  # 0.05s, covers [1.08, 1.13]
    assert len(out) == 6240 * 8  # 0.13s
