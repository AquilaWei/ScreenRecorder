from pathlib import Path

from screenrec.recorder.finalize import find_unfinished_recordings


def test_mkv_without_matching_mp4_is_unfinished(tmp_path: Path):
    mkv = tmp_path / "screenrec_2026-09-23_140000.mkv"
    mkv.write_bytes(b"fake")
    assert find_unfinished_recordings(tmp_path) == [mkv]


def test_mkv_with_matching_mp4_is_not_unfinished(tmp_path: Path):
    mkv = tmp_path / "screenrec_2026-09-23_140000.mkv"
    mkv.write_bytes(b"fake")
    mkv.with_suffix(".mp4").write_bytes(b"fake")
    assert find_unfinished_recordings(tmp_path) == []


def test_non_screenrec_mkv_files_are_ignored(tmp_path: Path):
    (tmp_path / "other.mkv").write_bytes(b"fake")
    assert find_unfinished_recordings(tmp_path) == []


def test_empty_directory_has_no_unfinished_recordings(tmp_path: Path):
    assert find_unfinished_recordings(tmp_path) == []
