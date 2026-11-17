"""macOS Screen Recording permission: status check and a shortcut to the right Settings pane.
(Input Monitoring is deliberately not handled here: the hotkeys use Carbon, which needs no permission.)"""
import subprocess
import sys

SCREEN_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"


def screen_recording_granted():
    """True / False on macOS; None when it can't be determined (other OS, old macOS)."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        fn = cg.CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def request_screen_recording():
    """Shows the system prompt once (no-op if already decided). Returns the granted state or None."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        fn = cg.CGRequestScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def open_screen_recording_settings():
    """True if the Settings pane was opened."""
    if sys.platform != "darwin":
        return False
    subprocess.run(["open", SCREEN_PANE])
    return True
