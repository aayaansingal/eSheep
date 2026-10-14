"""Build a downloadable eSheep app for the current operating system.

Usage (from the repository root, with the dev environment active):

    pip install -e '.[build]'
    python packaging/build.py

The finished download lands in ``dist/release/``:

* macOS   -> eSheep-<version>-macOS-<arch>.dmg
* Windows -> eSheep-<version>-Windows-x64.exe
* Linux   -> eSheep-<version>-Linux-<arch>.tar.gz
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RELEASE = DIST / "release"


def read_version() -> str:
    init_text = (ROOT / "src" / "esheep" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', init_text).group(1)


def architecture_name() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT)


def build_with_pyinstaller() -> None:
    run([sys.executable, str(ROOT / "packaging" / "make_icons.py"), str(ROOT / "build" / "icons")])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "pyinstaller"),
         str(ROOT / "packaging" / "esheep.spec")])


def package_macos(version: str) -> Path:
    """Wrap the .app in a disk image with the usual drag-to-Applications shortcut."""
    output = RELEASE / f"eSheep-{version}-macOS-{architecture_name()}.dmg"
    with tempfile.TemporaryDirectory() as staging_directory:
        staging = Path(staging_directory)
        shutil.copytree(DIST / "eSheep.app", staging / "eSheep.app", symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        output.unlink(missing_ok=True)
        run(["hdiutil", "create", "-volname", "eSheep", "-srcfolder", str(staging),
             "-ov", "-format", "UDZO", str(output)])
    return output


def package_windows(version: str) -> Path:
    output = RELEASE / f"eSheep-{version}-Windows-{architecture_name()}.exe"
    shutil.copy2(DIST / "eSheep.exe", output)
    return output


def package_linux(version: str) -> Path:
    """A tarball keeps the executable permission that a plain download would lose."""
    output = RELEASE / f"eSheep-{version}-Linux-{architecture_name()}.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        archive.add(DIST / "esheep", arcname="esheep/esheep")
        archive.add(ROOT / "LICENSE", arcname="esheep/LICENSE")
        archive.add(ROOT / "THIRD_PARTY_NOTICES.md", arcname="esheep/THIRD_PARTY_NOTICES.md")
    return output


def main() -> None:
    version = read_version()
    build_with_pyinstaller()
    RELEASE.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        output = package_macos(version)
    elif sys.platform == "win32":
        output = package_windows(version)
    else:
        output = package_linux(version)
    print(f"\nBuilt {output.relative_to(ROOT)} ({output.stat().st_size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    main()
