"""System-wide hotkeys on Windows via the Win32 RegisterHotKey API (ctypes, no extra packages).
Works whichever app is in front, needs no special permission. A background thread owns the
registrations and message loop; callbacks run on that thread, so they must only do thread-safe
things (the app just puts a message on a queue).

Combo syntax: "<ctrl>+<shift>+a" (modifiers <ctrl> <shift> <alt> <cmd>=Windows key; key a-z 0-9 space [ ] \\).
"""
import ctypes
import sys
import threading

MODS = {"<alt>": 0x0001, "<ctrl>": 0x0002, "<shift>": 0x0004, "<cmd>": 0x0008}  # MOD_ALT/CONTROL/SHIFT/WIN
MOD_MASK = sum(MODS.values())
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

# Windows virtual-key codes
KEYCODES = {chr(c): c for c in range(ord("A"), ord("Z") + 1)}
KEYCODES = {k.lower(): v for k, v in KEYCODES.items()}
KEYCODES.update({str(d): 0x30 + d for d in range(10)})
KEYCODES.update({"space": 0x20, "[": 0xDB, "\\": 0xDC, "]": 0xDD})


def parse(combo):
    """-> (modifier_bits, virtual_key). Raises ValueError with a readable message."""
    if not combo or not combo.strip():
        raise ValueError("Hotkey is empty.")
    mods, key = 0, None
    for part in (p.strip().lower() for p in combo.split("+")):
        if part in MODS:
            mods |= MODS[part]
        elif part in KEYCODES:
            if key is not None:
                raise ValueError("Only one normal key is allowed.")
            key = part
        else:
            raise ValueError(f"Unknown key '{part}'. Use modifiers <ctrl> <shift> <alt> <cmd> and a letter, digit, space, [ ] or \\.")
    if not mods:
        raise ValueError("Include at least one modifier, e.g. <ctrl>+<shift>+a")
    if key is None:
        raise ValueError("Add a normal key after the modifiers.")
    return mods, KEYCODES[key]


def validate(combo):
    try:
        parse(combo)
        return None
    except ValueError as e:
        return str(e)


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t), ("time", ctypes.c_uint32), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


def keep_awake(*a, **k):      # macOS-only concept; kept so app code is shared
    return None


class HotkeyManager:
    def __init__(self, user32=None, kernel32=None):
        self._user32, self._kernel32 = user32, kernel32
        self._thread = None
        self._thread_id = None
        self.backend = None
        self.error = None

    def _libs(self):
        if self._user32 is None:
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
        return self._user32, self._kernel32

    def start(self, mapping):
        """mapping: {combo_string: callback}. Raises RuntimeError if Windows refuses a combo."""
        self.stop()
        parsed = [(parse(c), cb, c) for c, cb in mapping.items()]
        user32, kernel32 = self._libs()
        ready, state = threading.Event(), {"error": None}

        def run():
            self._thread_id = kernel32.GetCurrentThreadId()
            msg = _MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # create this thread's message queue
            ids = {}
            for i, ((mods, vk), cb, combo) in enumerate(parsed, start=1):
                if not user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                    state["error"] = f"Windows refused {combo} (another program probably uses it) - pick a different combo."
                    break
                ids[i] = cb
            ready.set()
            try:
                if state["error"] is None:
                    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                        if msg.message == WM_HOTKEY and msg.wParam in ids:
                            try:
                                ids[msg.wParam]()
                            except Exception:
                                pass
            finally:
                for i in ids:
                    user32.UnregisterHotKey(None, i)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(5)
        if state["error"]:
            self.error = state["error"]
            self._thread.join(2)
            self._thread = None
            raise RuntimeError(state["error"])
        self.backend, self.error = "win32", None

    def add_escape(self, cb):
        return False   # not needed on Windows: the selector window receives Esc itself

    def remove_escape(self):
        pass

    def stop(self):
        if self._thread:
            try:
                self._libs()[0].PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
            self._thread.join(2)
            self._thread = None
