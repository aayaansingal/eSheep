"""A single pet: a small transparent window that runs the eSheep animation engine.

The step logic closely follows ``FormPet.NextStep`` from the original Windows
application so that existing pet XML files behave the same way. Each timer
tick shows one frame, moves the window and decides whether a border, gravity
or the end of the sequence triggers the next animation.
"""

from __future__ import annotations

import itertools
import math
import random
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QScreen
from PySide6.QtWidgets import QWidget

from . import platform_support
from .desktop import DesktopWindow, WindowTracker
from .expressions import ExpressionContext, evaluate
from .pet_definition import Animation, Child, PetDefinition, Surface, pick_next_animation
from .sprites import SpriteSheet

if TYPE_CHECKING:
    from .app import PetManager

MAX_CHILD_DEPTH = 5             # children may create children, up to this depth
_surface_serials = itertools.count(1)
GRAVITY_SNAP_PIXELS = 3         # pets this close to the ground don't fall
TOSS_TICK_MS = 16
FOLLOW_TICK_MS = 16             # how often a standing pet re-checks what it stands on
TOSS_FRAME_INTERVAL_MS = 30
TOSS_MINIMUM_FORCE = 5
HARD_LANDING_VELOCITY = 40
DRAG_SAMPLE_WINDOW_MS = 80


class PetWindow(QWidget):
    closed = Signal(object)

    def __init__(self, manager: PetManager, definition: PetDefinition, sprites: SpriteSheet,
                 window_tracker: WindowTracker, screen: QScreen | None = None,
                 child_depth: int = 0, moving_left: bool = True, random_spawn: int | None = None):
        super().__init__(None, platform_support.pet_window_flags())
        self.manager = manager
        self.definition = definition
        self.sprites = sprites
        self.window_tracker = window_tracker
        self.rng = random.Random()
        self.child_depth = child_depth
        self.children_pets: list[PetWindow] = []

        platform_support.configure_pet_widget(self)
        self.setFixedSize(sprites.frame_width, sprites.frame_height)
        self.setWindowTitle(definition.pet_name)

        # Position and appearance (position_x / position_y are authoritative;
        # the window itself is moved to the rounded values).
        self.pet_screen = screen or QGuiApplication.primaryScreen()
        self.position_x = 0.0
        self.position_y = 0.0
        self.offset_y = 0.0
        self.opacity = 1.0
        self.moving_left = moving_left
        self.current_frame = 0
        self.random_spawn = random_spawn if random_spawn is not None else self.rng.randint(10, 89)

        # Animation state, resolved from the XML when an animation starts.
        self.animation: Animation | None = None
        self.animation_step = 0
        self.total_steps = 1
        self.start_x = self.start_y = self.end_x = self.end_y = 0
        self.start_interval = self.end_interval = 1000
        self.next_interval = 1000
        self.respawned_during_step = False

        # The window (or other pet) this pet is standing on (None = taskbar / free fall).
        self.surface_window: DesktopWindow | None = None
        # Identifies this pet as a surface for others. It changes on every
        # spawn, so pets riding on it fall off instead of teleporting along.
        self.surface_serial = next(_surface_serials)

        # Mouse interaction.
        self.is_dragging = False
        self.is_tossing = False
        self.grab_offset = QPointF()
        self.drag_samples: list[tuple[float, float, float]] = []
        self.toss_force_x = 0.0
        self.toss_force_y = 0.0
        self.toss_vertical_velocity = 0.0
        self.toss_updated_at = 0.0

        # Closing: the "kill" animation fades the pet out before it disappears.
        self.is_dying = False
        self.kill_fade_opacity = 1.0

        self.step_timer = QTimer(self)
        self.step_timer.setSingleShot(True)
        self.step_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.step_timer.timeout.connect(self._on_step_timer)

        self.toss_timer = QTimer(self)
        self.toss_timer.setInterval(TOSS_TICK_MS)
        self.toss_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.toss_timer.timeout.connect(self._on_toss_timer)

        # Keeps the pet on a moving window/pet between animation steps, since
        # many animations (sleeping, turning...) don't run the gravity check.
        self.follow_timer = QTimer(self)
        self.follow_timer.setInterval(FOLLOW_TICK_MS)
        self.follow_timer.timeout.connect(self._on_follow_timer)

    # ------------------------------------------------------------------
    # Screen geometry helpers
    # ------------------------------------------------------------------

    @property
    def width_px(self) -> int:
        return self.sprites.frame_width

    @property
    def height_px(self) -> int:
        return self.sprites.frame_height

    def _screen(self) -> QScreen:
        # The screen may have been unplugged since we stored it.
        if self.pet_screen not in QGuiApplication.screens():
            self.pet_screen = QGuiApplication.primaryScreen()
        return self.pet_screen

    def _screen_bounds(self) -> QRect:
        return self._screen().geometry()

    def _screen_area(self) -> QRect:
        """The usable area: the screen minus taskbar / Dock / menu bar."""
        return self._screen().availableGeometry()

    @staticmethod
    def _right(rect: QRect) -> int:
        return rect.x() + rect.width()      # QRect.right() is inclusive; we want exclusive

    @staticmethod
    def _bottom(rect: QRect) -> int:
        return rect.y() + rect.height()

    def _expression_context(self, image_x: int = -1, image_y: int = -1,
                            parent_flipped: bool = False) -> ExpressionContext:
        bounds = self._screen_bounds()
        area = self._screen_area()
        return ExpressionContext(
            screen_w=bounds.width(),
            screen_h=bounds.height(),
            area_w=area.width(),
            area_h=self._bottom(area) - bounds.y(),   # bottom of usable area, screen-relative
            image_w=self.width_px,
            image_h=self.height_px,
            image_x=image_x,
            image_y=image_y,
            random_spawn=self.random_spawn,
            parent_flipped=parent_flipped,
            rng=self.rng,
        )

    # ------------------------------------------------------------------
    # Starting: spawn (normal pets) or child placement
    # ------------------------------------------------------------------

    def spawn(self) -> None:
        """Place the pet at one of the XML spawn points and start animating."""
        self.step_timer.stop()
        self.respawned_during_step = True
        self.animation_step = 0
        self.surface_window = None
        self.surface_serial = next(_surface_serials)
        self.random_spawn = self.rng.randint(10, 89)

        spawn = self.definition.pick_spawn(self.rng)
        context = self._expression_context()
        spawn_x = evaluate(spawn.x, context)
        spawn_y = evaluate(spawn.y, context)

        bounds = self._screen_bounds()
        self.position_y = bounds.y() + spawn_y
        if self.moving_left:
            self.position_x = bounds.x() + spawn_x
        else:
            # Mirror the spawn point when the pet walks to the right.
            self.position_x = bounds.x() + bounds.width() - spawn_x - self.width_px
        self.offset_y = 0.0

        next_id = spawn.next_animation_id
        if next_id not in self.definition.animations:
            next_id = next(iter(self.definition.animations))
        self.set_new_animation(next_id)

        self.opacity = 0.0          # the first frame is drawn on the first tick
        self._apply_position()
        if not self.isVisible():
            self.show()
            platform_support.after_pet_window_shown(self)
        self.step_timer.start(max(1, self.next_interval))

    def start_as_child(self, child: Child, parent: PetWindow) -> None:
        """Place a child pet relative to its parent and start its animation."""
        bounds = self._screen_bounds()
        context = self._expression_context(
            image_x=int(parent.position_x) - bounds.x(),
            image_y=int(parent.position_y) - bounds.y(),
            parent_flipped=not parent.moving_left,
        )
        self.position_x = bounds.x() + evaluate(child.x, context)
        self.position_y = bounds.y() + evaluate(child.y, context)
        self.offset_y = 0.0
        self.animation_step = 0
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.set_new_animation(child.next_animation_id)
        self._apply_position()
        self.show()
        platform_support.after_pet_window_shown(self)
        self.step_timer.start(max(1, self.next_interval))

    @property
    def is_child(self) -> bool:
        return self.child_depth > 0

    def as_surface(self) -> DesktopWindow:
        """This pet's on-screen rectangle, so that other pets can stand on it."""
        return DesktopWindow(
            window_id=-self.surface_serial,
            left=self.x(),
            top=self.y(),
            right=self.x() + self.width_px,
            bottom=self.y() + self.height_px,
        )

    # ------------------------------------------------------------------
    # Switching animations
    # ------------------------------------------------------------------

    def set_new_animation(self, animation_id: int) -> None:
        """Start an animation by id; an id of -1 (or unknown) re-spawns the pet."""
        if self.animation is not None and self.animation.animation_id == self.definition.kill_animation_id:
            return   # nothing interrupts the farewell animation

        if animation_id < 0 or animation_id not in self.definition.animations:
            if self.is_child:
                self.close()        # children have no spawn points
            else:
                self.spawn()
            return

        self.animation_step = -1
        self.animation = self.definition.animations[animation_id]
        self._resolve_animation_values()

        if animation_id in self.definition.children and self.child_depth < MAX_CHILD_DEPTH:
            for child in self.definition.children[animation_id]:
                self.manager.create_child(self, child)

        self.next_interval = self.start_interval

    def _resolve_animation_values(self) -> None:
        """Evaluate the animation's expressions (they may contain "random")."""
        animation = self.animation
        context = self._expression_context()
        self.start_x = evaluate(animation.start.x, context)
        self.start_y = evaluate(animation.start.y, context)
        self.end_x = evaluate(animation.end.x, context)
        self.end_y = evaluate(animation.end.y, context)
        self.start_interval = evaluate(animation.start.interval, context)
        self.end_interval = evaluate(animation.end.interval, context)

        frame_count = len(animation.sequence.frames)
        repeat = max(0, evaluate(animation.sequence.repeat, context))
        repeated_frames = max(0, frame_count - animation.sequence.repeat_from)
        self.total_steps = max(1, frame_count + repeated_frames * repeat)

    def _frame_for_step(self, step: int) -> int:
        """Sprite index for a step, honouring ``repeat`` and ``repeatfrom``."""
        frames = self.animation.sequence.frames
        if step < len(frames):
            return frames[max(0, step)]
        repeat_from = min(self.animation.sequence.repeat_from, len(frames) - 1)
        cycle_length = len(frames) - repeat_from
        index = (step - len(frames) + repeat_from) % cycle_length + repeat_from
        return frames[index]

    # ------------------------------------------------------------------
    # The animation step (one timer tick)
    # ------------------------------------------------------------------

    def _on_step_timer(self) -> None:
        if self.animation_step < 0:
            self.animation_step = 0
        self.respawned_during_step = False
        self.next_step()
        if not self.isVisible():
            return   # the pet closed itself during this step
        if not self.respawned_during_step:
            self.animation_step += 1
        self.step_timer.start(max(1, int(self.next_interval)))
        self._update_follow_timer()

    def next_step(self) -> None:
        """Advance the current animation by one step (port of ``NextStep``)."""
        step = self.animation_step
        self._show_frame(self._frame_for_step(step))
        self._interpolate_appearance(step)

        # While held or flying through the air, only the frames animate.
        if self.is_dragging or self.is_tossing:
            return

        dx, dy = self._interpolated_movement(step)
        if not self.moving_left:
            dx = -dx

        started_new_animation = False
        leaving_screen = False

        # 1. Horizontal borders (screen edges, or the edges of the window we stand on).
        if dx < 0:
            dx, started_new_animation, leaving_screen = self._check_left_border(dx)
        elif dx > 0:
            dx, started_new_animation, leaving_screen = self._check_right_border(dx)
        if self.respawned_during_step:
            return

        # 2. Vertical borders: landing on the taskbar / a window, or hitting the top.
        if not (started_new_animation or leaving_screen):
            if dy > 0:
                dy, started_new_animation = self._check_landing(dy)
            elif dy < 0:
                dy, started_new_animation, leaving_screen = self._check_top_border(dy)
        if self.respawned_during_step:
            return

        # 3. End of the sequence, or gravity pulling the pet down.
        if self.animation_step >= self.total_steps:
            started_new_animation |= self._finish_sequence(dy)
            if self.respawned_during_step or not self.isVisible():
                return
        elif self.animation.has_gravity:
            dy, fell = self._apply_gravity(dy)
            started_new_animation |= fell
            if self.respawned_during_step:
                return

        if started_new_animation:
            self.next_interval = 1     # play the new animation's first step right away
            self._show_frame(self.animation.sequence.frames[0])

        self.position_x += dx
        self.position_y += dy
        self._apply_position()

    def _interpolate_appearance(self, step: int) -> None:
        """Interval, opacity and vertical offset glide from START to END values."""
        animation = self.animation
        progress = step / self.total_steps
        if not self.is_tossing:
            self.next_interval = self.start_interval + int((self.end_interval - self.start_interval) * progress)
        self.opacity = animation.start.opacity + (animation.end.opacity - animation.start.opacity) * progress
        self.offset_y = animation.start.offset_y + int((animation.end.offset_y - animation.start.offset_y) * progress)

    def _interpolated_movement(self, step: int) -> tuple[float, float]:
        dx = float(self.start_x)
        dy = float(self.start_y)
        if self.total_steps > 1:
            progress = step / (self.total_steps - 1.0)
            dx += (self.end_x - self.start_x) * progress
            dy += (self.end_y - self.start_y) * progress
        return dx, dy

    def _check_left_border(self, dx: float) -> tuple[float, bool, bool]:
        """Returns (dx, started_new_animation, leaving_screen)."""
        if self.surface_window is None:
            area = self._screen_area()
            if self.position_x + dx < area.x():
                next_id = pick_next_animation(self.animation.on_border, Surface.VERTICAL, self.rng)
                if next_id >= 0:
                    self.position_x = area.x()
                    self.set_new_animation(next_id)
                    return 0.0, True, False
                return dx, False, True
        else:
            window = self.window_tracker.find(self.surface_window.window_id)
            if window is not None and self.position_x + dx < window.left:
                next_id = pick_next_animation(self.animation.on_border, Surface.WINDOW, self.rng)
                if next_id >= 0:
                    self.position_x = window.left
                    self.set_new_animation(next_id)
                    return 0.0, True, False
                self.surface_window = None   # walked off the edge of the window
        return dx, False, False

    def _check_right_border(self, dx: float) -> tuple[float, bool, bool]:
        """Returns (dx, started_new_animation, leaving_screen)."""
        if self.surface_window is None:
            area = self._screen_area()
            if self.position_x + dx + self.width_px > self._right(area):
                next_id = pick_next_animation(self.animation.on_border, Surface.VERTICAL, self.rng)
                if next_id >= 0:
                    self.position_x = self._right(area) - self.width_px
                    self.set_new_animation(next_id)
                    return 0.0, True, False
                return dx, False, True
        else:
            window = self.window_tracker.find(self.surface_window.window_id)
            if window is not None and self.position_x + dx + self.width_px > window.right:
                next_id = pick_next_animation(self.animation.on_border, Surface.WINDOW, self.rng)
                if next_id >= 0:
                    self.position_x = window.right - self.width_px
                    self.set_new_animation(next_id)
                    return 0.0, True, False
                self.surface_window = None
        return dx, False, False

    def _check_landing(self, dy: float) -> tuple[float, bool]:
        """Moving down: did the pet reach the taskbar or the top of a window?"""
        ground = self._bottom(self._screen_area()) - self.height_px
        if self.position_y + dy > ground:
            next_id = pick_next_animation(self.animation.on_border, Surface.TASKBAR, self.rng)
            if next_id >= 0:
                self.position_y = ground
                self.offset_y = 0
                self.set_new_animation(next_id)
                return 0.0, True
            return dy, False

        window_top = self._detect_window_below(dy)
        if window_top is not None:
            next_id = pick_next_animation(self.animation.on_border, Surface.WINDOW, self.rng)
            if next_id >= 0:
                self.position_y = window_top - self.height_px
                self.offset_y = 0
                self.set_new_animation(next_id)
                # An animation that keeps moving vertically isn't "standing" on it.
                if self.start_y != 0:
                    self.surface_window = None
                return 0.0, True
        return dy, False

    def _check_top_border(self, dy: float) -> tuple[float, bool, bool]:
        area = self._screen_area()
        if self.position_y + dy < area.y():
            next_id = pick_next_animation(self.animation.on_border, Surface.HORIZONTAL, self.rng)
            if next_id >= 0:
                self.position_y = area.y()
                self.set_new_animation(next_id)
                return 0.0, True, False
            return dy, False, True
        return dy, False, False

    def _finish_sequence(self, dy: float) -> bool:
        """The sequence is over: pick what comes next. Returns True if a new animation started."""
        if self.animation.sequence.action == "flip":
            self.moving_left = not self.moving_left

        # The farewell animation fades out, then the window closes.
        if self.animation.animation_id == self.definition.kill_animation_id:
            self.opacity = self.kill_fade_opacity
            self.kill_fade_opacity -= 0.1
            if self.kill_fade_opacity <= 0.0:
                self.close()
            self.update()
            return False

        next_id = self._choose_animation_after_sequence(dy)
        self.set_new_animation(next_id)
        return not self.respawned_during_step and self.isVisible()

    def _choose_animation_after_sequence(self, dy: float) -> int:
        if self.surface_window is not None:
            return pick_next_animation(self.animation.on_sequence_end, Surface.WINDOW, self.rng)

        # A pet that wandered off screen re-spawns.
        bounds = self._screen_bounds()
        if (self.position_x < bounds.x() - self.width_px
                or self.position_x > self._right(bounds)
                or self.position_y < bounds.y() - self.height_px
                or self.position_y > self._bottom(bounds)):
            return -1

        on_taskbar = (self.position_y + self.height_px + dy
                      >= self._bottom(self._screen_area()) - 2)
        surface = Surface.TASKBAR if on_taskbar else Surface.NONE
        return pick_next_animation(self.animation.on_sequence_end, surface, self.rng)

    def _apply_gravity(self, dy: float) -> tuple[float, bool]:
        """Make the pet fall if nothing is below it. Returns (dy, started_falling)."""
        if self.surface_window is None:
            ground = self._bottom(self._screen_area()) - self.height_px
            if self.position_y + dy < ground:
                if self.position_y + dy + GRAVITY_SNAP_PIXELS >= ground:
                    dy = ground - self.position_y        # close enough: snap down
                else:
                    self._start_falling(Surface.NONE)
                    return dy, True
            return dy, False

        if self.animation_step <= 0:
            return dy, False

        # Standing on a window: follow it if it moved, fall if it vanished or got covered.
        window = self.window_tracker.find(self.surface_window.window_id)
        if window is None:
            self._start_falling(Surface.WINDOW)
            return dy, True
        if self._window_moved(window):
            self._follow_window(window)
        elif self.window_tracker.is_top_edge_covered(window, self.position_x,
                                                     self.position_x + self.width_px):
            self._start_falling(Surface.WINDOW)
            return dy, True
        return dy, False

    def _start_falling(self, surface: Surface) -> None:
        self.surface_window = None
        self.set_new_animation(pick_next_animation(self.animation.on_gravity, surface, self.rng))

    def _window_moved(self, window: DesktopWindow) -> bool:
        previous = self.surface_window
        return (window.top != previous.top or window.left != previous.left
                or window.right != previous.right)

    def _follow_window(self, window: DesktopWindow) -> None:
        """Keep the pet at the same relative spot on a window that moved or resized."""
        previous = self.surface_window
        previous_width = previous.right - previous.left
        ratio = (window.right - window.left) / previous_width if previous_width > 0 else 1.0
        self.position_x = window.left + (self.position_x - previous.left) * ratio
        self.position_y += window.top - previous.top
        self.surface_window = window

    def _update_follow_timer(self) -> None:
        """Run the follow timer only while the pet is standing on something."""
        should_follow = (self.surface_window is not None
                         and not self.is_dragging and not self.is_tossing)
        if should_follow and not self.follow_timer.isActive():
            self.follow_timer.start()
        elif not should_follow and self.follow_timer.isActive():
            self.follow_timer.stop()

    def _on_follow_timer(self) -> None:
        """Move with the window/pet underneath as soon as it moves."""
        if self.surface_window is None or self.is_dragging or self.is_tossing:
            self.follow_timer.stop()
            return
        # Falling off a vanished surface is left to the gravity check, as upstream.
        window = self.window_tracker.find(self.surface_window.window_id)
        if window is not None and self._window_moved(window):
            self._follow_window(window)
            self._apply_position()

    def _detect_window_below(self, dy: float) -> float | None:
        """If the pet will cross the top edge of a window or another pet, return that edge."""
        if dy <= 0:
            return None
        area = self._screen_area()
        pet_bottom = self.position_y + self.height_px
        half_width = self.width_px / 2

        # Other pets first: they are always drawn in front of every window.
        own_id = -self.surface_serial
        other_pets = [pet for pet in self.window_tracker.pet_surfaces() if pet.window_id != own_id]
        for window in other_pets + self.window_tracker.windows():
            crosses_top_edge = pet_bottom < window.top <= pet_bottom + dy
            above_window = (window.left - half_width <= self.position_x
                            and self.position_x + self.width_px <= window.right + half_width)
            below_screen_top = self.position_y > 20 + area.y()
            if not (crosses_top_edge and above_window and below_screen_top):
                continue
            if self.window_tracker.is_top_edge_covered(window, self.position_x,
                                                       self.position_x + self.width_px):
                continue
            self.surface_window = window
            return window.top
        return None

    # ------------------------------------------------------------------
    # Drawing and window placement
    # ------------------------------------------------------------------

    def _show_frame(self, frame_index: int) -> None:
        self.current_frame = frame_index
        self.setMask(self.sprites.mask(frame_index, flipped=not self.moving_left))
        self.update()

    def _apply_position(self) -> None:
        self.move(int(self.position_x), int(self.position_y + self.offset_y))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setOpacity(max(0.0, min(1.0, self.opacity)))
        painter.drawImage(0, 0, self.sprites.frame(self.current_frame, flipped=not self.moving_left))
        painter.end()

    # ------------------------------------------------------------------
    # Mouse: drag, toss and context menu
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.is_child or self.is_dying:
            return
        self.surface_window = None
        self.is_dragging = True
        self.is_tossing = False
        self.toss_timer.stop()
        self.follow_timer.stop()
        self.raise_()

        global_position = event.globalPosition()
        self.grab_offset = global_position - QPointF(self.pos())
        self.drag_samples = []
        self._add_drag_sample(global_position)

        self.set_new_animation(self.definition.drag_animation_id)
        self.step_timer.start(1)

    def mouseMoveEvent(self, event) -> None:
        if not self.is_dragging:
            return
        global_position = event.globalPosition()
        top_left = global_position - self.grab_offset
        self.position_x = top_left.x()
        self.position_y = top_left.y()
        self.offset_y = 0
        self.move(int(self.position_x), int(self.position_y))
        self._add_drag_sample(global_position)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.is_dragging:
            return
        self.is_dragging = False
        self._add_drag_sample(event.globalPosition())
        self._adopt_screen_under_pet()

        self.toss_force_x, self.toss_force_y = self._toss_force()
        if math.hypot(self.toss_force_x, self.toss_force_y) > TOSS_MINIMUM_FORCE:
            # Flung! Fly with simple physics until landing.
            if self.definition.toss_animation_id != -1:
                self.set_new_animation(self.definition.toss_animation_id)
            self.is_tossing = True
            self.toss_vertical_velocity = self.toss_force_y
            self.toss_updated_at = self._now_ms()
            self.next_interval = TOSS_FRAME_INTERVAL_MS
            self.toss_timer.start()
        else:
            self.set_new_animation(self.definition.fall_animation_id)
        self.step_timer.start(1)

    def contextMenuEvent(self, event) -> None:
        self.manager.show_context_menu(self, event.globalPos())

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    def _add_drag_sample(self, global_position: QPointF) -> None:
        now = self._now_ms()
        if self.drag_samples and now <= self.drag_samples[-1][0]:
            return
        self.drag_samples.append((now, global_position.x(), global_position.y()))
        # Keep only the last ~80 ms of movement to measure the throw.
        while len(self.drag_samples) > 2 and self.drag_samples[1][0] <= now - DRAG_SAMPLE_WINDOW_MS:
            self.drag_samples.pop(0)

    def _toss_force(self) -> tuple[float, float]:
        """Throw velocity, in the original's units (pixels per 10 ms)."""
        if len(self.drag_samples) < 2:
            return 0.0, 0.0
        first_time, first_x, first_y = self.drag_samples[0]
        last_time, last_x, last_y = self.drag_samples[-1]
        elapsed = last_time - first_time
        if elapsed < 8 or self._now_ms() - last_time > DRAG_SAMPLE_WINDOW_MS:
            return 0.0, 0.0
        return (last_x - first_x) / elapsed * 10, (last_y - first_y) / elapsed * 10

    def _adopt_screen_under_pet(self) -> None:
        center = QPoint(int(self.position_x + self.width_px / 2),
                        int(self.position_y + self.height_px / 2))
        screen = QGuiApplication.screenAt(center)
        if screen is not None:
            self.pet_screen = screen

    def _on_toss_timer(self) -> None:
        """Integrate the throw: bounce off the sides, fall with gravity, then land."""
        now = self._now_ms()
        # Force units are "pixels per 30 ms"; cap pauses so a stall can't teleport the pet.
        dt = max(0.0, min(50.0, now - self.toss_updated_at)) / 30.0
        self.toss_updated_at = now
        if dt == 0:
            return

        area = self._screen_area()
        left_limit = area.x()
        right_limit = self._right(area) - self.width_px
        next_x = self.position_x + self.toss_force_x * dt
        if next_x < left_limit or next_x > right_limit:
            edge = left_limit if next_x < left_limit else right_limit
            next_x = edge - (next_x - edge) * 0.3     # bounce back, losing energy
            self.toss_force_x *= -0.3
        self.position_x = max(left_limit, min(right_limit, next_x))

        dy = self.toss_vertical_velocity * dt + 0.75 * dt * dt
        self.toss_vertical_velocity += 1.5 * dt
        ground = self._bottom(area) - self.height_px
        landed = self.position_y + dy >= ground

        window_top = self._detect_window_below(math.ceil(dy)) if dy > 0 else None
        if window_top is not None and window_top - self.height_px <= ground:
            ground = window_top - self.height_px
            landed = True

        self.position_y = ground if landed else self.position_y + dy
        self.offset_y = 0
        self._apply_position()

        if landed:
            self._land_after_toss()

    def _land_after_toss(self) -> None:
        # Face the direction the pet was thrown.
        if (self.toss_force_x < 0 and not self.moving_left) or (self.toss_force_x > 0 and self.moving_left):
            self.moving_left = not self.moving_left
        self.is_tossing = False
        self.toss_timer.stop()
        if self.toss_vertical_velocity < HARD_LANDING_VELOCITY:
            self.set_new_animation(self.definition.fall_soft_animation_id)
        else:
            self.set_new_animation(self.definition.fall_hard_animation_id)
        self._show_frame(self.animation.sequence.frames[0])
        self.step_timer.start(1)

    # ------------------------------------------------------------------
    # Closing
    # ------------------------------------------------------------------

    def kill(self) -> None:
        """Play the farewell animation (if the pet has one), then close."""
        if self.is_dying:
            return
        self.is_dying = True
        self.is_dragging = False
        self.is_tossing = False
        self.toss_timer.stop()
        for child in list(self.children_pets):
            child.close()

        kill_id = self.definition.kill_animation_id
        if kill_id in self.definition.animations and not self.is_child:
            self.set_new_animation(kill_id)
            self.step_timer.start(1)
        else:
            self.close()

    def closeEvent(self, event) -> None:
        self.step_timer.stop()
        self.toss_timer.stop()
        self.follow_timer.stop()
        for child in list(self.children_pets):
            child.close()
        super().closeEvent(event)
        self.closed.emit(self)
