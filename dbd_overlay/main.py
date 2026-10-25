"""Entry point: tray app, plus a scripted --simulate demo for testing without the game."""

import argparse
import ctypes.util
import os
import sys


from . import __version__


def _prepare_platform():
    # Wayland does not let clients keep a window on top or make it click-through,
    # so on Linux we run through XWayland - where Proton runs the game anyway.
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
        # Qt's xcb plugin aborts without libxcb-cursor; stay on Wayland rather than crash
        if ctypes.util.find_library("xcb-cursor"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"
        else:
            print("libxcb-cursor not found (install xcb-util-cursor / libxcb-cursor0); "
                  "running on Wayland, overlay may not stay on top", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Kobe overlay for Dead by Daylight")
    parser.add_argument("--simulate", action="store_true",
                        help="run a scripted fake match (spawn, Space presses, Kobe, end) without the game")
    parser.add_argument("--panel", action="store_true", help="open the control panel on startup")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    _prepare_platform()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from . import APP_NAME, theme
    from .config import Config
    from .controller import Controller
    from .ui import ControlPanel, Tray

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())

    config = Config()
    ctl = Controller(config)
    panel = ControlPanel(ctl)

    def quit_app():
        ctl.stop()
        app.quit()

    tray = Tray(ctl, panel, quit_app)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
        tray.showMessage(APP_NAME, "Running in the tray. Click the icon for the menu.",
                         QSystemTrayIcon.MessageIcon.Information, 3000)
    else:
        # Without a tray the panel is the only way to reach the app
        args.panel = True

    if args.simulate:
        args.panel = True
        script = [
            (1500, ctl.begin_match),
            (3000, ctl.on_space),
            (5000, ctl.on_space),
            (8000, ctl.play_random_sound),
            (12000, ctl.show_kobe),
            (16000, ctl.on_space),
            (20000, ctl.play_random_sound),
            (25000, ctl.show_kobe),
            (35000, ctl.end_match),
        ]
        for delay, action in script:
            QTimer.singleShot(delay, action)

    if config["autostart"] or args.simulate:
        ctl.start()
    if args.panel:
        tray.show_panel()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
