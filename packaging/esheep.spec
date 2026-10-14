# PyInstaller build recipe. Run through packaging/build.py, which creates the icons first.
#
# macOS   -> dist/eSheep.app          (folder-based bundle, the recommended layout for .app)
# Windows -> dist/eSheep.exe          (single file, no console window)
# Linux   -> dist/esheep              (single executable)

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICONS = ROOT / "build" / "icons"
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (ROOT / "src" / "esheep" / "__init__.py").read_text()).group(1)

# Window-detection backends are imported lazily, so name the right one explicitly.
if sys.platform == "darwin":
    platform_imports = ["esheep.desktop.macos", "Quartz", "AppKit", "objc"]
elif sys.platform == "win32":
    platform_imports = ["esheep.desktop.windows"]
else:
    platform_imports = ["esheep.desktop.x11", "Xlib", "Xlib.display"]

analysis = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "esheep" / "pets"), "esheep/pets")],
    hiddenimports=platform_imports,
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
python_archive = PYZ(analysis.pure)

if sys.platform == "darwin":
    executable = EXE(
        python_archive, analysis.scripts, [],
        exclude_binaries=True,
        name="eSheep",
        console=False,
        icon=str(ICONS / "esheep.icns"),
    )
    collected = COLLECT(executable, analysis.binaries, analysis.datas, name="eSheep")
    app = BUNDLE(
        collected,
        name="eSheep.app",
        icon=str(ICONS / "esheep.icns"),
        bundle_identifier="org.esheep.crossplatform",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "eSheep",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,                 # menu-bar app: no Dock icon
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
    executable = EXE(
        python_archive, analysis.scripts, analysis.binaries, analysis.datas, [],
        name="eSheep" if sys.platform == "win32" else "esheep",
        console=False,
        icon=str(ICONS / "esheep.ico") if sys.platform == "win32" else None,
        upx=False,          # UPX-compressed executables trigger antivirus false positives
    )
