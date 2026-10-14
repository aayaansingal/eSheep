"""Linux/BSD window list via X11 EWMH properties (python-xlib).

Works on X11 sessions and, for X11 apps, under XWayland. Native Wayland
windows cannot be inspected by other applications, so they are invisible here.
"""

from __future__ import annotations

import os

from Xlib import X, display

from . import DesktopWindow, WindowBackend

MINIMUM_WINDOW_SIZE = 50
ALL_DESKTOPS = 0xFFFFFFFF


class X11WindowBackend(WindowBackend):
    def __init__(self):
        self._display = display.Display()
        self._root = self._display.screen().root
        self._own_pid = os.getpid()
        atom = self._display.intern_atom
        self._atoms = {
            name: atom(name) for name in (
                "_NET_CLIENT_LIST_STACKING", "_NET_CURRENT_DESKTOP", "_NET_WM_DESKTOP",
                "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN", "_NET_WM_WINDOW_TYPE",
                "_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG",
                "_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS", "_NET_WM_PID",
            )
        }
        # Don't let a window closing mid-query raise asynchronous errors.
        self._display.set_error_handler(lambda *args: None)

    def _property(self, window, name: str) -> list[int] | None:
        prop = window.get_full_property(self._atoms[name], X.AnyPropertyType)
        return list(prop.value) if prop is not None else None

    def list_windows(self) -> list[DesktopWindow]:
        stacking = self._property(self._root, "_NET_CLIENT_LIST_STACKING") or []
        current_desktop = (self._property(self._root, "_NET_CURRENT_DESKTOP") or [0])[0]

        windows = []
        # The stacking list is bottom-to-top; we want front-most first.
        for window_id in reversed(stacking):
            try:
                rectangle = self._usable_window(window_id, current_desktop)
            except Exception:
                continue   # the window vanished while we were looking at it
            if rectangle is not None:
                windows.append(rectangle)
        return windows

    def _usable_window(self, window_id: int, current_desktop: int) -> DesktopWindow | None:
        window = self._display.create_resource_object("window", window_id)

        if (self._property(window, "_NET_WM_PID") or [0])[0] == self._own_pid:
            return None
        desktop = (self._property(window, "_NET_WM_DESKTOP") or [current_desktop])[0]
        if desktop not in (current_desktop, ALL_DESKTOPS):
            return None
        if self._atoms["_NET_WM_STATE_HIDDEN"] in (self._property(window, "_NET_WM_STATE") or []):
            return None
        window_types = self._property(window, "_NET_WM_WINDOW_TYPE")
        allowed_types = {self._atoms["_NET_WM_WINDOW_TYPE_NORMAL"],
                         self._atoms["_NET_WM_WINDOW_TYPE_DIALOG"]}
        if window_types and not allowed_types.intersection(window_types):
            return None   # docks, desktop icons, menus, tooltips...

        geometry = window.get_geometry()
        origin = window.translate_coords(self._root, 0, 0)
        left, top = -origin.x, -origin.y
        right, bottom = left + geometry.width, top + geometry.height

        # Window-manager decorations sit outside the client area...
        frame = self._property(window, "_NET_FRAME_EXTENTS")
        if frame and len(frame) == 4:
            left, right = left - frame[0], right + frame[1]
            top, bottom = top - frame[2], bottom + frame[3]
        # ...while client-side-decorated GTK windows include invisible shadows.
        shadow = self._property(window, "_GTK_FRAME_EXTENTS")
        if shadow and len(shadow) == 4:
            left, right = left + shadow[0], right - shadow[1]
            top, bottom = top + shadow[2], bottom - shadow[3]

        if right - left < MINIMUM_WINDOW_SIZE or bottom - top < MINIMUM_WINDOW_SIZE:
            return None
        return DesktopWindow(window_id, left, top, right, bottom)
