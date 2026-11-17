"""Screen capture for Windows (Pillow ImageGrab, all monitors) + helpers."""
import ctypes
import io
import sys

MAX_EDGE = 1568  # larger images are downscaled by the API anyway


class CaptureError(Exception):
    pass


def downscale_png(data, max_edge=MAX_EDGE):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    w, h = im.size
    scale = max_edge / max(w, h)
    if scale < 1:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


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
