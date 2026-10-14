"""Load an original eSheep ``animations.xml`` pet file into plain Python objects.

The format is documented upstream at
https://github.com/Adrianotiger/desktopPet (Resources/animations.xsd).
Expression strings (``<x>``, ``<interval>``, ``repeat=""``...) are kept as text
and evaluated later, because they can depend on the screen or on randomness.
"""

from __future__ import annotations

import base64
import random
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from enum import IntFlag
from pathlib import Path


class Surface(IntFlag):
    """Where the pet currently is; mirrors upstream's ``TOnly`` flags."""

    TASKBAR = 0x01
    WINDOW = 0x02
    HORIZONTAL = 0x04
    HORIZONTAL_PLUS = 0x06
    VERTICAL = 0x08
    NONE = 0x7F    # "no restriction": matches every surface


ONLY_FLAG_NAMES = {
    "taskbar": Surface.TASKBAR,
    "window": Surface.WINDOW,
    "horizontal": Surface.HORIZONTAL,
    "horizontal+": Surface.HORIZONTAL_PLUS,
    "vertical": Surface.VERTICAL,
}


@dataclass
class Movement:
    """Start or end values of an animation; numbers are interpolated between them."""

    x: str = "0"
    y: str = "0"
    interval: str = "1000"
    offset_y: int = 0
    opacity: float = 1.0


@dataclass
class NextAnimation:
    animation_id: int
    probability: int
    only: Surface = Surface.NONE


@dataclass
class Sequence:
    frames: list[int]
    repeat: str = "0"
    repeat_from: int = 0
    action: str = ""


@dataclass
class Animation:
    animation_id: int
    name: str
    start: Movement
    end: Movement
    sequence: Sequence
    on_sequence_end: list[NextAnimation] = field(default_factory=list)
    on_border: list[NextAnimation] = field(default_factory=list)
    on_gravity: list[NextAnimation] = field(default_factory=list)

    @property
    def has_gravity(self) -> bool:
        return len(self.on_gravity) > 0


@dataclass
class Spawn:
    spawn_id: int
    probability: int
    x: str
    y: str
    next_animation_id: int


@dataclass
class Child:
    """A secondary pet window created when its parent starts an animation."""

    parent_animation_id: int
    x: str
    y: str
    next_animation_id: int


@dataclass
class PetDefinition:
    title: str
    pet_name: str
    author: str
    version: str
    info: str
    tiles_x: int
    tiles_y: int
    sprite_png: bytes
    transparency_color: str
    icon_data: bytes
    animations: dict[int, Animation]
    spawns: list[Spawn]
    children: dict[int, list[Child]]

    # Animations with special names are triggered by the app itself.
    drag_animation_id: int = 1
    fall_animation_id: int = 1
    kill_animation_id: int = -1
    sync_animation_id: int = 1
    toss_animation_id: int = -1
    fall_soft_animation_id: int = 1
    fall_hard_animation_id: int = 1

    def pick_spawn(self, rng: random.Random) -> Spawn:
        """Pick a spawn weighted by probability (same algorithm as upstream)."""
        if not self.spawns:
            first_animation_id = next(iter(self.animations), 1)
            return Spawn(0, 100, "0", "0", first_animation_id)

        total_probability = sum(spawn.probability for spawn in self.spawns)
        random_value = rng.randrange(total_probability) if total_probability > 0 else 0
        cumulative = 0
        for spawn in self.spawns:
            cumulative += spawn.probability
            if cumulative >= random_value:
                return spawn
        return self.spawns[0]


def pick_next_animation(candidates: list[NextAnimation], surface: Surface,
                        rng: random.Random) -> int:
    """Choose the next animation id, or -1 when the pet should re-spawn.

    Only candidates whose ``only`` flag matches the current surface take part,
    and each one's chance is proportional to its probability.
    """
    allowed = [
        candidate for candidate in candidates
        if candidate.only == Surface.NONE or (candidate.only & surface) != 0
    ]
    total_probability = sum(candidate.probability for candidate in allowed)
    if total_probability <= 0:
        return -1

    random_value = rng.randint(1, total_probability)
    cumulative = 0
    for candidate in allowed:
        cumulative += candidate.probability
        if cumulative >= random_value:
            return candidate.animation_id
    return -1


# --------------------------------------------------------------------------
# XML parsing
# --------------------------------------------------------------------------

def load_pet_definition(path: str | Path) -> PetDefinition:
    """Parse a pet XML file from disk."""
    return parse_pet_definition(Path(path).read_bytes())


def parse_pet_definition(xml_bytes: bytes) -> PetDefinition:
    root = ElementTree.fromstring(xml_bytes)
    _strip_namespaces(root)

    header = root.find("header")
    image = root.find("image")
    if image is None:
        raise ValueError("pet file has no <image> section")

    animations = _parse_animations(root.find("animations"))
    if not animations:
        raise ValueError("pet file has no animations")

    definition = PetDefinition(
        title=_text(header, "title", "Unnamed pet"),
        pet_name=_text(header, "petname", "Pet"),
        author=_text(header, "author", ""),
        version=_text(header, "version", ""),
        info=_text(header, "info", ""),
        tiles_x=int(_text(image, "tilesx", "1")),
        tiles_y=int(_text(image, "tilesy", "1")),
        sprite_png=_decode_base64(_text(image, "png", "")),
        transparency_color=_text(image, "transparency", "Magenta"),
        icon_data=_decode_base64(_text(header, "icon", "")),
        animations=animations,
        spawns=_parse_spawns(root.find("spawns")),
        children=_parse_children(root.find("childs")),
    )
    _assign_special_animations(definition)
    return definition


def _strip_namespaces(root: ElementTree.Element) -> None:
    """Pet files may or may not declare the eSheep namespace; ignore it."""
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]


def _text(parent: ElementTree.Element | None, tag: str, default: str) -> str:
    if parent is None:
        return default
    element = parent.find(tag)
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _decode_base64(text: str) -> bytes:
    if not text:
        return b""
    if ";base64," in text:               # tolerate data: URLs
        text = text.split(";base64,", 1)[1]
    cleaned = "".join(text.split())
    cleaned += "=" * (-len(cleaned) % 4)  # upstream pads missing '=' too
    return base64.b64decode(cleaned)


def _int_attribute(element: ElementTree.Element, name: str, default: int) -> int:
    try:
        return int(element.get(name, default))
    except ValueError:
        return default


def _parse_movement(element: ElementTree.Element | None) -> Movement:
    if element is None:
        return Movement()
    return Movement(
        x=_text(element, "x", "0"),
        y=_text(element, "y", "0"),
        interval=_text(element, "interval", "1000"),
        offset_y=int(float(_text(element, "offsety", "0"))),
        opacity=float(_text(element, "opacity", "1.0")),
    )


def _parse_next_list(parent: ElementTree.Element | None) -> list[NextAnimation]:
    if parent is None:
        return []
    next_animations = []
    for element in parent.findall("next"):
        # Missing probability means 0, as with upstream's XmlSerializer.
        next_animations.append(NextAnimation(
            animation_id=int((element.text or "0").strip()),
            probability=_int_attribute(element, "probability", 0),
            only=ONLY_FLAG_NAMES.get(element.get("only", "").strip().lower(), Surface.NONE),
        ))
    return next_animations


def _parse_animations(section: ElementTree.Element | None) -> dict[int, Animation]:
    animations: dict[int, Animation] = {}
    if section is None:
        return animations

    for element in section.findall("animation"):
        animation_id = _int_attribute(element, "id", 0)
        sequence_element = element.find("sequence")
        if sequence_element is None:
            continue

        sequence = Sequence(
            frames=[int(frame.text) for frame in sequence_element.findall("frame") if frame.text],
            repeat=sequence_element.get("repeat", "0") or "0",
            repeat_from=_int_attribute(sequence_element, "repeatfrom", 0),
            action=_text(sequence_element, "action", ""),
        )
        if not sequence.frames:
            continue

        animations[animation_id] = Animation(
            animation_id=animation_id,
            name=_text(element, "name", str(animation_id)),
            start=_parse_movement(element.find("start")),
            end=_parse_movement(element.find("end")),
            sequence=sequence,
            on_sequence_end=_parse_next_list(sequence_element),
            on_border=_parse_next_list(element.find("border")),
            on_gravity=_parse_next_list(element.find("gravity")),
        )
    return animations


def _parse_spawns(section: ElementTree.Element | None) -> list[Spawn]:
    if section is None:
        return []
    spawns = []
    for element in section.findall("spawn"):
        spawns.append(Spawn(
            spawn_id=_int_attribute(element, "id", 0),
            probability=_int_attribute(element, "probability", 0),
            x=_text(element, "x", "0"),
            y=_text(element, "y", "0"),
            next_animation_id=int(_text(element, "next", "1")),
        ))
    return spawns


def _parse_children(section: ElementTree.Element | None) -> dict[int, list[Child]]:
    children: dict[int, list[Child]] = {}
    if section is None:
        return children
    for element in section.findall("child"):
        parent_animation_id = _int_attribute(element, "animationid", 0)
        children.setdefault(parent_animation_id, []).append(Child(
            parent_animation_id=parent_animation_id,
            x=_text(element, "x", "0"),
            y=_text(element, "y", "0"),
            next_animation_id=int(_text(element, "next", "1")),
        ))
    return children


def _assign_special_animations(definition: PetDefinition) -> None:
    """Animations named "drag", "fall", "kill"... are triggered by the app."""
    special_names = {
        "drag": "drag_animation_id",
        "fall": "fall_animation_id",
        "kill": "kill_animation_id",
        "sync": "sync_animation_id",
        "toss": "toss_animation_id",
        "fall soft": "fall_soft_animation_id",
        "fall hard": "fall_hard_animation_id",
    }
    for animation in definition.animations.values():
        attribute_name = special_names.get(animation.name.strip().lower())
        if attribute_name is not None:
            setattr(definition, attribute_name, animation.animation_id)


def bundled_pet_path(name: str = "esheep64") -> Path:
    """Path of a pet shipped inside this package."""
    return Path(__file__).parent / "pets" / name / "animations.xml"
