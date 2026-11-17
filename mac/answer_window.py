"""Small borderless always-on-top answer window: drag to move, corner grip to resize,
Aa flips white/black text, x closes."""
import sys
import tkinter as tk

import settings_store as ss

TITLE = "CursorAI-Answer"


class AnswerWindow:
    def __init__(self, root, dark_text=False, on_color_change=None, opacity=1.0, always_on_top=True):
        self.root = root
        self.dark_text = dark_text
        self.on_color_change = on_color_change
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title(TITLE)
        self.win.overrideredirect(True)
        try:  # macOS: don't let showing this window activate the app / raise the settings window
            self.win.tk.call("::tk::unsupported::MacWindowStyle", "style", self.win._w, "plain", "noActivates")
        except tk.TclError:
            pass
        self.always_on_top = bool(always_on_top)
        self.win.attributes("-topmost", self.always_on_top)
        # macOS: fully transparent window background, so only the text is drawn.
        self.transparent = False
        if sys.platform == "darwin":
            try:
                self.win.attributes("-transparent", True)
                self.transparent = True
            except tk.TclError:
                pass
        self.opacity = 1.0
        self.set_opacity(opacity)
        self.win.geometry("420x140+80+80")
        self.win.minsize(160, 60)

        self.bar = tk.Frame(self.win, height=18, cursor="fleur")
        self.drag_hint = tk.Label(self.bar, text="⠿", padx=6, cursor="fleur")
        self.drag_hint.pack(side="left")
        self.bar.pack(fill="x", side="top")
        self.close_btn = tk.Label(self.bar, text="×", padx=6, cursor="hand2")
        self.close_btn.pack(side="right")
        self.color_btn = tk.Label(self.bar, text="Aa", padx=6, cursor="hand2")
        self.color_btn.pack(side="right")
        self.text = tk.Label(self.win, text="", justify="left", anchor="nw", wraplength=400,
                             font=("Helvetica", 15, "bold"), padx=8, pady=4)
        self.text.pack(fill="both", expand=True)
        self.grip = tk.Label(self.win, text="◢", cursor="bottom_right_corner")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

        for w in (self.bar, self.drag_hint):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.close_btn.bind("<Button-1>", lambda e: self.hide())
        self.color_btn.bind("<Button-1>", lambda e: self.flip_color())
        self.win.bind("<Configure>", lambda e: self.text.configure(wraplength=max(60, self.win.winfo_width() - 24)))
        self._apply_colors()
        self._keepalive()

    def set_opacity(self, value):
        """Whole-popup opacity (text included), 0.10 .. 1.0."""
        self.opacity = ss.clamp_opacity(value, fallback=1.0)
        try:
            self.win.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def set_always_on_top(self, flag):
        self.always_on_top = bool(flag)
        try:
            self.win.attributes("-topmost", self.always_on_top)
        except tk.TclError:
            pass
        self._pin_mac()

    def _apply_colors(self):
        fg = "#000000" if self.dark_text else "#ffffff"
        if self.transparent:
            bg = "systemTransparent"
        else:
            bg = "#e8e8e8" if self.dark_text else "#1c1c1e"
        for w in (self.win, self.bar, self.text, self.close_btn, self.color_btn, self.grip, self.drag_hint):
            w.configure(bg=bg)
        for w in (self.text, self.close_btn, self.color_btn, self.grip, self.drag_hint):
            w.configure(fg=fg)

    def flip_color(self):
        self.dark_text = not self.dark_text
        self._apply_colors()
        if self.on_color_change:
            self.on_color_change(self.dark_text)

    def _pin_mac(self):
        """macOS: float above everything, on every Space and over full-screen apps, and
        don't hide when the app loses focus."""
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp
            for w in NSApp.windows():
                if str(w.title()) == TITLE:
                    w.setLevel_(25 if self.always_on_top else 0)   # NSStatusWindowLevel / normal
                    w.setCollectionBehavior_(1 | 16 | 64 | 256)  # all Spaces, stationary, ignores cycle, full-screen aux
                    w.setHidesOnDeactivate_(False)
        except Exception:
            pass

    def _keepalive(self):
        """Re-assert 'always on top' every second while the popup is visible."""
        try:
            if self.is_visible() and self.always_on_top:
                self.win.attributes("-topmost", True)
                self.win.lift()
                self._pin_mac()
            self.win.after(1000, self._keepalive)
        except tk.TclError:
            pass  # window destroyed

    def show(self, message):
        self.text.configure(text=message)
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", self.always_on_top)
        self.set_opacity(self.opacity)   # some window systems drop alpha set while hidden
        self.win.update_idletasks()
        self._pin_mac()

    def hide(self):
        self.win.withdraw()

    def toggle(self):
        if self.win.state() == "withdrawn":
            self.win.deiconify()
            self.win.lift()
            self.set_opacity(self.opacity)
            self.win.update_idletasks()
            self._pin_mac()
        else:
            self.hide()

    def is_visible(self):
        return self.win.state() != "withdrawn"

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y()

    def _drag_move(self, e):
        self.win.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _resize_start(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rw, self._rh = self.win.winfo_width(), self.win.winfo_height()

    def _resize_move(self, e):
        w = max(160, self._rw + e.x_root - self._rx)
        h = max(60, self._rh + e.y_root - self._ry)
        self.win.geometry(f"{w}x{h}")
