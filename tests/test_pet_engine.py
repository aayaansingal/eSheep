"""Drive the real pet engine headlessly (Qt "offscreen" platform) with fake windows."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from esheep.desktop import DesktopWindow, WindowBackend, WindowTracker
from esheep.pet_definition import bundled_pet_path, load_pet_definition
from esheep.pet_window import PetWindow
from esheep.sprites import SpriteSheet


class FakeBackend(WindowBackend):
    def __init__(self, windows):
        self.windows = windows

    def list_windows(self):
        return list(self.windows)


class FakeManager:
    def __init__(self):
        self.children = []

    def create_child(self, parent, child):
        self.children.append(child)

    def show_context_menu(self, pet, position):
        pass


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def sheep_parts(app):
    definition = load_pet_definition(bundled_pet_path())
    return definition, SpriteSheet(definition)


def make_pet(sheep_parts, windows=()):
    definition, sprites = sheep_parts
    tracker = WindowTracker(FakeBackend(list(windows)))
    tracker.CACHE_SECONDS = -1          # always re-query the fake backend
    pet = PetWindow(FakeManager(), definition, sprites, tracker)
    pet.show()
    return pet


def run_steps(pet, count):
    for _ in range(count):
        pet._on_step_timer()


def test_sprite_sheet_frames(sheep_parts):
    _, sprites = sheep_parts
    assert (sprites.frame_width, sprites.frame_height) == (40, 40)
    assert sprites.frame_count == 16 * 11
    assert not sprites.mask(2, flipped=False).isEmpty()


def test_falling_pet_lands_on_screen_bottom(sheep_parts):
    pet = make_pet(sheep_parts)
    area = pet._screen_area()
    pet.position_x, pet.position_y = area.x() + 300, area.y() + 50
    pet.set_new_animation(pet.definition.fall_animation_id)
    for _ in range(400):
        pet._on_step_timer()
        if not pet.animation.name.startswith("fall"):
            break
    ground = area.y() + area.height() - pet.height_px
    assert pet.position_y == ground
    pet.close()


def test_falling_pet_lands_on_window(sheep_parts):
    window = DesktopWindow(1, left=100, top=400, right=700, bottom=600)
    pet = make_pet(sheep_parts, [window])
    pet.position_x, pet.position_y = 300, 100
    pet.set_new_animation(pet.definition.fall_animation_id)
    for _ in range(200):
        pet._on_step_timer()
        if pet.surface_window is not None and pet.animation.name not in ("fall", "fall fast"):
            break
    assert pet.surface_window is not None
    assert pet.position_y == window.top - pet.height_px
    pet.close()


def test_pet_follows_moving_window_and_falls_when_it_closes(sheep_parts):
    window = DesktopWindow(1, left=100, top=400, right=700, bottom=600)
    pet = make_pet(sheep_parts, [window])
    backend = pet.window_tracker._backend
    pet.position_x, pet.position_y = 300, window.top - pet.height_px
    pet.surface_window = window
    pet.set_new_animation(1)              # walk (has gravity)
    run_steps(pet, 2)

    moved = DesktopWindow(1, left=150, top=350, right=750, bottom=550)
    backend.windows = [moved]
    x_before = pet.position_x
    run_steps(pet, 1)
    assert pet.position_y == moved.top - pet.height_px
    assert pet.position_x > x_before          # carried 50px right (minus its own steps)

    backend.windows = []
    run_steps(pet, 2)
    assert pet.surface_window is None
    assert pet.animation.name.startswith("fall")
    pet.close()


def test_drag_animation_runs_without_moving(sheep_parts):
    pet = make_pet(sheep_parts)
    pet.position_x, pet.position_y = 400, 300
    pet.is_dragging = True
    pet.set_new_animation(pet.definition.drag_animation_id)
    run_steps(pet, 50)
    assert (pet.position_x, pet.position_y) == (400, 300)
    assert pet.animation.name == "drag"
    pet.close()


def test_long_random_run_stays_stable(sheep_parts):
    """Hammer the engine: thousands of steps must never raise."""
    pet = make_pet(sheep_parts, [DesktopWindow(1, 200, 500, 900, 800)])
    pet.spawn()
    run_steps(pet, 5000)
    assert pet.animation is not None
    pet.close()
