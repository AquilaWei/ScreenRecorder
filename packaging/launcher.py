"""PyInstaller entry script for the packaged app."""

import sys

from screenrec.app import run

if __name__ == "__main__":
    sys.exit(run())
