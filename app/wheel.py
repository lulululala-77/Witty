"""Observe vertical wheel input over the captured conversation (Windows)."""
import ctypes as ct
from ctypes import wintypes as wt
from threading import Event, Thread


_user = ct.WinDLL("user32", use_last_error=True)
_callback = ct.WINFUNCTYPE(ct.c_ssize_t, ct.c_int, ct.c_size_t, ct.c_ssize_t)


class MouseEvent(ct.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("extra", ct.c_size_t)]


def _api(name, result, *args):
    fn = getattr(_user, name)
    fn.restype, fn.argtypes = result, args
    return fn


_install = _api("SetWindowsHookExW", wt.HANDLE, ct.c_int, _callback, wt.HMODULE, wt.DWORD)
_next = _api("CallNextHookEx", ct.c_ssize_t, wt.HANDLE, ct.c_int, ct.c_size_t, ct.c_ssize_t)
_remove = _api("UnhookWindowsHookEx", wt.BOOL, wt.HANDLE)
_window_at = _api("WindowFromPoint", wt.HWND, wt.POINT)
_ancestor = _api("GetAncestor", wt.HWND, wt.HWND, wt.UINT)
_rect = _api("GetWindowRect", wt.BOOL, wt.HWND, ct.POINTER(wt.RECT))


class WheelMonitor:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.target = None  # (conversation title, message-area rectangle)
        self.direction = {}
        self.ready = Event()
        self.error = 0

    def _handle(self, code, msg, data):
        target = self.target
        if code == 0 and msg == 0x020A and target:  # WM_MOUSEWHEEL
            event = ct.cast(data, ct.POINTER(MouseEvent)).contents
            pt = event.pt
            if _ancestor(_window_at(pt), 2) == self.hwnd:  # GA_ROOT
                bounds = wt.RECT()
                title, (left, top, right, bottom) = target
                if _rect(self.hwnd, ct.byref(bounds)):
                    x, y = pt.x - bounds.left, pt.y - bounds.top
                    delta = ct.c_short(event.mouseData >> 16).value
                    if delta and left <= x < right and top <= y < bottom:
                        if delta > 0 or title in self.direction:
                            self.direction[title] = "up" if delta > 0 else "down"
        return _next(None, code, msg, data)

    def _run(self):
        self.tid = ct.windll.kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        _user.PeekMessageW(ct.byref(msg), None, 0, 0, 0)
        callback = _callback(self._handle)
        module = ct.windll.kernel32.GetModuleHandleW
        module.restype = wt.HMODULE
        hook = _install(14, callback, module(None), 0)  # WH_MOUSE_LL
        if not hook:
            self.error = ct.get_last_error()
        self.ready.set()
        if hook:
            try:
                while _user.GetMessageW(ct.byref(msg), None, 0, 0) > 0:
                    _user.DispatchMessageW(ct.byref(msg))
            finally:
                _remove(hook)

    def __enter__(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait()
        return self

    def __exit__(self, *exc):
        self.target = None
        if self.thread.is_alive():
            _user.PostThreadMessageW(self.tid, 0x0012, 0, 0)  # WM_QUIT
            self.thread.join(2)
