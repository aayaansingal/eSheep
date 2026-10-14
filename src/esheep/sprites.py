"""Slice a pet's sprite sheet into individual frames, ready for drawing."""

from __future__ import annotations

from array import array

from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QColor, QImage, QPixmap, QRegion

from .pet_definition import PetDefinition


class SpriteSheet:
    """All frames of a pet, in both facing directions, plus their click masks.

    The original artwork faces left; flipped frames are used when the pet walks
    to the right. Masks make transparent pixels click-through and keep the
    background invisible on Linux desktops without a compositor.
    """

    def __init__(self, definition: PetDefinition):
        sheet = _load_sheet_with_transparency(definition)
        self.frame_width = sheet.width() // max(1, definition.tiles_x)
        self.frame_height = sheet.height() // max(1, definition.tiles_y)

        self._frames: list[QImage] = []
        self._flipped_frames: list[QImage] = []
        self._masks: dict[tuple[int, bool], QRegion] = {}

        for row in range(definition.tiles_y):
            for column in range(definition.tiles_x):
                frame = sheet.copy(column * self.frame_width, row * self.frame_height,
                                   self.frame_width, self.frame_height)
                self._frames.append(frame)
                self._flipped_frames.append(_mirror_horizontally(frame))

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def frame(self, index: int, flipped: bool) -> QImage:
        frames = self._flipped_frames if flipped else self._frames
        return frames[index % len(frames)]

    def mask(self, index: int, flipped: bool) -> QRegion:
        """Region covering the frame's visible pixels (cached)."""
        key = (index % self.frame_count, flipped)
        if key not in self._masks:
            alpha_mask = self.frame(index, flipped).createAlphaMask()
            region = QRegion(QBitmap.fromImage(alpha_mask))
            # A fully transparent frame would make the window unclickable and,
            # on some platforms, an empty mask means "no mask"; keep 1 pixel.
            if region.isEmpty():
                region = QRegion(0, 0, 1, 1)
            self._masks[key] = region
        return self._masks[key]


def _load_sheet_with_transparency(definition: PetDefinition) -> QImage:
    pixmap = QPixmap()
    if not pixmap.loadFromData(definition.sprite_png):
        raise ValueError("could not decode the pet's sprite sheet image")

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)

    # Older pets have no alpha channel and use a colour key (usually magenta).
    key_color = QColor(definition.transparency_color.strip())
    if key_color.isValid():
        image = _clear_key_color(image, key_color)
    return image


def _clear_key_color(image: QImage, key_color: QColor) -> QImage:
    """Return a copy where every opaque pixel of the key colour is transparent."""
    # Format_ARGB32 stores each pixel as one native-endian 32-bit 0xAARRGGBB word.
    key_pixel = 0xFF000000 | (key_color.rgb() & 0x00FFFFFF)
    pixels = array("I", bytes(image.constBits()))
    for index, pixel in enumerate(pixels):
        if pixel == key_pixel:
            pixels[index] = 0

    cleared = QImage(pixels.tobytes(), image.width(), image.height(),
                     image.bytesPerLine(), QImage.Format.Format_ARGB32)
    return cleared.copy()   # detach from the temporary Python buffer


def _mirror_horizontally(image: QImage) -> QImage:
    if hasattr(image, "flipped"):              # Qt >= 6.9
        return image.flipped(Qt.Orientation.Horizontal)
    return image.mirrored(True, False)
