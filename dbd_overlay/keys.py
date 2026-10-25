"""Read-only keyboard detection for Space and the start/stop hotkey.

Nothing here touches the game process: on Windows the key state is polled with
GetAsyncKeyState (no hook, no injection), on Linux we read the keyboard through
evdev or the X server, the same way push-to-talk apps do.
"""

import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal

# Windows virtual-key codes / evdev names / pynput names per key we listen to
KEYS = {
    "space": (0x20, "KEY_SPACE", "space"),
    "hotkey": (0x77, "KEY_F8", "f8"),
}


class KeyListener(QObject):
    pressed = Signal(str)  # "space" or "hotkey"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = "none"
        self._active = False
        self._down: dict[str, bool] = {k: False for k in KEYS}
        self._poll: QTimer | None = None

        if sys.platform == "win32":
            self._init_windows()
        elif not self._init_evdev():
            self._init_pynput()

    def set_active(self, active: bool):
        self._active = active
        self._down = {k: False for k in KEYS}

    def _emit(self, name: str):
        if self._active:
            self.pressed.emit(name)

    # -- Windows ------------------------------------------------------------

    def _init_windows(self):
        import ctypes

        self._get_state = ctypes.windll.user32.GetAsyncKeyState
        self._poll = QTimer(self)
        self._poll.setInterval(15)
        self._poll.timeout.connect(self._poll_windows)
        self._poll.start()
        self.backend = "GetAsyncKeyState"

    def _poll_windows(self):
        if not self._active:
            return
        for name, (vk, _, _) in KEYS.items():
            down = bool(self._get_state(vk) & 0x8000)
            if down and not self._down[name]:
                self.pressed.emit(name)
            self._down[name] = down

    # -- Linux --------------------------------------------------------------

    def _init_evdev(self) -> bool:
        # Works on X11 and Wayland, but needs read access to /dev/input (the "input" group)
        try:
            import evdev
        except ImportError:
            return False
        codes = {getattr(evdev.ecodes, ev): name for name, (_, ev, _) in KEYS.items()}
        keyboards = []
        for dev_path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(dev_path)
                if evdev.ecodes.KEY_SPACE in dev.capabilities().get(evdev.ecodes.EV_KEY, []):
                    keyboards.append(dev)
            except OSError:
                continue
        if not keyboards:
            return False

        def reader(dev):
            try:
                for event in dev.read_loop():
                    if event.type == evdev.ecodes.EV_KEY and event.value == 1 and event.code in codes:
                        self._emit(codes[event.code])
            except OSError:
                pass

        for dev in keyboards:
            threading.Thread(target=reader, args=(dev,), daemon=True).start()
        self.backend = "evdev"
        return True

    def _init_pynput(self) -> bool:
        # X11 / XWayland: sees keys typed into X11 windows, which includes Proton games
        try:
            from pynput import keyboard
        except Exception:
            return False
        names = {getattr(keyboard.Key, pk): name for name, (_, _, pk) in KEYS.items()}

        def on_press(key):
            name = names.get(key)
            if name and not self._down[name]:
                self._down[name] = True
                self._emit(name)

        def on_release(key):
            name = names.get(key)
            if name:
                self._down[name] = False

        try:
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.daemon = True
            listener.start()
        except Exception:
            return False
        self.backend = "pynput"
        return True
