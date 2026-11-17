"""Global hotkeys.

macOS: uses AppKit's NSEvent global/local key monitors (pyobjc). These run on the MAIN
thread, which avoids the crash pynput hits on recent macOS (its listener thread calls
TSMGetInputSourceProperty off the main queue -> SIGTRAP). Needs Input Monitoring permission.
Other OSes: falls back to pynput (only used for development/testing).

Combo syntax: "<ctrl>+<shift>+a" (modifiers: <ctrl> <shift> <alt> <cmd>; key: a-z, 0-9, space).
"""
import sys

MODS = {"<ctrl>": 1 << 18, "<shift>": 1 << 17, "<alt>": 1 << 19, "<cmd>": 1 << 20}  # NSEventModifierFlag*
MOD_MASK = sum(MODS.values())

# macOS ANSI virtual key codes
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
    "l": 37, "j": 38, "k": 40, "n": 45, "m": 46, "space": 49,
    "]": 30, "[": 33, "\\": 42,
}


def parse(combo):
    """-> (modifier_flags, keycode). Raises ValueError with a readable message."""
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


def matches(parsed, keycode, flags):
    mods, code = parsed
    return keycode == code and (flags & MOD_MASK) == mods


class HotkeyManager:
    def __init__(self):
        self._monitors = []
        self._listener = None
        self._carbon = None
        self._esc = None
        self.backend = None   # "carbon" | "nsevent" | "pynput"

    def start(self, mapping):
        """mapping: {combo_string: callback}. Callbacks should be quick (e.g. queue.put)."""
        self.stop()
        parsed = [(parse(c), cb) for c, cb in mapping.items()]
        if sys.platform == "darwin":
            # Preferred: Carbon hotkeys - global, no permission needed.
            try:
                import carbon_hotkeys
                c = carbon_hotkeys.CarbonHotkeys()
                c.register([(m, code, cb) for ((m, code), cb) in parsed])
                self._carbon, self.backend = c, "carbon"
                return
            except Exception as e:
                self.carbon_error = str(e)
                try:
                    c.unregister_all()
                except Exception:
                    pass
            self.backend = "nsevent"   # fallback: needs Input Monitoring
            from AppKit import NSEvent
            KEYDOWN_MASK = 1 << 10

            def dispatch(event):
                if event.isARepeat():
                    return
                for p, cb in parsed:
                    if matches(p, int(event.keyCode()), int(event.modifierFlags())):
                        cb()
                        break

            def local(event):
                dispatch(event)
                return event

            g = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(KEYDOWN_MASK, dispatch)
            l = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(KEYDOWN_MASK, local)
            self._monitors = [m for m in (g, l) if m is not None]
            if g is None:
                raise RuntimeError("macOS refused the global key monitor - grant Input Monitoring and restart the app")
        else:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys({c: cb for c, cb in mapping.items()})
            self._listener.daemon = True
            self._listener.start()
            self.backend = "pynput"

    def add_escape(self, cb):
        """While a region is being picked: make a bare Esc cancel, even if our full-screen window is not
        the key window (borderless Tk windows often can't receive keys on macOS). Needs no permission."""
        self.remove_escape()
        if sys.platform != "darwin":
            return False
        try:
            import carbon_hotkeys
            c = carbon_hotkeys.CarbonHotkeys()
            c.register([(0, 53, cb)])   # keycode 53 = Esc, no modifiers
            self._esc = c
            return True
        except Exception:
            self._esc = None
            return False

    def remove_escape(self):
        if self._esc:
            self._esc.unregister_all()
            self._esc = None

    def stop(self):
        self.remove_escape()
        if self._carbon:
            self._carbon.unregister_all()
            self._carbon = None
        if self._monitors:
            from AppKit import NSEvent
            for m in self._monitors:
                NSEvent.removeMonitor_(m)
            self._monitors = []
        if self._listener:
            self._listener.stop()
            self._listener = None


def keep_awake(reason="Listening for global hotkeys"):
    """macOS: stop App Nap from throttling the app when it has no visible window, which would
    delay or drop hotkeys. Returns a token that must be kept referenced; None elsewhere."""
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import NSProcessInfo
        USER_INITIATED_ALLOWING_IDLE_SLEEP = 0x00FFFFFF & ~(1 << 20)
        return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(USER_INITIATED_ALLOWING_IDLE_SLEEP, reason)
    except Exception:
        return None


def input_monitoring_granted(request=False):
    """True/False on macOS (False means global hotkeys will silently not fire); None if unknown."""
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        ok = bool(Quartz.CGPreflightListenEventAccess())
        if not ok and request:
            Quartz.CGRequestListenEventAccess()
        return ok
    except Exception:
        return None
