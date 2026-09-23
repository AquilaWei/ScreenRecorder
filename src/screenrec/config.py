"""Read and write the user's persisted settings (TOML under the platform config dir)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import tomli_w
from platformdirs import user_config_dir


@dataclass
class Settings:
    output_dir: str
    keep_mkv: bool = False
    indicator_opacity: float = 0.6


def config_path() -> Path:
    return Path(user_config_dir("screenrec")) / "settings.toml"


def load_settings(path: Path | None = None) -> Settings | None:
    """Return the persisted settings, or None if no config file exists yet."""
    path = path or config_path()
    if not path.exists():
        return None
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Settings(**data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(asdict(settings), f)
