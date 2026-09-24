from screenrec.recorder.ffmpeg_common import wait_for_output


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
