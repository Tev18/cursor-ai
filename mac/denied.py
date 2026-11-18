"""Full-screen "ACCESS DENIED" notice shown when a blocked device tries to use the app."""
import tkinter as tk

SHOW_MS = 3500


def show(root, message=""):
    """Dim the whole screen and put ACCESS DENIED in big red bold text in the middle.
    Closes by itself after a few seconds, or on click / any key."""
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.configure(bg="#000000")
    w, h = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+0+0")
    try:
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.88)
    except tk.TclError:
        pass
    box = tk.Frame(win, bg="#000000")
    box.place(relx=0.5, rely=0.5, anchor="center")
    size = max(48, min(140, w // 12))
    tk.Label(box, text="ACCESS DENIED", fg="#ff1e1e", bg="#000000",
             font=("Helvetica", size, "bold")).pack()
    if message:
        tk.Label(box, text=message, fg="#ffb3b3", bg="#000000", font=("Helvetica", 20),
                 wraplength=int(w * 0.7), justify="center").pack(pady=(24, 0))

    def close(_e=None):
        try:
            win.destroy()
        except tk.TclError:
            pass

    win.bind("<Button-1>", close)
    win.bind("<Key>", close)
    win.after(SHOW_MS, close)
    win.lift()
    try:
        win.focus_force()
    except tk.TclError:
        pass
    return win
