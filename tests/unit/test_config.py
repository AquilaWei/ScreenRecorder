from pathlib import Path

from screenrec.config import Settings, load_settings, save_settings


def test_load_settings_returns_none_when_no_file_exists(tmp_path: Path):
    assert load_settings(tmp_path / "missing.toml") is None


def test_save_then_load_settings_round_trips(tmp_path: Path):
    path = tmp_path / "settings.toml"
    original = Settings(output_dir="D:/Videos", keep_mkv=True, indicator_opacity=0.4)
    save_settings(original, path)
    assert load_settings(path) == original


def test_save_settings_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "settings.toml"
    save_settings(Settings(output_dir="D:/Videos"), path)
    assert path.exists()
