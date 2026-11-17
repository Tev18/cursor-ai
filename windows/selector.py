"""Our own region picker: shows a frozen copy of the screen with the normal arrow cursor (it does not change). Click one
corner, then the opposite corner. Nothing is drawn (no outline, no fill, no dragging)."""
import base64
import io
import tkinter as tk

MIN_SIZE = 10  # points


def image_box(x0, y0, x1, y1, scale_x, scale_y, img_w, img_h):
    """Drag corners in screen points -> (left, top, right, bottom) in image pixels, clamped."""
    l, r = sorted((x0, x1))
    t, b = sorted((y0, y1))
    box = (round(l * scale_x), round(t * scale_y), round(r * scale_x), round(b * scale_y))
    box = (max(0, min(box[0], img_w - 1)), max(0, min(box[1], img_h - 1)),
           max(1, min(box[2], img_w)), max(1, min(box[3], img_h)))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


class RegionSelector:
    def __init__(self, root, png_bytes, on_done, area=None):
        from PIL import Image
        self.on_done = on_done
        self.done = False
        im = Image.open(io.BytesIO(png_bytes))
        im.load()
        self.img_w, self.img_h = im.size
        # area = (left, top, width, height) of the whole desktop (may start at negative x/y with several monitors)
        left, top, self.sw, self.sh = area or (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        self.sx, self.sy = self.img_w / self.sw, self.img_h / self.sh
        shown = im.convert("RGB").resize((self.sw, self.sh), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        shown.save(buf, "PNG", compress_level=1)   # fast: this runs while the user waits

        # Build everything while the window is hidden and fully transparent, and show it only once the
        # screenshot is loaded - otherwise a blank/black full-screen window flashes before the picture.
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.win.overrideredirect(True)
        self.win.geometry(f"{self.sw}x{self.sh}+{left}+{top}")   # "+-1920" is how Tk spells a negative offset
        self.win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.win, width=self.sw, height=self.sh, highlightthickness=0,
                                cursor="arrow", bg="black")
        self.canvas.pack()
        self.canvas.configure(cursor="arrow")
        self.photo = tk.PhotoImage(master=self.win, data=base64.b64encode(buf.getvalue()))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.start = None
        # Two plain clicks: first corner, then opposite corner. Nothing is drawn; only the cursor changes.
        self.canvas.bind("<ButtonPress-1>", self._click)
        self.canvas.bind("<ButtonPress-2>", lambda e: self._finish(None))
        self.canvas.bind("<ButtonPress-3>", lambda e: self._finish(None))
        self.win.bind("<Escape>", lambda e: self._finish(None))
        self.win.update_idletasks()      # lay out + decode the image while still hidden
        self.win.deiconify()
        self.win.lift()
        self.win.update_idletasks()      # first paint happens at alpha 0 ...
        try:
            self.win.attributes("-alpha", 1.0)   # ... then it appears in one step, already showing the screenshot
        except tk.TclError:
            pass
        self.win.focus_force()
        self.canvas.focus_set()

    def _click(self, e):
        if self.start is None:
            self.start = (e.x, e.y)
            return
        (x0, y0), (x1, y1) = self.start, (e.x, e.y)
        if abs(x1 - x0) < MIN_SIZE or abs(y1 - y0) < MIN_SIZE:
            return  # too close to the first corner: click somewhere else (Esc cancels)
        self._finish(image_box(x0, y0, x1, y1, self.sx, self.sy, self.img_w, self.img_h))

    def cancel(self):
        self._finish(None)

    def _finish(self, box):
        if self.done:
            return
        self.done = True
        self.win.destroy()
        self.on_done(box)
