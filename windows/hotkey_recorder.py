"""A button you click and then press the key combo you want (instead of typing it)."""
import sys
import tkinter as tk
from tkinter import ttk

import hotkeys

NAMED = {"bracketright": "]", "bracketleft": "[", "backslash": "\\", "space": "space"}
SHIFTED = {"braceright": "]", "braceleft": "[", "bar": "\\", "exclam": "1", "at": "2", "numbersign": "3",
           "dollar": "4", "percent": "5", "asciicircum": "6", "ampersand": "7", "asterisk": "8",
           "parenleft": "9", "parenright": "0"}
MODIFIER_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                    "Super_L", "Super_R", "Caps_Lock", "Command", "Option_L", "Option_R", "Mode_switch",
                    "ISO_Level3_Shift"}


def _bits(platform):
    # Tk event.state modifier bits
    if platform == "darwin":
        return {"shift": 0x1, "ctrl": 0x4, "alt": 0x10, "cmd": 0x8}
    if platform == "win32":
        return {"shift": 0x1, "ctrl": 0x4, "alt": 0x20000, "cmd": 0}   # 0x8 is NumLock; the Win key isn't reported
    return {"shift": 0x1, "ctrl": 0x4, "alt": 0x8, "cmd": 0x40}


def combo_from_event(keysym, keycode, state, platform=sys.platform):
    """Returns a combo string like '<ctrl>+<shift>+a', None for a bare modifier press
    (keep waiting), or raises ValueError with a message for the user."""
    if keysym in MODIFIER_KEYSYMS:
        return None
    key = None
    low = keysym.lower()
    if low in hotkeys.KEYCODES:
        key = low
    elif keysym in NAMED:
        key = NAMED[keysym]
    elif keysym in SHIFTED:
        key = SHIFTED[keysym]
    if key is None:
        raise ValueError(f"'{keysym}' can't be used. Use a letter, digit, space, [ ] or \\.")
    b = _bits(platform)
    parts = [name for name, bit in (("<ctrl>", b["ctrl"]), ("<shift>", b["shift"]),
                                     ("<alt>", b["alt"]), ("<cmd>", b["cmd"])) if state & bit]
    if not parts:
        raise ValueError("Hold Ctrl, Shift or Alt while you press the key.")
    combo = "+".join(parts + [key])
    hotkeys.parse(combo)  # must be valid
    return combo


def pretty(combo, platform=sys.platform):
    if not combo:
        return "(not set)"
    names = {"<ctrl>": "Ctrl", "<shift>": "Shift", "<alt>": "Option" if platform == "darwin" else "Alt",
             "<cmd>": "Win" if platform == "win32" else "Cmd"}
    return " + ".join(names.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in combo.split("+"))


def symbols(combo, platform=sys.platform):
    """Display form with macOS symbols, in the order macOS shows them (⌃ ⌥ ⇧ ⌘ key)."""
    if not combo:
        return "Not set"
    parts = combo.split("+")
    key = parts[-1]
    mods = set(parts[:-1])
    keyname = "Space" if key == "space" else key.upper()
    if platform == "darwin":
        order = (("<ctrl>", "⌃"), ("<alt>", "⌥"), ("<shift>", "⇧"), ("<cmd>", "⌘"))
        return " ".join([sym for tag, sym in order if tag in mods] + [keyname])
    order = (("<ctrl>", "Ctrl"), ("<alt>", "Alt"), ("<shift>", "Shift"), ("<cmd>", "Win"))
    return " + ".join([n for tag, n in order if tag in mods] + [keyname])


class HotkeyRecorder(ttk.Button):
    def __init__(self, parent, var, on_message=None):
        super().__init__(parent, command=self.begin)
        self.var, self.on_message, self.recording = var, on_message, False
        self.bind("<KeyPress>", self._key)
        self.bind("<FocusOut>", lambda e: self._stop())
        var.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    def _refresh(self):
        self.configure(text="Press the keys…  (Esc cancels)" if self.recording
                       else f"{pretty(self.var.get())}   — click to change")

    def begin(self):
        self.recording = True
        self._refresh()
        self.focus_force()

    def _stop(self):
        self.recording = False
        self._refresh()

    def _key(self, e):
        if not self.recording:
            return None
        if e.keysym == "Escape":
            self._stop()
            return "break"
        try:
            combo = combo_from_event(e.keysym, e.keycode, e.state)
        except ValueError as err:
            if self.on_message:
                self.on_message(str(err))
            return "break"
        if combo is not None:
            self.var.set(combo)
            self._stop()
        return "break"
