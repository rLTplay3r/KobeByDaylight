"""Read-only keyboard / mouse detection: Space, the start/stop hotkey and the flashlight button.

Nothing here touches the game process: on Windows the key state is polled with
GetAsyncKeyState (no hook, no injection), on Linux we read the input through
evdev or the X server, the same way push-to-talk apps do.
"""

import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal

# Windows virtual-key codes / evdev names / pynput names per input we listen to.
# The flashlight is the right mouse button (DBD's default "Active Ability" binding).
KEYS = {
    "space": (0x20, "KEY_SPACE", "space"),
    "hotkey": (0x77, "KEY_F8", "f8"),
}
BUTTONS = {
    "flashlight": (0x02, "BTN_RIGHT", "right"),
}
ALL_INPUTS = {**KEYS, **BUTTONS}


class KeyListener(QObject):
    pressed = Signal(str)   # "space", "hotkey" or "flashlight"
    released = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = "none"
        self._active = False
        self._down: dict[str, bool] = {k: False for k in ALL_INPUTS}
        self._poll: QTimer | None = None

        if sys.platform == "win32":
            self._init_windows()
        elif not self._init_evdev():
            self._init_pynput()

    def set_active(self, active: bool):
        self._active = active
        self._down = {k: False for k in ALL_INPUTS}

    def is_down(self, name: str) -> bool:
        return self._down.get(name, False)

    def _set(self, name: str, down: bool):
        # Called from the input threads too; Qt queues the signals to the UI thread
        if down == self._down[name]:
            return
        self._down[name] = down
        if self._active:
            (self.pressed if down else self.released).emit(name)

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
        for name, (vk, _, _) in ALL_INPUTS.items():
            self._set(name, bool(self._get_state(vk) & 0x8000))

    # -- Linux --------------------------------------------------------------

    def _init_evdev(self) -> bool:
        # Works on X11 and Wayland, but needs read access to /dev/input (the "input" group)
        try:
            import evdev
        except ImportError:
            return False
        codes = {getattr(evdev.ecodes, ev): name for name, (_, ev, _) in ALL_INPUTS.items()}
        devices = []
        for dev_path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(dev_path)
                keys = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
                if evdev.ecodes.KEY_SPACE in keys or evdev.ecodes.BTN_RIGHT in keys:
                    devices.append(dev)
            except OSError:
                continue
        if not devices:
            return False

        def reader(dev):
            try:
                for event in dev.read_loop():
                    if event.type == evdev.ecodes.EV_KEY and event.code in codes and event.value in (0, 1):
                        self._set(codes[event.code], event.value == 1)
            except OSError:
                pass

        for dev in devices:
            threading.Thread(target=reader, args=(dev,), daemon=True).start()
        self.backend = "evdev"
        return True

    def _init_pynput(self) -> bool:
        # X11 / XWayland: sees input sent to X11 windows, which includes Proton games
        try:
            from pynput import keyboard, mouse
        except Exception:
            return False
        keys = {getattr(keyboard.Key, pk): name for name, (_, _, pk) in KEYS.items()}
        buttons = {getattr(mouse.Button, pb): name for name, (_, _, pb) in BUTTONS.items()}

        def on_press(key):
            if key in keys:
                self._set(keys[key], True)

        def on_release(key):
            if key in keys:
                self._set(keys[key], False)

        def on_click(_x, _y, button, down):
            if button in buttons:
                self._set(buttons[button], down)

        try:
            for listener in (keyboard.Listener(on_press=on_press, on_release=on_release),
                             mouse.Listener(on_click=on_click)):
                listener.daemon = True
                listener.start()
        except Exception:
            return False
        self.backend = "pynput"
        return True
