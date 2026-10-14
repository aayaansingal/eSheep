"""macOS window list via Quartz (needs no special permissions for bounds)."""

from __future__ import annotations

import os

import Quartz

from . import DesktopWindow, WindowBackend

MINIMUM_WINDOW_SIZE = 50


class MacWindowBackend(WindowBackend):
    def __init__(self):
        self._own_pid = os.getpid()

    def list_windows(self) -> list[DesktopWindow]:
        options = (Quartz.kCGWindowListOptionOnScreenOnly
                   | Quartz.kCGWindowListExcludeDesktopElements)
        window_infos = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []

        # Quartz already returns windows front-to-back, in the same top-left
        # origin point coordinates that Qt uses for global positions.
        windows = []
        for info in window_infos:
            if info.get(Quartz.kCGWindowOwnerPID) == self._own_pid:
                continue
            if info.get(Quartz.kCGWindowLayer, 0) != 0:   # menu bar, Dock, overlays
                continue
            if info.get(Quartz.kCGWindowAlpha, 1.0) <= 0:
                continue

            bounds = info.get(Quartz.kCGWindowBounds) or {}
            left = float(bounds.get("X", 0))
            top = float(bounds.get("Y", 0))
            width = float(bounds.get("Width", 0))
            height = float(bounds.get("Height", 0))
            if width < MINIMUM_WINDOW_SIZE or height < MINIMUM_WINDOW_SIZE:
                continue

            windows.append(DesktopWindow(
                window_id=int(info.get(Quartz.kCGWindowNumber, 0)),
                left=left, top=top, right=left + width, bottom=top + height,
            ))
        return windows
