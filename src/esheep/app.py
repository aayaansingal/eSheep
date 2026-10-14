"""Application entry point: tray icon, menus and the collection of running pets."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__, platform_support
from .desktop import WindowTracker
from .pet_definition import Child, PetDefinition, bundled_pet_path, load_pet_definition
from .pet_window import PetWindow
from .sprites import SpriteSheet

QUIT_GRACE_PERIOD_MS = 3000     # longest we wait for farewell animations


class PetManager:
    """Owns the loaded pet definition and every pet window on screen."""

    def __init__(self, app: QApplication, definition: PetDefinition, pet_path: Path):
        self.app = app
        self.window_tracker = WindowTracker(pet_surface_provider=self._pet_surfaces)
        self.pets: list[PetWindow] = []
        self.is_quitting = False

        self.definition = definition
        self.pet_path = pet_path
        self.sprites = SpriteSheet(definition)

        self.menu = QMenu()
        self.tray_icon = QSystemTrayIcon()
        self._build_menu()
        self._setup_tray_icon()

    # ------------------------------------------------------------------
    # Pets
    # ------------------------------------------------------------------

    def add_pet(self) -> PetWindow:
        pet = PetWindow(self, self.definition, self.sprites, self.window_tracker)
        self._register(pet)
        pet.spawn()
        return pet

    def create_child(self, parent: PetWindow, child: Child) -> None:
        """Called by a pet whose current animation spawns a child (e.g. a UFO)."""
        child_pet = PetWindow(self, self.definition, self.sprites, self.window_tracker,
                              screen=parent.pet_screen,
                              child_depth=parent.child_depth + 1,
                              moving_left=parent.moving_left,
                              random_spawn=parent.random_spawn)
        parent.children_pets.append(child_pet)
        self._register(child_pet)
        child_pet.start_as_child(child, parent)

    def _register(self, pet: PetWindow) -> None:
        self.pets.append(pet)
        pet.closed.connect(self._on_pet_closed)

    def _on_pet_closed(self, pet: PetWindow) -> None:
        if pet in self.pets:
            self.pets.remove(pet)
        for other in self.pets:
            if pet in other.children_pets:
                other.children_pets.remove(pet)
        pet.deleteLater()
        if self.is_quitting and not self._main_pets():
            self.exit_application()

    def _main_pets(self) -> list[PetWindow]:
        return [pet for pet in self.pets if not pet.is_child]

    def _pet_surfaces(self):
        """Pets other pets can land on. Children (e.g. a UFO) are not solid."""
        return [pet.as_surface() for pet in self._main_pets() if pet.isVisible()]

    def remove_pet(self, pet: PetWindow) -> None:
        pet.kill()

    def quit_with_farewell(self) -> None:
        """Let every pet play its farewell animation, then exit."""
        if self.is_quitting:
            return
        self.is_quitting = True
        self.tray_icon.hide()
        if not self._main_pets():
            self.exit_application()
            return
        for pet in list(self._main_pets()):
            pet.kill()
        QTimer.singleShot(QUIT_GRACE_PERIOD_MS, self.exit_application)

    def exit_application(self) -> None:
        """Stop the event loop so ``main`` can shut down cleanly.

        Deliberately not ``QApplication.quit()``: on macOS, Qt 6 routes that
        through ``NSApplication terminate:``, which calls ``exit()`` straight
        away when invoked from a menu's nested event loop. Qt then destroys
        windows during process teardown and crashes. ``exit(0)`` just ends
        every running event loop and lets ``app.exec()`` return normally.
        """
        self.app.exit(0)

    def shutdown(self) -> None:
        """Close and delete every pet while Qt is still fully alive."""
        self.tray_icon.hide()
        for pet in list(self.pets):
            pet.close()
        # Run the pending deleteLater() calls now, not during process exit.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def load_pet(self, path: Path) -> None:
        """Replace the current pet type with another XML file, keeping the pet count."""
        try:
            definition = load_pet_definition(path)
            sprites = SpriteSheet(definition)
        except Exception as error:
            QMessageBox.warning(None, "eSheep", f"Could not load pet file:\n{path}\n\n{error}")
            return

        pet_count = max(1, len(self._main_pets()))
        for pet in list(self.pets):
            pet.close()
        self.definition = definition
        self.sprites = sprites
        self.pet_path = path
        self._build_menu()
        self._setup_tray_icon()
        for _ in range(pet_count):
            self.add_pet()

    # ------------------------------------------------------------------
    # Menus and tray icon
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        pet_name = self.definition.pet_name
        self.menu.clear()

        add_action = QAction(f"Add new {pet_name}", self.menu)
        add_action.triggered.connect(self.add_pet)
        self.menu.addAction(add_action)

        load_action = QAction("Open pet file…", self.menu)
        load_action.triggered.connect(self._choose_pet_file)
        self.menu.addAction(load_action)

        self.menu.addSeparator()
        about_action = QAction("About", self.menu)
        about_action.triggered.connect(self._show_about)
        self.menu.addAction(about_action)

        self.menu.addSeparator()
        quit_action = QAction(f"Remove {pet_name} and close", self.menu)
        quit_action.triggered.connect(self.quit_with_farewell)
        self.menu.addAction(quit_action)

    def show_context_menu(self, pet: PetWindow, position: QPoint) -> None:
        """Right-click on a pet: the tray menu plus "remove this one".

        This doubles as the main menu on desktops without a system tray.
        """
        menu = QMenu()
        if not pet.is_child:
            remove_action = QAction(f"Remove this {self.definition.pet_name}", menu)
            remove_action.triggered.connect(lambda: self.remove_pet(pet))
            menu.addAction(remove_action)
            menu.addSeparator()
        for action in self.menu.actions():
            menu.addAction(action)
        menu.exec(position)

    def _setup_tray_icon(self) -> None:
        self.tray_icon.setIcon(self._pet_icon())
        self.tray_icon.setToolTip(self.definition.title)
        self.tray_icon.setContextMenu(self.menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _pet_icon(self) -> QIcon:
        pixmap = QPixmap()
        if self.definition.icon_data and pixmap.loadFromData(self.definition.icon_data):
            return QIcon(pixmap)
        # No (readable) icon in the XML: use the pet's first walking frame.
        return QIcon(QPixmap.fromImage(self.sprites.frame(0, flipped=False)))

    def _choose_pet_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None, "Open eSheep pet", str(self.pet_path.parent), "Pet animations (*.xml)")
        if path:
            self.load_pet(Path(path))

    def _show_about(self) -> None:
        definition = self.definition
        info = definition.info.replace("[br]", "<br>")
        QMessageBox.about(
            None, "About eSheep",
            f"<b>eSheep (cross-platform)</b> {__version__}<br><br>"
            f"Current pet: <b>{definition.title}</b> {definition.version} "
            f"by {definition.author}<br>{info}<br><br>"
            "Based on the original eSheep desktop pet by Adriano Petrucci "
            "(<a href='https://github.com/Adrianotiger/desktopPet'>desktopPet</a>, MIT licence).<br>"
            "Drag a pet to move it, throw it, or right-click it for options.",
        )


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="esheep", description="A desktop pet for every OS.")
    parser.add_argument("--pet", type=Path, default=None,
                        help="path to an eSheep animations.xml file (default: the classic sheep)")
    parser.add_argument("--count", type=int, default=1,
                        help="how many pets to start with (default: 1)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def ensure_standard_streams() -> None:
    """Windowed builds (e.g. the Windows .exe) start with no console streams.

    ``print`` and argparse would crash on ``None``, so send output nowhere instead.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def main(argv: list[str] | None = None) -> int:
    ensure_standard_streams()
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    platform_support.prepare_environment()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("eSheep")
    platform_support.configure_application(app)

    pet_path = arguments.pet or bundled_pet_path()
    try:
        definition = load_pet_definition(pet_path)
    except Exception as error:
        # Packaged apps have no visible terminal, so also show a dialog.
        message = f"Could not load pet file:\n{pet_path}\n\n{error}"
        print(f"esheep: {message}", file=sys.stderr)
        QMessageBox.critical(None, "eSheep", message)
        return 1

    manager = PetManager(app, definition, pet_path)
    for _ in range(max(1, arguments.count)):
        manager.add_pet()

    # Let Ctrl+C in a terminal close the app gracefully.
    signal.signal(signal.SIGINT, lambda *_: manager.quit_with_farewell())
    interrupt_poller = QTimer()
    interrupt_poller.start(250)       # wakes Python so it can notice the signal
    interrupt_poller.timeout.connect(lambda: None)

    exit_code = app.exec()
    manager.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
