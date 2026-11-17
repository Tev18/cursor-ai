"""Black-and-gold widget kit for Cursor AI.

Tk's own widgets can't have rounded corners, so every control here is drawn on a tk.Canvas
(polygons with smoothing), with animated hover / press feedback. Nothing in this file knows
about the app's behaviour: widgets take a tk variable and/or a callback.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont

import hotkey_recorder

# ---------- palette ----------
BG = "#0D0D0F"            # main background
CARD = "#191919"          # cards and panels
SURFACE = "#252525"       # secondary surfaces (inputs, tiles)
GOLD = "#D4AF37"          # primary accent
GOLD_HOVER = "#EAC85C"
GOLD_PRESS = "#B8962E"
TEXT = "#F5F2EA"          # primary text
TEXT2 = "#9E9A92"         # secondary text
BORDER = "#34302A"
SUCCESS = "#76DCA1"
ERROR = "#E5736B"         # failures (not in the brief's palette, but errors need a colour)
SHADOW = "#050506"
ON_GOLD = "#16130A"       # text drawn on gold
SURFACE_HOVER = "#2F2F2F"
SURFACE_PRESS = "#1E1E1E"
DISABLED_BG = "#1F1F1F"
DISABLED_FG = "#6E6A62"
GOLD_TINT = "#2B2616"     # listening / selected tint

R_CARD = 18
R_CTRL = 12

IS_MAC = sys.platform == "darwin"
PLATFORM = sys.platform
FAMILY = ".AppleSystemUIFont" if IS_MAC else ("Segoe UI" if sys.platform == "win32" else "Helvetica")
MONO = "Menlo" if IS_MAC else ("Consolas" if sys.platform == "win32" else "Courier")
HAND = "pointinghand" if IS_MAC else "hand2"


def font(size=13, weight="normal", mono=False):
    return (MONO if mono else FAMILY, size, weight)


def text_width(widget, text, fnt):
    return tkfont.Font(root=widget, font=fnt).measure(text)


# ---------- helpers ----------
def _rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def tween(widget, key, a, b, apply, ms=120, steps=6):
    """Animate from a to b (hex colours or numbers), calling apply(value) each step."""
    ids = widget.__dict__.setdefault("_tweens", {})
    old = ids.pop(key, None)
    if old is not None:
        try:
            widget.after_cancel(old)
        except tk.TclError:
            pass

    def step(i):
        t = i / steps
        try:
            apply(lerp(a, b, t) if isinstance(a, str) else a + (b - a) * t)
            if i < steps:
                ids[key] = widget.after(max(1, ms // steps), step, i + 1)
            else:
                ids.pop(key, None)
        except tk.TclError:
            ids.pop(key, None)   # widget was destroyed mid-animation

    step(0)


def rrect(c, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle polygon (doubled points keep the edges straight, corners smooth)."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
           x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
           x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def _size(c):
    w, h = c.winfo_width(), c.winfo_height()
    if w <= 1:
        w = int(float(c.cget("width")))
    if h <= 1:
        h = int(float(c.cget("height")))
    return w, h


# ---------- cards ----------
class Card(tk.Canvas):
    """Rounded card with a soft shadow. Put widgets in `.content`; optional title/subtitle and a
    `.right` slot (top-right of the title row)."""

    def __init__(self, parent, title=None, subtitle=None, pad=14, bg=BG):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=40)
        self.pad = pad
        self.body = tk.Frame(self, bg=CARD)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self.body.columnconfigure(0, weight=1)
        row = 0
        if title:
            tk.Label(self.body, text=title.upper(), bg=CARD, fg=GOLD, font=font(11, "bold"), anchor="w") \
                .grid(row=0, column=0, sticky="w")
            row = 1
            if subtitle:
                self.sub = tk.Label(self.body, text=subtitle, bg=CARD, fg=TEXT2, font=font(12), anchor="w",
                                    justify="left", wraplength=560)
                self.sub.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
                row = 2
        self.right = tk.Frame(self.body, bg=CARD)
        self.right.grid(row=0, column=1, sticky="e")
        self.content = tk.Frame(self.body, bg=CARD)
        self.content.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10 if title else 0, 0))
        self.content.columnconfigure(0, weight=1)
        self.bind("<Configure>", self._on_canvas)
        self.body.bind("<Configure>", self._on_body)

    def _on_canvas(self, e):
        self.itemconfigure(self._win, width=max(1, e.width - 2 * self.pad))
        if getattr(self, "sub", None):
            self.sub.configure(wraplength=max(120, e.width - 2 * self.pad - 4))
        self._draw()

    def _on_body(self, e):
        h = e.height + 2 * self.pad + 4
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)
        self._draw()

    def _draw(self):
        self.delete("bg")
        w, h = _size(self)
        rrect(self, 1, 4, w - 1, h - 1, R_CARD, fill=SHADOW, outline="", tags="bg")                # soft shadow
        rrect(self, 1, 1, w - 1, h - 4, R_CARD, fill=CARD, outline=BORDER, width=1, tags="bg")
        self.tag_lower("bg")


def divider(parent):
    return tk.Frame(parent, bg=BORDER, height=1)


def label(parent, text, size=13, weight="normal", fg=TEXT, bg=CARD, **kw):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=font(size, weight), anchor="w", justify="left", **kw)


def autowrap(lbl, margin=0):
    """Keep a label's wrap width in step with its width, so text reflows when the window resizes."""
    lbl.master.bind("<Configure>", lambda e: lbl.configure(wraplength=max(120, e.width - margin)), add="+")


# ---------- buttons ----------
class RoundButton(tk.Canvas):
    STYLES = {
        "primary": dict(fill=GOLD, hover=GOLD_HOVER, press=GOLD_PRESS, fg=ON_GOLD, border=None),
        "secondary": dict(fill=SURFACE, hover=SURFACE_HOVER, press=SURFACE_PRESS, fg=TEXT, border=BORDER),
        "danger": dict(fill=SURFACE, hover="#3A2626", press="#2A1A1A", fg=ERROR, border=BORDER),
    }

    def __init__(self, parent, text, command=None, style="secondary", bg=CARD, height=38, radius=R_CTRL,
                 size=13, min_width=0, pad=20):
        self.style = self.STYLES[style]
        self.command = command
        self.enabled = True
        self._text = text
        self._radius = radius
        self._font = font(size, "bold" if style == "primary" else "normal")
        self._fill = self.style["fill"]
        w = max(min_width, text_width(parent, text, self._font) + 2 * pad)
        super().__init__(parent, width=w, height=height, bg=bg, highlightthickness=0, bd=0, cursor=HAND)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    # drawing
    def _fg(self):
        return self.style["fg"] if self.enabled else DISABLED_FG

    def _border(self):
        if not self.enabled:
            return BORDER
        return self.style["border"] or self._fill

    def _draw(self):
        self.delete("all")
        w, h = _size(self)
        self._box = rrect(self, 1, 1, w - 1, h - 1, self._radius,
                          fill=self._fill if self.enabled else DISABLED_BG, outline=self._border(), width=1)
        self.create_text(w / 2, h / 2, text=self._text, fill=self._fg(), font=self._font, tags="label")

    def _recolor(self, c):
        self._fill = c
        try:
            self.itemconfigure(self._box, fill=c, outline=self.style["border"] or c)
        except tk.TclError:
            pass

    # events
    def _enter(self, _e):
        if self.enabled:
            tween(self, "fill", self._fill, self.style["hover"], self._recolor)

    def _leave(self, _e):
        if self.enabled:
            tween(self, "fill", self._fill, self.style["fill"], self._recolor)

    def _press(self, _e):
        if self.enabled:
            tween(self, "fill", self._fill, self.style["press"], self._recolor, ms=40, steps=2)

    def _release(self, e):
        if not self.enabled:
            return
        w, h = _size(self)
        inside = 0 <= e.x <= w and 0 <= e.y <= h
        tween(self, "fill", self._fill, self.style["hover"] if inside else self.style["fill"], self._recolor, ms=80, steps=3)
        if inside and self.command:
            self.command()

    # api
    def invoke(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self._fill = self.style["fill"]
        self.configure(cursor=HAND if self.enabled else "arrow")
        self._draw()

    def set_text(self, text):
        self._text = text
        self._draw()


# ---------- text input ----------
class RoundEntry(tk.Canvas):
    def __init__(self, parent, textvariable=None, show=None, height=42, bg=CARD, mono=False, size=13):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0)
        self.entry = tk.Entry(self, textvariable=textvariable, show=show or "", bd=0, highlightthickness=0,
                              relief="flat", bg=SURFACE, fg=TEXT, insertbackground=GOLD, selectbackground=GOLD,
                              selectforeground=ON_GOLD, font=font(size, mono=mono), disabledbackground=SURFACE)
        self._border = BORDER
        self.bind("<Configure>", lambda e: self._layout())
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))

    def _layout(self):
        self.delete("all")
        w, h = _size(self)
        self._box = rrect(self, 1, 1, w - 1, h - 1, R_CTRL, fill=SURFACE, outline=self._border, width=1)
        self.create_window(14, h / 2, anchor="w", window=self.entry, width=max(10, w - 28))

    def _set_border(self, c):
        self._border = c
        try:
            self.itemconfigure(self._box, outline=c)
        except tk.TclError:
            pass

    def _focus(self, on):
        tween(self, "border", self._border, GOLD if on else BORDER, self._set_border)

    def set_hidden(self, hidden):
        self.entry.configure(show="•" if hidden else "")


# ---------- scrollbar ----------
class ThinScrollbar(tk.Canvas):
    def __init__(self, parent, command, bg=BG, width=10):
        super().__init__(parent, width=width, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.lo, self.hi = 0.0, 1.0
        self._off = None
        self._color = BORDER
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_off", None))
        self.bind("<Enter>", lambda e: tween(self, "c", self._color, GOLD, self._recolor))
        self.bind("<Leave>", lambda e: tween(self, "c", self._color, BORDER, self._recolor))

    def set(self, lo, hi):
        self.lo, self.hi = float(lo), float(hi)
        self._draw()

    def _recolor(self, c):
        self._color = c
        self.itemconfigure("thumb", fill=c)

    def _thumb(self):
        h = max(1, self.winfo_height())
        y1, y2 = self.lo * h, self.hi * h
        if y2 - y1 < 28:
            y2 = y1 + 28
        return y1, min(y2, h)

    def _draw(self):
        self.delete("all")
        if self.hi - self.lo >= 0.999:
            return
        y1, y2 = self._thumb()
        w = max(1, self.winfo_width())
        rrect(self, 2, y1 + 1, w - 2, y2 - 1, 3, fill=self._color, outline="", tags="thumb")

    def _press(self, e):
        y1, y2 = self._thumb()
        h = max(1, self.winfo_height())
        if y1 <= e.y <= y2:
            self._off = e.y - y1
        else:
            self._off = (y2 - y1) / 2
            self.command("moveto", (e.y - self._off) / h)

    def _motion(self, e):
        if self._off is not None:
            self.command("moveto", (e.y - self._off) / max(1, self.winfo_height()))


def _wheel_pixels(event):
    d = event.delta
    return -d * (12 if IS_MAC else 0.5) if d else 0


def _touchpad_dy(event):
    """Vertical pixels from a Tk 9 <TouchpadScroll> event (0 if it can't be decoded)."""
    try:
        dx, dy = event.widget.tk.call("::tk::PreciseScrollDeltas", event.delta)
        return float(dy)
    except Exception:
        return 0.0


class ScrollFrame(tk.Frame):
    """Vertically scrolling area with a centred content column that adapts to the window width."""

    def __init__(self, parent, max_width=820, pad=24, bg=BG):
        super().__init__(parent, bg=bg)
        self.max_width, self.pad = max_width, pad
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.sb = ThinScrollbar(self, self.canvas.yview, bg=bg)
        self.sb.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=6)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, anchor="n", window=self.inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")
        try:
            self.canvas.bind_all("<TouchpadScroll>", self._touchpad, add="+")
        except tk.TclError:
            pass                                   # Tk 8.6 has no such event
        self.canvas.bind_all("<Button-4>", lambda e: self._scroll(-40), add="+")
        self.canvas.bind_all("<Button-5>", lambda e: self._scroll(40), add="+")

    def _on_canvas(self, e):
        w = max(200, min(self.max_width, e.width - 2 * self.pad))
        self.canvas.coords(self._win, e.width / 2, 0)
        self.canvas.itemconfigure(self._win, width=w)
        self._fit()

    def _on_inner(self, e):
        self._fit()

    def _fit(self):
        h = self.inner.winfo_reqheight() + self.pad
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width()), h))
        lo, hi = self.canvas.yview()
        if hi - lo >= 1:
            self.canvas.yview_moveto(0)

    def _scroll(self, px):
        """Scroll by a number of pixels. (Canvas.yview_scroll has no 'pixels' unit, so use moveto.)"""
        lo, hi = self.canvas.yview()
        if hi - lo >= 1 or not px:
            return
        total = max(1, self.inner.winfo_reqheight() + self.pad)
        top = min(max(0.0, lo + px / total), 1.0 - (hi - lo))
        self.canvas.yview_moveto(top)

    def _over_me(self, e):
        w = e.widget
        return isinstance(w, tk.Misc) and str(w).startswith(str(self.canvas))

    def _wheel(self, e):
        if self._over_me(e):
            self._scroll(_wheel_pixels(e))

    def _touchpad(self, e):
        """Tk 9 on macOS sends two-finger scrolls as <TouchpadScroll> instead of <MouseWheel>."""
        if self._over_me(e):
            self._scroll(-_touchpad_dy(e))


# ---------- multi-line editor ----------
class RoundText(tk.Canvas):
    def __init__(self, parent, height=170, bg=CARD, mono=True, size=12):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0)
        self.text = tk.Text(self, wrap="word", bd=0, highlightthickness=0, relief="flat", bg=SURFACE, fg=TEXT,
                            insertbackground=GOLD, selectbackground=GOLD, selectforeground=ON_GOLD,
                            font=font(size, mono=mono), padx=6, pady=4, undo=True, spacing1=1, spacing3=2)
        self.sb = ThinScrollbar(self, self.text.yview, bg=SURFACE)
        self.text.configure(yscrollcommand=self.sb.set)
        self._border = BORDER
        self.bind("<Configure>", lambda e: self._layout())
        self.bind("<Button-1>", lambda e: self.text.focus_set())
        self.text.bind("<FocusIn>", lambda e: tween(self, "b", self._border, GOLD, self._set_border))
        self.text.bind("<FocusOut>", lambda e: tween(self, "b", self._border, BORDER, self._set_border))
        self.text.bind("<MouseWheel>", self._wheel)

    def _wheel(self, e):
        lo, hi = self.text.yview()
        if hi - lo >= 1:
            return None                      # nothing to scroll here: let the page scroll
        try:
            self.text.yview_scroll(int(_wheel_pixels(e)) or (-1 if e.delta > 0 else 1), "pixels")
        except tk.TclError:
            self.text.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _layout(self):
        self.delete("all")
        w, h = _size(self)
        self._box = rrect(self, 1, 1, w - 1, h - 1, R_CTRL, fill=SURFACE, outline=self._border, width=1)
        self.create_window(12, 10, anchor="nw", window=self.text, width=max(20, w - 12 - 26), height=max(20, h - 20))
        self.create_window(w - 8, 10, anchor="ne", window=self.sb, width=8, height=max(20, h - 20))

    def _set_border(self, c):
        self._border = c
        try:
            self.itemconfigure(self._box, outline=c)
        except tk.TclError:
            pass


# ---------- dropdown ----------
class RoundDropdown(tk.Canvas):
    ROW_H = 38

    def __init__(self, parent, variable, values, on_change=None, height=42, bg=CARD):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0, cursor=HAND)
        self.var, self.values, self.on_change = variable, list(values), on_change
        self._fill, self._pop, self._bind_id, self._esc_id = SURFACE, None, None, None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: tween(self, "f", self._fill, SURFACE_HOVER, self._recolor))
        self.bind("<Leave>", lambda e: tween(self, "f", self._fill, SURFACE, self._recolor))
        self.bind("<ButtonRelease-1>", lambda e: self.toggle())
        self.var.trace_add("write", lambda *a: self._draw())

    def _recolor(self, c):
        self._fill = c
        try:
            self.itemconfigure(self._box, fill=c)
        except tk.TclError:
            pass

    def _draw(self):
        self.delete("all")
        w, h = _size(self)
        self._box = rrect(self, 1, 1, w - 1, h - 1, R_CTRL, fill=self._fill,
                          outline=GOLD if self._pop else BORDER, width=1)
        self.create_text(16, h / 2, anchor="w", text=self.var.get(), fill=TEXT, font=font(13))
        cx, cy = w - 24, h / 2
        self.create_line(cx - 5, cy - 2, cx, cy + 3, cx + 5, cy - 2, fill=GOLD, width=2, capstyle="round",
                         joinstyle="round")

    def set_values(self, values):
        self.values = list(values)

    def toggle(self):
        self.close() if self._pop else self.open()

    def open(self):
        if self._pop:
            return
        top = self.winfo_toplevel()
        vals = list(self.values)
        cur = self.var.get()
        if cur and cur not in vals:
            vals.insert(0, cur)
        w = self.winfo_width()
        h = len(vals) * self.ROW_H + 12
        x = self.winfo_rootx() - top.winfo_rootx()
        y = self.winfo_rooty() - top.winfo_rooty() + self.winfo_height() + 6
        pop = tk.Canvas(top, bg=BG, highlightthickness=0, bd=0, cursor=HAND)
        pop.place(x=x, y=y, width=w, height=h)
        tk.Misc.lift(pop)       # (Canvas.lift would raise canvas items, not the widget)
        self._pop, self._hover, self._vals = pop, None, vals
        self._paint_menu()
        pop.bind("<Motion>", self._menu_motion)
        pop.bind("<Leave>", lambda e: self._set_hover(None))
        pop.bind("<ButtonRelease-1>", self._menu_pick)
        self._bind_id = top.bind("<Button-1>", self._outside, add="+")
        self._esc_id = top.bind("<Escape>", lambda e: self.close(), add="+")
        self._draw()

    def _paint_menu(self):
        pop = self._pop
        pop.delete("all")
        w, h = int(pop.place_info()["width"]), int(pop.place_info()["height"])
        rrect(pop, 1, 1, w - 1, h - 1, R_CTRL, fill=SURFACE, outline=GOLD, width=1)
        for i, v in enumerate(self._vals):
            y0 = 6 + i * self.ROW_H
            if i == self._hover:
                rrect(pop, 6, y0 + 2, w - 6, y0 + self.ROW_H - 2, 8, fill=GOLD_TINT, outline="")
            sel = v == self.var.get()
            pop.create_text(18, y0 + self.ROW_H / 2, anchor="w", text=v, fill=GOLD if sel else TEXT,
                            font=font(13, "bold" if sel else "normal"))
            if sel:
                pop.create_text(w - 20, y0 + self.ROW_H / 2, text="✓", fill=GOLD, font=font(13, "bold"))

    def _row_at(self, y):
        i = int((y - 6) // self.ROW_H)
        return i if 0 <= i < len(self._vals) else None

    def _menu_motion(self, e):
        self._set_hover(self._row_at(e.y))

    def _set_hover(self, i):
        if self._pop and i != self._hover:
            self._hover = i
            self._paint_menu()

    def _menu_pick(self, e):
        i = self._row_at(e.y)
        if i is None:
            return
        value = self._vals[i]
        self.close()
        self.var.set(value)
        if self.on_change:
            self.on_change(value)

    def _outside(self, e):
        if e.widget is self._pop or e.widget is self:
            return
        self.close()

    def close(self):
        if not self._pop:
            return
        top = self.winfo_toplevel()
        for seq, ident in (("<Button-1>", self._bind_id), ("<Escape>", self._esc_id)):
            if ident:
                try:
                    top.unbind(seq, ident)
                except tk.TclError:
                    pass
        self._pop.destroy()
        self._pop = None
        self._draw()


# ---------- slider ----------
class GoldSlider(tk.Canvas):
    """Gold track, rounded thumb. Values step in `step` increments between from_ and to."""

    def __init__(self, parent, variable, from_=0.1, to=1.0, step=0.01, command=None, release_command=None,
                 height=34, bg=CARD):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0, cursor=HAND,
                         takefocus=1)
        self.var, self.lo, self.hi, self.step = variable, from_, to, step
        self.command, self.release_command = command, release_command
        self._r, self._focused, self._dragging = 9.0, False, False
        self.pad = 16
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._up)
        self.bind("<Enter>", lambda e: tween(self, "r", self._r, 11.0, self._set_r, ms=100, steps=4))
        self.bind("<Leave>", lambda e: (not self._dragging) and tween(self, "r", self._r, 9.0, self._set_r, ms=100, steps=4))
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Left>", lambda e: self._nudge(-1, e))
        self.bind("<Right>", lambda e: self._nudge(1, e))
        self.bind("<Down>", lambda e: self._nudge(-1, e))
        self.bind("<Up>", lambda e: self._nudge(1, e))
        self.var.trace_add("write", lambda *a: self._draw())

    def _set_r(self, r):
        self._r = r
        self._draw()

    def _focus(self, on):
        self._focused = on
        self._draw()

    def _clamp(self, v):
        v = round((v - self.lo) / self.step) * self.step + self.lo
        return round(min(self.hi, max(self.lo, v)), 4)

    def _x(self, v, w):
        return self.pad + (v - self.lo) / (self.hi - self.lo) * (w - 2 * self.pad)

    def _value_at(self, x):
        w, _ = _size(self)
        frac = (x - self.pad) / max(1, (w - 2 * self.pad))
        return self._clamp(self.lo + frac * (self.hi - self.lo))

    def _draw(self):
        self.delete("all")
        w, h = _size(self)
        cy = h / 2
        try:
            v = float(self.var.get())
        except (tk.TclError, ValueError):
            v = self.hi
        v = min(self.hi, max(self.lo, v))
        x = self._x(v, w)
        rrect(self, self.pad, cy - 3.5, w - self.pad, cy + 3.5, 3.5, fill=SURFACE, outline=BORDER, width=1)
        if x > self.pad + 2:
            rrect(self, self.pad, cy - 3.5, x, cy + 3.5, 3.5, fill=GOLD, outline="")
        r = self._r
        self.create_oval(x - r - 4, cy - r - 4, x + r + 4, cy + r + 4, fill=GOLD_TINT if self._focused else "",
                         outline="")
        self.create_oval(x - r, cy - r, x + r, cy + r, fill=GOLD_HOVER if self._r > 9.5 else GOLD, outline=BG, width=3)

    def _apply(self, v):
        v = self._clamp(v)
        if abs(v - float(self.var.get())) > 1e-9:
            self.var.set(v)
            if self.command:
                self.command(v)

    def _down(self, e):
        self.focus_set()
        self._dragging = True
        self._apply(self._value_at(e.x))

    def _move(self, e):
        if self._dragging:
            self._apply(self._value_at(e.x))

    def _up(self, e):
        self._dragging = False
        if self.release_command:
            self.release_command(float(self.var.get()))

    def _nudge(self, direction, e):
        mult = 10 if (e.state & 0x1) else 1
        self._apply(float(self.var.get()) + direction * self.step * mult)
        if self.release_command:
            self.release_command(float(self.var.get()))
        return "break"


# ---------- switch ----------
class GoldSwitch(tk.Canvas):
    W, H = 48, 28

    def __init__(self, parent, variable, command=None, bg=CARD):
        super().__init__(parent, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0, cursor=HAND,
                         takefocus=1)
        self.var, self.command = variable, command
        self._t = 1.0 if variable.get() else 0.0
        self.bind("<ButtonRelease-1>", lambda e: self.toggle())
        self.bind("<space>", lambda e: self.toggle())
        self.var.trace_add("write", lambda *a: self._sync())
        self._draw()

    def _draw(self):
        self.delete("all")
        track = lerp(SURFACE, GOLD, self._t)
        rrect(self, 1, 1, self.W - 1, self.H - 1, self.H / 2, fill=track, outline=lerp(BORDER, GOLD, self._t), width=1)
        x = 4 + self._t * (self.W - self.H)
        self.create_oval(x + 1, 5, x + self.H - 9, self.H - 5, fill=lerp(TEXT2, ON_GOLD, self._t), outline="")

    def _set_t(self, t):
        self._t = t
        self._draw()

    def _sync(self):
        tween(self, "t", self._t, 1.0 if self.var.get() else 0.0, self._set_t, ms=140, steps=7)

    def toggle(self):
        self.var.set(not self.var.get())
        if self.command:
            self.command(self.var.get())


# ---------- status / header ----------
class StatusDot(tk.Canvas):
    def __init__(self, parent, size=12, bg=CARD, color=TEXT2):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size = size
        self.set_color(color)

    def set_color(self, color):
        self.delete("all")
        s = self.size
        self.create_oval(1, 1, s - 1, s - 1, fill=color, outline="")
        self.color = color


class IconBadge(tk.Canvas):
    """The Cursor AI icon: a gold rounded square with a dark pointer."""

    def __init__(self, parent, size=48, bg=BG):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        s = size
        rrect(self, 1, 1, s - 1, s - 1, s * 0.28, fill=GOLD, outline=GOLD_HOVER, width=1)
        k = s / 48.0
        pts = [(15, 11), (15, 34), (21, 28.5), (25.5, 38), (30, 36), (25.5, 27), (33.5, 27)]
        self.create_polygon([c for p in pts for c in (p[0] * k, p[1] * k)], fill=ON_GOLD, outline=ON_GOLD,
                            width=1, joinstyle="round")
        for (cx, cy, r) in ((35, 14, 2.4), (39.5, 20, 1.5)):          # little sparkles
            self.create_oval((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k, fill=ON_GOLD, outline="")


# ---------- keyboard shortcut tile ----------
class ShortcutButton(tk.Canvas):
    """Click to listen, press the combination; shows macOS symbols (⌃ ⇧ ⌥ ⌘).

    conflict(combo) -> name of the shortcut already using it (or None). on_message(text, kind).
    on_listen(True/False) lets the app pause its global hotkeys while a key is being recorded.
    """

    def __init__(self, parent, var, title, conflict=None, on_message=None, on_listen=None, bg=CARD, height=72,
                 compact=False):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0, cursor=HAND,
                         takefocus=1)
        self.var, self.title, self.conflict = var, title, conflict
        self.on_message, self.on_listen = on_message, on_listen
        self.listening = False
        self.compact = compact
        self._fill, self._border = SURFACE, BORDER
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: (not self.listening) and tween(self, "f", self._fill, SURFACE_HOVER, self._recolor))
        self.bind("<Leave>", lambda e: (not self.listening) and tween(self, "f", self._fill, SURFACE, self._recolor))
        self.bind("<ButtonRelease-1>", lambda e: self.begin() if not self.listening else None)
        self.bind("<KeyPress>", self._key)
        self.bind("<FocusOut>", lambda e: self.stop())
        self.var.trace_add("write", lambda *a: self._draw())

    def _recolor(self, c):
        self._fill = c
        try:
            self.itemconfigure(self._box, fill=c)
        except tk.TclError:
            pass

    def _draw(self):
        self.delete("all")
        w, h = _size(self)
        self._box = rrect(self, 1, 1, w - 1, h - 1, R_CTRL, fill=self._fill,
                          outline=GOLD if self.listening else BORDER, width=1)
        if self.compact:
            if self.listening:
                self.create_text(w / 2, h / 2, text="Press shortcut…", fill=GOLD, font=font(12, "bold"))
            else:
                self.create_text(w / 2, h / 2, text=hotkey_recorder.symbols(self.var.get(), PLATFORM), fill=TEXT,
                                 font=font(14, "bold"))
            return
        self.create_text(16, h * 0.30, anchor="w", text=self.title, fill=TEXT2, font=font(11))
        if self.listening:
            self.create_text(16, h * 0.68, anchor="w", text="Press shortcut…", fill=GOLD, font=font(16, "bold"))
            self.create_text(w - 14, h * 0.30, anchor="e", text="esc to cancel", fill=TEXT2, font=font(10))
        else:
            self.create_text(16, h * 0.68, anchor="w", text=hotkey_recorder.symbols(self.var.get(), PLATFORM),
                             fill=TEXT, font=font(18, "bold"))

    def begin(self):
        self.listening = True
        self._fill = GOLD_TINT
        if self.on_listen:
            self.on_listen(True)
        self.focus_force()
        self._draw()

    def stop(self):
        if not self.listening:
            return
        self.listening = False
        self._fill = SURFACE
        if self.on_listen:
            self.on_listen(False)
        self._draw()

    def _say(self, text, kind="error"):
        if self.on_message:
            self.on_message(text, kind)

    def _key(self, e):
        if not self.listening:
            return None
        if e.keysym == "Escape":
            self.stop()
            return "break"
        try:
            combo = hotkey_recorder.combo_from_event(e.keysym, e.keycode, e.state, PLATFORM)
        except ValueError as err:
            self._say(str(err))
            return "break"
        if combo is None:        # a bare modifier: keep waiting for the real key
            return "break"
        other = self.conflict(combo) if self.conflict else None
        if other and other != self.title:
            self._say(f"{hotkey_recorder.symbols(combo, PLATFORM)} is already used by “{other}”. Pick another.")
            return "break"
        self.var.set(combo)
        self.stop()
        self._say(f"{self.title}: {hotkey_recorder.symbols(combo, PLATFORM)} (press Save Settings to keep it)", "info")
        return "break"


# ---------- progress bar ----------
class GoldProgress(tk.Canvas):
    def __init__(self, parent, height=8, bg=CARD):
        super().__init__(parent, height=height, width=120, bg=bg, highlightthickness=0, bd=0)
        self.value = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, fraction):
        self.value = min(1.0, max(0.0, float(fraction)))
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = _size(self)
        rrect(self, 0, 0, w, h, h / 2, fill=SURFACE, outline=BORDER, width=1)
        if self.value > 0:
            rrect(self, 0, 0, max(h, w * self.value), h, h / 2, fill=GOLD, outline="")
