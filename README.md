# eSheep

The classic desktop sheep, now on **macOS, Linux and Windows**.

eSheep wanders across your screen, walks along the bottom of the desktop, climbs
onto your windows, falls off when you move them, sleeps, and occasionally gets
abducted. This project is a cross-platform port of the original Windows-only
[eSheep / desktopPet](https://github.com/Adrianotiger/desktopPet) by Adriano
Petrucci. It reads the **same pet XML files**, so community pets work too.

## Install and run

You need Python 3.10 or newer.

```bash
git clone https://github.com/<your-username>/esheep.git
cd esheep
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install .
esheep
```

Options:

```bash
esheep --count 3                   # start with three sheep
esheep --pet path/to/animations.xml   # use another eSheep pet
```

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
and open it with **Open pet file…** or `--pet`.

## Platform notes

| | Walks on taskbar / Dock | Walks on windows | Notes |
| --- | --- | --- | --- |
| **macOS** | ✅ | ✅ | No Dock icon; the sheep appears on every Space. |
| **Windows** | ✅ | ✅ | Mixed-DPI multi-monitor setups may be slightly off. |
| **Linux (X11)** | ✅ | ✅ | |
| **Linux (Wayland)** | ✅ | X11 apps only | Wayland doesn't allow apps to position windows, so eSheep runs through XWayland automatically. |

## Development

```bash
pip install -e '.[dev]'
pytest
python -m esheep
```

Code layout (`src/esheep/`):

- `pet_definition.py`: parses the original `animations.xml` format
- `expressions.py`: safely evaluates XML expressions such as `screenW-imageW`
- `pet_window.py`: one pet; a port of the original animation engine
- `sprites.py`: slices the sprite sheet into frames and click masks
- `desktop/`: finds other windows to walk on (one backend per OS)
- `platform_support.py`: per-OS window tweaks
- `app.py`: tray icon, menus and command-line entry point

## Credits and licence

MIT licensed; see [LICENSE](LICENSE). The sheep artwork, pet format and original
behaviour are by Adriano Petrucci and contributors, also MIT licensed. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
