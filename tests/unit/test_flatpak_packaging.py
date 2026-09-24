import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLATPAK = ROOT / "packaging" / "flatpak"


def _install_metainfo():
    spec = importlib.util.spec_from_file_location(
        "install_metainfo", FLATPAK / "install_metainfo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flatpak_wheels_are_the_versions_uv_lock_pins():
    # The manifest pins wheels by hand (Flatpak builds offline); a dependency
    # bump in uv.lock alone would leave the Flatpak on the old version.
    manifest = (FLATPAK / "io.github.AquilaWei.ScreenRecorder.yml").read_text()
    shipped = dict(re.findall(r"/([a-z_]+)-([0-9][^-]*)-py3-none-any\.whl", manifest))
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {p["name"].replace("-", "_"): p["version"] for p in lock["package"]}
    assert shipped == {name: locked[name] for name in ("jeepney", "platformdirs", "tomli_w")}


def test_release_date_comes_from_the_versions_changelog_heading():
    changelog = "# Changelog\n\n## Unreleased\n\n## 0.1.1 - 2026-09-24\n\n## 0.1.0 - 2026-09-20\n"
    assert _install_metainfo().release_date(changelog, "0.1.1") == "2026-09-24"


def test_release_date_does_not_match_a_longer_version_with_the_same_prefix():
    changelog = "## 0.1.10 - 2026-12-01\n\n## 0.1.1 - 2026-09-24\n"
    assert _install_metainfo().release_date(changelog, "0.1.1") == "2026-09-24"
