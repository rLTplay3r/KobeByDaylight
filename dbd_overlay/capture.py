"""Screenshots of the game window, the way OBS or Fog Companion take them.

Windows: finds the game's window by process id and copies that screen area (GDI).
Linux: the game runs through XWayland under Proton, so we read the image of its
X11 window. Nothing touches the game process itself.

Every grabber is used from a single worker thread only.
"""

import sys

import numpy as np


class CaptureError(Exception):
    pass


class _WindowsGrabber:
    center: tuple[int, int] | None = None  # game window centre in native screen pixels

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        import mss

        self._ct, self._wt = ctypes, wintypes
        self._user32 = ctypes.windll.user32
        self._mss = mss.mss()
        self._hwnd = None

    def _find_window(self, pids: set[int]):
        ct, wt, user32 = self._ct, self._wt, self._user32
        found = []

        @ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def callback(hwnd, _):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
            if pid.value in pids and user32.IsWindowVisible(hwnd):
                rect = wt.RECT()
                user32.GetClientRect(hwnd, ct.byref(rect))
                found.append((rect.right * rect.bottom, hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return max(found)[1] if found else None

    def window_size(self, pids: set[int]) -> tuple[int, int]:
        ct, wt, user32 = self._ct, self._wt, self._user32
        if not self._hwnd or not user32.IsWindow(self._hwnd):
            self._hwnd = self._find_window(pids)
        if not self._hwnd:
            raise CaptureError("game window not found")
        rect = wt.RECT()
        user32.GetClientRect(self._hwnd, ct.byref(rect))
        origin = wt.POINT(0, 0)
        user32.ClientToScreen(self._hwnd, ct.byref(origin))
        self._origin = (origin.x, origin.y)
        self.center = (origin.x + rect.right // 2, origin.y + rect.bottom // 2)
        return rect.right, rect.bottom

    def grab(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        ox, oy = self._origin
        shot = self._mss.grab({"left": ox + x, "top": oy + y, "width": w, "height": h})
        return np.asarray(shot)[:, :, :3]


class _X11Grabber:
    center: tuple[int, int] | None = None

    def __init__(self):
        try:
            from Xlib import X, display
        except ImportError as e:
            raise CaptureError("python-xlib missing") from e
        try:
            self._d = display.Display()
        except Exception as e:
            raise CaptureError(f"no X display ({e})") from e
        self._X = X
        self._root = self._d.screen().root
        self._client_list = self._d.intern_atom("_NET_CLIENT_LIST")
        self._wm_pid = self._d.intern_atom("_NET_WM_PID")
        self._win = None

    def _find_window(self, pids: set[int]):
        prop = self._root.get_full_property(self._client_list, self._X.AnyPropertyType)
        best = None
        for wid in (prop.value if prop else []):
            win = self._d.create_resource_object("window", wid)
            try:
                pid_prop = win.get_full_property(self._wm_pid, self._X.AnyPropertyType)
                pid = pid_prop.value[0] if pid_prop else None
                wm_class = " ".join(win.get_wm_class() or ()).lower()
                if pid not in pids and "deadbydaylight" not in wm_class:
                    continue
                geo = win.get_geometry()
                area = geo.width * geo.height
                if best is None or area > best[0]:
                    best = (area, win)
            except Exception:
                continue
        return best[1] if best else None

    def window_size(self, pids: set[int]) -> tuple[int, int]:
        for attempt in (0, 1):
            if self._win is None:
                self._win = self._find_window(pids)
            if self._win is None:
                raise CaptureError("game window not found (is the game running under XWayland?)")
            try:
                geo = self._win.get_geometry()
                pos = self._win.translate_coords(self._root, 0, 0)
                self.center = (-pos.x + geo.width // 2, -pos.y + geo.height // 2)
                return geo.width, geo.height
            except Exception:
                self._win = None
        raise CaptureError("game window disappeared")

    def grab(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        try:
            img = self._win.get_image(x, y, w, h, self._X.ZPixmap, 0xFFFFFFFF)
        except Exception as e:
            self._win = None
            raise CaptureError(f"window capture failed ({e})") from e
        data = np.frombuffer(img.data, np.uint8)
        if data.size < w * h * 4:
            raise CaptureError(f"unsupported window depth {img.depth}")
        return data[: w * h * 4].reshape(h, w, 4)[:, :, :3]


def make_grabber():
    return _WindowsGrabber() if sys.platform == "win32" else _X11Grabber()
