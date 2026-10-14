"""Generate app icons (.png, .ico, .icns) from a frame of the bundled sheep.

The XML's own icon is only 48x48, which looks blurry as a macOS app icon, so
we upscale a sprite frame with nearest-neighbour scaling to keep it pixel-crisp.

Usage: python packaging/make_icons.py <output-directory>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from esheep.pet_definition import bundled_pet_path, load_pet_definition  # noqa: E402

ICON_FRAME = 3          # the classic side-on walking sheep
ICON_SIZE = 1024
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def extract_frame(frame_index: int) -> Image.Image:
    definition = load_pet_definition(bundled_pet_path())
    sheet = Image.open(io.BytesIO(definition.sprite_png)).convert("RGBA")
    frame_width = sheet.width // definition.tiles_x
    frame_height = sheet.height // definition.tiles_y
    column = frame_index % definition.tiles_x
    row = frame_index // definition.tiles_x
    frame = sheet.crop((column * frame_width, row * frame_height,
                        (column + 1) * frame_width, (row + 1) * frame_height))
    # Trim empty borders so the sheep fills the icon.
    bounding_box = frame.getbbox()
    return frame.crop(bounding_box) if bounding_box else frame


def make_square_icon(frame: Image.Image, size: int) -> Image.Image:
    """Centre the frame on a transparent square, scaled by a whole-number factor."""
    padding_ratio = 0.9
    scale = max(1, int(size * padding_ratio / max(frame.width, frame.height)))
    scaled = frame.resize((frame.width * scale, frame.height * scale), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def main() -> None:
    output_directory = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icons")
    output_directory.mkdir(parents=True, exist_ok=True)

    icon = make_square_icon(extract_frame(ICON_FRAME), ICON_SIZE)
    icon.save(output_directory / "esheep.png")
    icon.save(output_directory / "esheep.ico", sizes=ICO_SIZES)
    icon.save(output_directory / "esheep.icns")
    print(f"icons written to {output_directory}")


if __name__ == "__main__":
    main()
