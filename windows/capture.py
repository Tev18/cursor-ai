"""Screen capture for Windows (Pillow ImageGrab, all monitors) + helpers."""
import ctypes
import io
import sys

MAX_EDGE = 2576          # keep detail: only very large regions are scaled down (small text stays sharp)
MAX_BYTES = 4_500_000    # the API rejects images over 5 MB


class CaptureError(Exception):
    pass


def downscale_png(data, max_edge=MAX_EDGE, max_bytes=MAX_BYTES):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    w, h = im.size
    edge = max_edge
    while True:
        scale = edge / max(w, h)
        cur = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS) if scale < 1 else im
        out = io.BytesIO()
        cur.save(out, "PNG", optimize=True)
        if out.tell() <= max_bytes or edge <= 600:
            return out.getvalue()
        edge = int(min(edge, max(w, h)) * 0.85)   # still too big for the API: shrink a little and retry


def virtual_screen(root=None):
    """(left, top, width, height) of the whole desktop across all monitors, in pixels."""
    if sys.platform == "win32":
        gm = ctypes.windll.user32.GetSystemMetrics
        return gm(76), gm(77), gm(78), gm(79)   # SM_X/Y/CX/CYVIRTUALSCREEN
    if root is not None:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    raise CaptureError("No screen information available.")


def grab_screen(grabber=None):
    """Silent screenshot of ALL monitors (PNG bytes)."""
    try:
        if grabber is None:
            from PIL import ImageGrab
            grabber = lambda: ImageGrab.grab(all_screens=True)
        im = grabber()
        out = io.BytesIO()
        im.convert("RGB").save(out, "PNG")
        return out.getvalue()
    except Exception as e:
        raise CaptureError(f"Screenshot failed: {e}") from e


def crop_and_downscale(png_bytes, box):
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes))
    im.load()
    out = io.BytesIO()
    im.convert("RGB").crop(box).save(out, "PNG")
    return downscale_png(out.getvalue())


def full_box(png_bytes):
    """Crop box covering the whole screenshot."""
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes))
    return (0, 0, im.width, im.height)
