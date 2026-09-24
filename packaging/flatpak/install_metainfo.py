"""Install the AppStream metainfo with the current version as its release.

    python3 install_metainfo.py <metainfo template> <repository root> <destination>

`flatpak list` and software centres show the version from this file, so it is
taken from pyproject.toml (the only place the version is written) and the
date from that version's CHANGELOG heading. A build of unreleased work has no
heading yet and gets today's date.
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import date
from pathlib import Path


def release_date(changelog: str, version: str) -> str:
    match = re.search(rf"^## {re.escape(version)} - (\d{{4}}-\d{{2}}-\d{{2}})$", changelog, re.M)
    return match.group(1) if match else date.today().isoformat()


if __name__ == "__main__":
    template, root, destination = (Path(arg) for arg in sys.argv[1:4])
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    when = release_date((root / "CHANGELOG.md").read_text(), version)
    text = template.read_text()
    if text.count("<releases>\n") != 1:
        sys.exit(f"{template}: expected one <releases> element to fill in")
    release = f'    <release version="{version}" date="{when}" />\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text.replace("<releases>\n", "<releases>\n" + release))
