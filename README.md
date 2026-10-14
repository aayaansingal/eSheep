# eSheep

The classic desktop sheep, now on **macOS, Linux and Windows**.

eSheep wanders across your screen, walks along the bottom of the desktop, climbs
onto your windows, falls off when you move them, sleeps, and occasionally gets
abducted. This project is a cross-platform port of the original Windows-only
[eSheep / desktopPet](https://github.com/Adrianotiger/desktopPet) by Adriano
Petrucci. It reads the **same pet XML files**, so community pets work too.

## Download

Get the latest version from the
**[Releases page](https://github.com/aayaansingal/esheep/releases/latest)**:

| System | File |
| --- | --- |
| macOS (Apple Silicon: M1 or newer) | `eSheep-…-macOS-arm64.dmg` |
| macOS (Intel) | `eSheep-…-macOS-x64.dmg` |
| Windows 10 / 11 | `eSheep-…-Windows-x64.exe` |
| Linux (x86-64) | `eSheep-…-Linux-x64.tar.gz` |

These apps aren't code-signed (signing costs money every year), so your system
will warn you the first time you open one. That's expected; here's how to get past it:

<details>
<summary><b>macOS</b></summary>

1. Open the `.dmg` and drag **eSheep** into **Applications**.
2. Open eSheep. macOS says it "cannot verify" the app. Click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down, and click
   **Open Anyway** next to the eSheep message. Confirm with your password.

You only have to do this once. Alternatively, run this in Terminal:
`xattr -dr com.apple.quarantine /Applications/eSheep.app`

eSheep lives in the menu bar (no Dock icon). Look for the little sheep at the top of the screen.
</details>

<details>
<summary><b>Windows</b></summary>

1. Download and run `eSheep-…-Windows-x64.exe`. No installation needed.
2. If SmartScreen says "Windows protected your PC", click **More info → Run anyway**.

eSheep appears in the system tray (you might need to click the **^** arrow next to the clock).
</details>

<details>
<summary><b>Linux</b></summary>

```bash
tar -xzf eSheep-*-Linux-x64.tar.gz
./esheep/esheep
```

If it fails to start with an error about the `xcb` platform plugin, install the
Qt runtime library it needs: `sudo apt install libxcb-cursor0` on Debian or Ubuntu
(`xcb-util-cursor` on Fedora or Arch).
</details>

## Using it

| Action | What happens |
| --- | --- |
| Left-drag a sheep | Pick it up and move it |
| Drag and release quickly | Throw it! It bounces off screen edges |
| Right-click a sheep | Menu: remove this sheep, add another, open a pet file, quit |
| Tray / menu-bar icon | Same menu (if your desktop has a system tray) |

### Other pets

Any pet from the original project works. Download an `animations.xml` from
[desktopPet/Pets](https://github.com/Adrianotiger/desktopPet/tree/master/Pets)
and open it with **Open pet file…** in the menu.

## Platform notes

| | Walks on taskbar / Dock | Walks on windows | Notes |
| --- | --- | --- | --- |
| **macOS** | ✅ | ✅ | No Dock icon; the sheep appears on every Space. |
| **Windows** | ✅ | ✅ | Mixed-DPI multi-monitor setups may be slightly off. |
| **Linux (X11)** | ✅ | ✅ | |
| **Linux (Wayland)** | ✅ | X11 apps only | Wayland doesn't allow apps to position windows, so eSheep runs through XWayland automatically. |

---

## Run from source with Python

Prefer not to run a downloaded binary, or using a system without a prebuilt
download? eSheep runs anywhere Python 3.10+ and Qt do.

```bash
git clone https://github.com/aayaansingal/esheep.git
cd esheep
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install .
esheep
```

Command-line options:

```bash
esheep --count 3                      # start with three sheep
esheep --pet path/to/animations.xml   # use another eSheep pet
```

## Development

```bash
pip install -e '.[dev]'
pytest
python -m esheep
```

To build the downloadable app for your own OS (the output goes to `dist/release/`):

```bash
pip install -e '.[build]'
python packaging/build.py
```

**Releasing:** bump `__version__` in `src/esheep/__init__.py`, commit, then push a
matching tag (`git tag v0.2.0 && git push origin v0.2.0`). GitHub Actions builds
all four downloads and attaches them to a new release. Normal pushes only run the tests.

Code layout (`src/esheep/`):

- `pet_definition.py`: parses the original `animations.xml` format
- `expressions.py`: safely evaluates XML expressions such as `screenW-imageW`
- `pet_window.py`: one pet; a port of the original animation engine
- `sprites.py`: slices the sprite sheet into frames and click masks
- `desktop/`: finds other windows to walk on (one backend per OS)
- `platform_support.py`: per-OS window tweaks
- `app.py`: tray icon, menus and command-line entry point

Packaging lives in `packaging/` (PyInstaller spec, icon generator, build
script), and CI in `.github/workflows/`.

## Credits and licence

MIT licensed; see [LICENSE](LICENSE). The sheep artwork, pet format and original
behaviour are by Adriano Petrucci and contributors, also MIT licensed. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
