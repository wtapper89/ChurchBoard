from __future__ import annotations

import threading
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from app.config import ROOT_DIR
from app.store import ConfigStore
from app.version import __version__


class DesktopTray:
    def __init__(self, port: int, data_file: Path, on_quit: Callable[[], None], scheme: str = "http"):
        self.base_url = f"{scheme}://127.0.0.1:{port}"
        self.store = ConfigStore(data_file)
        self.on_quit = on_quit
        self.icon = None
        self._application_delegate = None

    def open_path(self, path: str) -> None:
        threading.Thread(
            target=webbrowser.open,
            args=(f"{self.base_url}/{path.lstrip('/')}",),
            daemon=True,
        ).start()

    def quit(self, _icon=None, _item=None) -> None:
        self.on_quit()
        if self.icon is not None:
            self.icon.stop()

    def _open_board_action(self, slug: str):
        def action(_icon, _item) -> None:
            self.open_path(f"display/{slug}")

        return action

    def _boards_menu(self):
        import pystray

        dashboards = self.store.load().get("dashboards", [])
        if not dashboards:
            return (pystray.MenuItem("No boards configured", None, enabled=False),)
        return tuple(
            pystray.MenuItem(
                str(board.get("name") or board.get("slug") or "Board"),
                self._open_board_action(str(board.get("slug") or board.get("id"))),
            )
            for board in dashboards
        )

    def run(self) -> None:
        import pystray

        if sys.platform == "darwin":
            self._configure_macos_dock()
        artwork = Image.open(ROOT_DIR / "app" / "static" / "churchboard-icon.png").convert("RGBA")
        menu = pystray.Menu(
            pystray.MenuItem("Open ChurchBoard", lambda *_: self.open_path("desktop"), default=True),
            pystray.MenuItem("Setup", lambda *_: self.open_path("admin")),
            pystray.MenuItem("Boards", pystray.Menu(self._boards_menu)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check for Updates", lambda *_: self.open_path("desktop#updates")),
            pystray.MenuItem(f"ChurchBoard {__version__}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit ChurchBoard", self.quit),
        )
        self.icon = pystray.Icon("ChurchBoard", artwork, "ChurchBoard", menu)
        self.icon.run()

    def _configure_macos_dock(self) -> None:
        import AppKit
        from Foundation import NSObject

        tray = self

        class ChurchBoardApplicationDelegate(NSObject):
            def applicationShouldHandleReopen_hasVisibleWindows_(self, _application, _has_visible_windows):
                tray.open_path("desktop")
                return True

        application = AppKit.NSApplication.sharedApplication()
        application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        self._application_delegate = ChurchBoardApplicationDelegate.alloc().init()
        application.setDelegate_(self._application_delegate)
