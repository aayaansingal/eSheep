"""Discover other applications' windows so pets can walk on top of them.

Each operating system needs its own API, so the work is split into backends:

* macOS   -> Quartz ``CGWindowListCopyWindowInfo``
* Windows -> Win32 ``EnumWindows`` via ctypes
* Linux   -> X11 ``_NET_CLIENT_LIST_STACKING`` via python-xlib

When no backend works (e.g. a pure Wayland session) the tracker simply reports
no windows, and pets walk along the bottom of the screen only.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DesktopWindow:
    """A top-level window rectangle in Qt logical (device-independent) pixels."""

    window_id: int
    left: float
    top: float
    right: float
    bottom: float


class WindowBackend:
    """Interface implemented by every platform backend."""

    def list_windows(self) -> list[DesktopWindow]:
        """Return visible windows ordered front-most first."""
        return []


def is_pet_surface(window_id: int) -> bool:
    """Pets use negative ids so they can never clash with real window ids."""
    return window_id < 0


class WindowTracker:
    """Everything a pet can stand on: other apps' windows and other pets.

    The OS window list is cached briefly, since many pets query it every tick.
    Pet surfaces come straight from the app (they move every tick anyway).
    """

    CACHE_SECONDS = 0.1

    def __init__(self, backend: WindowBackend | None = None,
                 pet_surface_provider: Callable[[], list[DesktopWindow]] | None = None):
        self._backend = backend if backend is not None else create_backend()
        self._cached_windows: list[DesktopWindow] = []
        self._cached_at = 0.0
        self.pet_surface_provider = pet_surface_provider

    def pet_surfaces(self) -> list[DesktopWindow]:
        """Other pets, which (as in the original eSheep) can be stood on too."""
        if self.pet_surface_provider is None:
            return []
        return self.pet_surface_provider()

    def windows(self) -> list[DesktopWindow]:
        now = time.monotonic()
        if now - self._cached_at > self.CACHE_SECONDS:
            try:
                self._cached_windows = self._backend.list_windows()
            except Exception:
                # A flaky platform API must never crash the pets.
                self._cached_windows = []
            self._cached_at = now
        return self._cached_windows

    def find(self, window_id: int) -> DesktopWindow | None:
        """Current rectangle of a window or pet, or None if it's gone."""
        candidates = self.pet_surfaces() if is_pet_surface(window_id) else self.windows()
        for window in candidates:
            if window.window_id == window_id:
                return window
        return None

    def is_top_edge_covered(self, target: DesktopWindow, x_left: float, x_right: float) -> bool:
        """True if a window in front of ``target`` hides its top edge at [x_left, x_right]."""
        if is_pet_surface(target.window_id):
            return False   # pets are always on top of every window
        for window in self.windows():
            if window.window_id == target.window_id:
                return False   # reached the target: nothing in front covers it
            spans_edge = window.top < target.top < window.bottom
            spans_pet = window.left < x_left and window.right > x_right
            if spans_edge and spans_pet:
                return True
        return False


def create_backend() -> WindowBackend:
    """Pick the window backend for the current platform."""
    try:
        if sys.platform == "darwin":
            from .macos import MacWindowBackend
            return MacWindowBackend()
        if sys.platform == "win32":
            from .windows import Win32WindowBackend
            return Win32WindowBackend()
        if sys.platform.startswith("linux") or "bsd" in sys.platform:
            from .x11 import X11WindowBackend
            return X11WindowBackend()
    except Exception as error:   # missing optional dependency, no X server...
        print(f"esheep: window detection unavailable ({error}); "
              "pets will only walk on the screen bottom.", file=sys.stderr)
    return WindowBackend()
