"""System-wide hotkeys through Carbon's RegisterEventHotKey (ctypes).

Why: it works while ANY app is in front and needs NO Input Monitoring / Accessibility
permission (unlike key monitors, which silently do nothing without it). Events arrive on the
main thread through the normal Cocoa/Tk event loop.
"""
import ctypes
import ctypes.util


def fourcc(s):
    return int.from_bytes(s.encode("ascii"), "big")


K_EVENT_CLASS_KEYBOARD = fourcc("keyb")
K_EVENT_HOTKEY_PRESSED = 5
K_EVENT_PARAM_DIRECT_OBJECT = fourcc("----")
TYPE_EVENT_HOTKEY_ID = fourcc("hkid")
SIGNATURE = fourcc("CAIk")

# NSEvent modifier bits (what hotkeys.parse produces) -> Carbon modifier bits
_NS_TO_CARBON = {1 << 20: 0x0100, 1 << 17: 0x0200, 1 << 19: 0x0800, 1 << 18: 0x1000}  # cmd shift option control


def carbon_mods(ns_flags):
    return sum(c for ns, c in _NS_TO_CARBON.items() if ns_flags & ns)


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


import itertools

_INSTANCES = itertools.count(1)
NOT_HANDLED = -9874   # eventNotHandledErr: lets another handler (another instance) take the event


class CarbonHotkeys:
    def __init__(self, lib=None):
        if lib is None:
            path = ctypes.util.find_library("Carbon") or "/System/Library/Frameworks/Carbon.framework/Carbon"
            lib = ctypes.CDLL(path)
            lib.GetApplicationEventTarget.restype = ctypes.c_void_p
            lib.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_uint32,
                                                ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p)]
            lib.InstallEventHandler.restype = ctypes.c_int32
            lib.RemoveEventHandler.argtypes = [ctypes.c_void_p]
            lib.RemoveEventHandler.restype = ctypes.c_int32
            lib.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                                ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
            lib.RegisterEventHotKey.restype = ctypes.c_int32
            lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            lib.UnregisterEventHotKey.restype = ctypes.c_int32
            lib.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                              ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
            lib.GetEventParameter.restype = ctypes.c_int32
        self.lib = lib
        self._base = next(_INSTANCES) * 1000   # ids never collide between instances
        self._callbacks = {}
        self._refs = []
        self._handler_ref = ctypes.c_void_p()
        self._upp = HANDLER(self._on_event)   # keep referenced or it is garbage-collected -> crash
        self._installed = False

    def _on_event(self, call_ref, event, user_data):
        try:
            hk = EventHotKeyID()
            st = self.lib.GetEventParameter(event, K_EVENT_PARAM_DIRECT_OBJECT, TYPE_EVENT_HOTKEY_ID, None,
                                            ctypes.sizeof(hk), None, ctypes.byref(hk))
            if st == 0 and hk.signature == SIGNATURE:
                cb = self._callbacks.get(hk.id)
                if cb:
                    cb()
                    return 0  # noErr: handled
        except Exception:
            pass
        return NOT_HANDLED

    def register(self, items):
        """items: [(ns_modifier_flags, mac_keycode, callback)]. Raises OSError on any failure."""
        target = self.lib.GetApplicationEventTarget()
        if not self._installed:
            spec = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
            st = self.lib.InstallEventHandler(target, self._upp, 1, ctypes.byref(spec), None,
                                              ctypes.byref(self._handler_ref))
            if st != 0:
                raise OSError(f"InstallEventHandler failed ({st})")
            self._installed = True
        for i, (mods, code, cb) in enumerate(items, start=1):
            ref = ctypes.c_void_p()
            st = self.lib.RegisterEventHotKey(code, carbon_mods(mods), EventHotKeyID(SIGNATURE, self._base + i), target, 0,
                                              ctypes.byref(ref))
            if st != 0:
                raise OSError(f"RegisterEventHotKey failed ({st}) - another app may already own that combo")
            self._refs.append(ref)
            self._callbacks[self._base + i] = cb

    def unregister_all(self):
        for ref in self._refs:
            try:
                self.lib.UnregisterEventHotKey(ref)
            except Exception:
                pass
        self._refs, self._callbacks = [], {}
        if self._installed:
            try:
                self.lib.RemoveEventHandler(self._handler_ref)
            except Exception:
                pass
            self._installed = False
