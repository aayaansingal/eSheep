"""Entry script for PyInstaller builds (it needs a file, not a package entry point)."""

import sys

from esheep.app import main

if __name__ == "__main__":
    sys.exit(main())
