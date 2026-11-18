"""Region capture using macOS's own drag-to-select tool, `screencapture`."""
import io
import os
import subprocess
import tempfile

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


def capture_region(runner=subprocess.run):
    """Lets the user drag a rectangle. Returns PNG bytes, or None if they cancelled (Esc)."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        # -i interactive, -s selection only, -x no shutter sound
        try:
            res = runner(["screencapture", "-i", "-s", "-x", path], capture_output=True, timeout=300)
        except FileNotFoundError as e:
            raise CaptureError("`screencapture` was not found - this app only runs on macOS.") from e
        except subprocess.TimeoutExpired as e:
            raise CaptureError("Selection timed out.") from e
        if res.returncode != 0 and (not os.path.exists(path) or os.path.getsize(path) == 0):
            err = (getattr(res, "stderr", b"") or b"").decode("utf-8", "ignore").strip()
            raise CaptureError(err or "screencapture failed. Is Screen Recording permission granted?")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None  # cancelled
        with open(path, "rb") as f:
            return downscale_png(f.read())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def grab_screen(runner=subprocess.run):
    """Silent screenshot of the main display (PNG bytes, full resolution)."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        try:
            res = runner(["screencapture", "-x", path], capture_output=True, timeout=30)
        except FileNotFoundError as e:
            raise CaptureError("`screencapture` was not found - this app only runs on macOS.") from e
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            err = (getattr(res, "stderr", b"") or b"").decode("utf-8", "ignore").strip()
            raise CaptureError(err or "Screenshot failed. Is Screen Recording permission granted?")
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


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
