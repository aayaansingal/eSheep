"""Small per-operating-system tweaks that make pet windows behave like the original."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget


def prepare_environment() -> None:
    """Must run before QApplication is created.

    Wayland does not let applications position their own windows, which a
    desktop pet fundamentally needs. Qt can run through XWayland instead, so
    prefer that unless the user explicitly chose a platform.
    """
    # Pets spawn and leave off-screen on purpose; don't log a warning each time.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        if not os.environ.get("QT_QPA_PLATFORM") and os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"


def configure_application(app: QApplication) -> None:
    # Pets come and go; only the tray menu or the last "Quit" ends the app.
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == "darwin":
        _hide_macos_dock_icon()


def pet_window_flags() -> Qt.WindowType:
    flags = (Qt.WindowType.FramelessWindowHint
             | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.Tool                      # no taskbar button / Alt-Tab entry
             | Qt.WindowType.WindowDoesNotAcceptFocus
             | Qt.WindowType.NoDropShadowWindowHint)
    if QGuiApplication.platformName() == "xcb":
        # Unmanaged X11 windows can be placed anywhere and never get decorations.
        flags |= Qt.WindowType.X11BypassWindowManagerHint
    return flags


def configure_pet_widget(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)   # stay visible when app is inactive
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    widget.setCursor(Qt.CursorShape.OpenHandCursor)


def after_pet_window_shown(widget: QWidget) -> None:
    """Native tweaks that need the platform window to exist."""
    if sys.platform == "darwin":
        _join_all_macos_spaces(widget)


def _hide_macos_dock_icon() -> None:
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass   # pyobjc missing: the app just shows a Dock icon


def _join_all_macos_spaces(widget: QWidget) -> None:
    """Show the pet on every Space (virtual desktop), including over full-screen apps."""
    try:
        import objc
        import AppKit
        view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window()
        if window is None:
            return
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        window.setHidesOnDeactivate_(False)
    except Exception:
        pass
