import random

from esheep.pet_definition import (
    NextAnimation, Surface, bundled_pet_path, load_pet_definition, parse_pet_definition,
    pick_next_animation,
)

MINIMAL_PET = b"""<?xml version="1.0"?>
<animations xmlns="https://esheep.petrucci.ch/">
  <header><title>Tiny</title><petname>Tiny</petname></header>
  <image><tilesx>2</tilesx><tilesy>1</tilesy><png>iVBORw0KGgo</png></image>
  <spawns>
    <spawn id="1" probability="100"><x>0</x><y>0</y><next probability="100">7</next></spawn>
  </spawns>
  <animations>
    <animation id="7">
      <name>walk</name>
      <start><x>-2</x><y>0</y><interval>200</interval></start>
      <end><x>-2</x><y>0</y><interval>200</interval></end>
      <sequence repeat="3" repeatfrom="1">
        <frame>0</frame><frame>1</frame>
        <next probability="10" only="taskbar">7</next>
        <next probability="5">7</next>
        <action>flip</action>
      </sequence>
      <gravity><next probability="100">7</next></gravity>
    </animation>
  </animations>
</animations>
"""


def test_bundled_sheep_loads():
    definition = load_pet_definition(bundled_pet_path())
    assert definition.pet_name == "eSheep"
    assert (definition.tiles_x, definition.tiles_y) == (16, 11)
    assert definition.sprite_png.startswith(b"\x89PNG")
    assert len(definition.animations) > 50
    assert len(definition.spawns) == 4
    # Special animations are wired up by name.
    assert definition.animations[definition.drag_animation_id].name == "drag"
    assert definition.animations[definition.fall_animation_id].name == "fall"
    assert definition.animations[definition.kill_animation_id].name == "kill"
    # Every referenced animation exists.
    for animation in definition.animations.values():
        for candidate in animation.on_sequence_end + animation.on_border + animation.on_gravity:
            assert candidate.animation_id in definition.animations
    for children in definition.children.values():
        for child in children:
            assert child.next_animation_id in definition.animations


def test_minimal_pet_parses_details():
    definition = parse_pet_definition(MINIMAL_PET)
    walk = definition.animations[7]
    assert walk.sequence.frames == [0, 1]
    assert walk.sequence.repeat == "3"
    assert walk.sequence.repeat_from == 1
    assert walk.sequence.action == "flip"
    assert walk.start.opacity == 1.0 and walk.start.offset_y == 0
    assert walk.on_sequence_end[0].only == Surface.TASKBAR
    assert walk.on_sequence_end[1].only == Surface.NONE
    assert walk.has_gravity
    assert definition.spawns[0].next_animation_id == 7


def test_pick_next_respects_only_flags():
    candidates = [
        NextAnimation(1, 100, Surface.TASKBAR),
        NextAnimation(2, 100, Surface.WINDOW),
    ]
    rng = random.Random(0)
    picks = {pick_next_animation(candidates, Surface.WINDOW, rng) for _ in range(50)}
    assert picks == {2}
    # "NONE" as the current surface matches every flag, as in the original.
    picks = {pick_next_animation(candidates, Surface.NONE, rng) for _ in range(200)}
    assert picks == {1, 2}


def test_pick_next_without_candidates_respawns():
    rng = random.Random(0)
    assert pick_next_animation([], Surface.NONE, rng) == -1
    assert pick_next_animation([NextAnimation(3, 0)], Surface.NONE, rng) == -1
    assert pick_next_animation([NextAnimation(3, 50, Surface.WINDOW)], Surface.TASKBAR, rng) == -1


def test_pick_spawn_weighting():
    definition = load_pet_definition(bundled_pet_path())
    rng = random.Random(42)
    counts = {}
    for _ in range(2000):
        spawn = definition.pick_spawn(rng)
        counts[spawn.spawn_id] = counts.get(spawn.spawn_id, 0) + 1
    # Spawn 2 (probability 80 of 106) dominates.
    assert counts[2] > counts[1] > counts[3]
