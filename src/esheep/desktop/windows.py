"""Windows window list via Win32 ``EnumWindows`` (ctypes, no extra packages)."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtGui import QGuiApplication

from . import DesktopWindow, WindowBackend

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
IGNORED_WINDOW_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
MINIMUM_WINDOW_SIZE = 50

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]


class Win32WindowBackend(WindowBackend):
    def __init__(self):
        self._own_pid = os.getpid()

    def list_windows(self) -> list[DesktopWindow]:
        handles: list[int] = []

        # EnumWindows walks top-level windows in Z-order, front-most first.
        @EnumWindowsProc
        def collect(hwnd, _parameter):
            handles.append(hwnd)
            return True

        user32.EnumWindows(collect, 0)

        # Win32 reports physical pixels; Qt positions windows in logical ones.
        # (Approximation: assumes every monitor shares the primary's scale.)
        screen = QGuiApplication.primaryScreen()
        pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0

        windows = []
        for hwnd in handles:
            rect = self._usable_window_rect(hwnd)
            if rect is None:
                continue
            windows.append(DesktopWindow(
                window_id=int(hwnd),
                left=rect.left / pixel_ratio,
                top=rect.top / pixel_ratio,
                right=rect.right / pixel_ratio,
                bottom=rect.bottom / pixel_ratio,
            ))
        return windows

    def _usable_window_rect(self, hwnd) -> wintypes.RECT | None:
        """The window's visible frame, or None if pets should ignore it."""
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return None
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return None

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == self._own_pid:
            return None

        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, 64)
        if class_name.value in IGNORED_WINDOW_CLASSES:
            return None

        # Suspended UWP apps are "visible" but cloaked (not actually shown).
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                     ctypes.sizeof(cloaked))
        if cloaked.value:
            return None

        # The extended frame excludes the invisible resize borders of Win10+.
        rect = wintypes.RECT()
        result = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                              ctypes.byref(rect), ctypes.sizeof(rect))
        if result != 0 and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        if (rect.right - rect.left < MINIMUM_WINDOW_SIZE
                or rect.bottom - rect.top < MINIMUM_WINDOW_SIZE):
            return None
        return rect
