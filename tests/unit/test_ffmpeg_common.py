from pathlib import Path

from screenrec.presets import get_encoding_params
from screenrec.recorder.ffmpeg_common import encoding_args, wait_for_output
from screenrec.recorder.spec import QualityPreset, VideoCodec

STANDARD_H264 = get_encoding_params(QualityPreset.STANDARD, VideoCodec.H264)


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


def test_openh264_gets_a_target_bitrate_instead_of_a_quality_flag():
    # OpenH264 has no CRF; given one, ffmpeg ignores it and encodes at its
    # tiny default bitrate.
    args = encoding_args(STANDARD_H264, "libopenh264", has_audio=False, output_path=Path("o.mkv"))
    assert args[args.index("-b:v") + 1] == "6000k"
    assert args[args.index("-maxrate") + 1] == "8000k"
    assert "-crf" not in args


def test_openh264_does_not_get_a_libx264_style_preset():
    args = encoding_args(STANDARD_H264, "libopenh264", has_audio=False, output_path=Path("o.mkv"))
    assert "-preset" not in args


def test_vaapi_uses_a_capped_variable_bitrate():
    # h264_vaapi has no -crf; the default quality flag would be ignored.
    args = encoding_args(STANDARD_H264, "h264_vaapi", has_audio=False, output_path=Path("o.mkv"))
    assert "-crf" not in args
    assert args[args.index("-b:v") + 1] == "6000k"
    assert args[args.index("-maxrate") + 1] == "8000k"


def test_vaapi_gets_no_pix_fmt_because_its_frames_are_already_on_the_gpu():
    # -pix_fmt yuv420p would ask ffmpeg to convert the uploaded GPU frames back.
    args = encoding_args(STANDARD_H264, "h264_vaapi", has_audio=False, output_path=Path("o.mkv"))
    assert "-pix_fmt" not in args


def test_qsv_uses_a_capped_variable_bitrate_not_constant_qp():
    # Regression test: -global_quality put QSV into constant-QP mode, which
    # ignores -maxrate - measured live at ~125 Mbps on busy 1080p content
    # against the STANDARD preset's 8 Mbps ceiling.
    args = encoding_args(STANDARD_H264, "h264_qsv", has_audio=False, output_path=Path("o.mkv"))
    assert "-global_quality" not in args
    assert args[args.index("-b:v") + 1] == "6000k"
    assert args[args.index("-maxrate") + 1] == "8000k"


def test_videotoolbox_uses_a_capped_variable_bitrate():
    args = encoding_args(
        STANDARD_H264, "h264_videotoolbox", has_audio=False, output_path=Path("o.mkv")
    )
    assert "-crf" not in args
    assert args[args.index("-b:v") + 1] == "6000k"
    assert args[args.index("-maxrate") + 1] == "8000k"
