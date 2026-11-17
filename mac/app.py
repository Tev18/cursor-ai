"""Cursor AI - menu-less Mac app. Paste your Claude API key, press the hotkey (or the
button), click twice on screen to box a region, get the answer in a small floating window.

The settings window is drawn with ui_kit (rounded black-and-gold canvas widgets)."""
import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox

import access
import answer_window
import capture
import claude_client
import hotkeys
import permissions
import selector
import settings_store as ss
import ui_kit as ui
import updater
import version

SHORTCUTS = (("Capture Screenshot", "cap_var"), ("Show/Hide Popup", "tog_var"), ("Change Text Color", "col_var"))


class App:
    def __init__(self, root, store=None, access_obj=None):
        self.root = root
        self.store = store or ss.SettingsStore()
        self.cfg = self.store.load()
        self.q = queue.Queue()
        self._busy = False
        self._testing = False
        self._sel = None
        self._preview_id = None
        self._quiet_until = 0.0   # ignore system 'reopen' pokes right after a selection ends
        self.hk = hotkeys.HotkeyManager()
        root.title("Cursor AI")
        root.configure(bg=ui.BG)
        root.minsize(560, 480)
        self.answer = answer_window.AnswerWindow(root, self.cfg["dark_text"], self._save_color, self.cfg["opacity"],
                                                 self.cfg["always_on_top"], self.cfg["popup_scale"])
        self._upd_info = None
        self._upd_busy = False
        self.access = access_obj or access.Access(directory=self.store.dir)
        self._build()
        self._fit_window()
        self._load_key_field()
        self._refresh_permission()
        self._awake = hotkeys.keep_awake()  # keep reference: stops App Nap delaying hotkeys
        self.apply_hotkeys(initial=True)
        root.after(100, self._pump)
        root.after(2500, self._access_tick)
        root.after(6000, self._report_tick)   # heartbeat to the owner's dashboard, once a minute
        if self.cfg["auto_update_check"] and updater.configured() and updater.should_auto_check(self.cfg["update_last_check"]):
            root.after(4000, lambda: self.check_updates(silent=True))
        # Closing the window only hides it: the app keeps running so the hotkeys keep working.
        # Click the Dock icon to bring the settings back; Cmd+Q quits.
        root.protocol("WM_DELETE_WINDOW", self.hide_main)
        try:
            root.createcommand("::tk::mac::ReopenApplication", self._on_reopen)
        except tk.TclError:
            pass

    # `busy` also greys out the Capture now button, so it can't be started twice.
    @property
    def busy(self):
        return self._busy

    @busy.setter
    def busy(self, flag):
        self._busy = bool(flag)
        btn = getattr(self, "capture_btn", None)
        if btn is not None:
            btn.set_enabled(not self._busy)

    # ---------- UI ----------
    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # header
        head = tk.Frame(root, bg=ui.BG)
        head.grid(row=0, column=0, sticky="ew", padx=30, pady=(14, 8))
        self._head = head
        ui.IconBadge(head, 42, bg=ui.BG).pack(side="left")
        titles = tk.Frame(head, bg=ui.BG)
        titles.pack(side="left", padx=(14, 0))
        ui.label(titles, "Cursor AI", 20, "bold", bg=ui.BG).pack(anchor="w")
        ui.label(titles, "Personalize your AI assistant.", 12, fg=ui.TEXT2, bg=ui.BG).pack(anchor="w")

        # scrolling body
        self.scroll = ui.ScrollFrame(root)
        self.scroll.grid(row=1, column=0, sticky="nsew")
        body = self.scroll.inner
        body.columnconfigure(0, weight=1)
        for r, build in enumerate((self._build_ai, self._build_prompt, self._build_shortcuts,
                                   self._build_appearance, self._build_updates, self._build_access, self._build_permissions)):
            build(body).grid(row=r, column=0, sticky="ew", pady=(0, 8))

        # footer
        ui.divider(root).grid(row=2, column=0, sticky="ew")
        foot = tk.Frame(root, bg=ui.BG)
        foot.grid(row=3, column=0, sticky="ew", padx=30, pady=10)
        self._foot = foot
        root.bind("<Configure>", self._align_bars, add="+")
        foot.columnconfigure(0, weight=1)
        left = tk.Frame(foot, bg=ui.BG)
        left.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        self.status_dot = ui.StatusDot(left, 10, bg=ui.BG)
        self.status_dot.pack(side="left", anchor="n", pady=4)
        self.status = ui.label(left, "", 12, fg=ui.TEXT2, bg=ui.BG)
        self.status.pack(side="left", padx=(8, 0), fill="x", expand=True)
        left.bind("<Configure>", lambda e: self.status.configure(wraplength=max(120, e.width - 30)))
        self.cancel_btn = ui.RoundButton(foot, "Cancel", self.cancel, "secondary", bg=ui.BG, min_width=90, height=34, size=12)
        self.cancel_btn.grid(row=0, column=1, padx=(0, 10))
        self.save_btn = ui.RoundButton(foot, "Save Settings", self.save_settings, "primary", bg=ui.BG, min_width=140, height=34, size=12)
        self.save_btn.grid(row=0, column=2)

        # the dropdown overlay should close when the page scrolls
        root.bind_all("<MouseWheel>", lambda e: self.model_dd.close(), add="+")
        # permission status can change while the app is open: re-check when the window is focused again
        root.bind("<FocusIn>", lambda e: self._refresh_permission() if e.widget is root else None, add="+")

    def _fit_window(self):
        """Open at the size that shows every card without scrolling (capped to the screen)."""
        r = self.root
        r.update_idletasks()
        need = (self._head.winfo_reqheight() + 48 + self.scroll.inner.winfo_reqheight() + self.scroll.pad
                + self._foot.winfo_reqheight() + 21)
        h = min(need, max(480, r.winfo_screenheight() - 70))
        r.geometry(f"760x{h}")

    def _align_bars(self, e):
        """Keep header and footer lined up with the centred content column on wide windows."""
        if e.widget is not self.root:
            return
        pad = max(30, (e.width - self.scroll.max_width) // 2 + 6)
        for bar in (self._head, self._foot):
            bar.grid_configure(padx=pad)

    def _build_ai(self, parent):
        card = ui.Card(parent, "AI Configuration")
        srow = tk.Frame(card.right, bg=ui.CARD)
        srow.pack()
        self.key_dot = ui.StatusDot(srow, 9)
        self.key_dot.pack(side="left")
        self.key_status = ui.label(srow, "", 11, fg=ui.TEXT2)
        self.key_status.pack(side="left", padx=(6, 0))
        c = card.content
        krow = tk.Frame(c, bg=ui.CARD)
        krow.grid(row=0, column=0, sticky="ew")
        krow.columnconfigure(0, weight=1)
        self.key_var = tk.StringVar()
        self.key_field = ui.RoundEntry(krow, self.key_var, show="•", mono=True, size=12, height=38)
        self.key_field.grid(row=0, column=0, sticky="ew")
        self.key_entry = self.key_field.entry
        self.show_var = tk.BooleanVar(value=False)
        self.show_btn = ui.RoundButton(krow, "Show", self._toggle_show, "secondary", height=38, min_width=76, size=12)
        self.show_btn.grid(row=0, column=1, padx=(8, 0))

        brow = tk.Frame(c, bg=ui.CARD)
        brow.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.save_key_btn = ui.RoundButton(brow, "Save Key", self.save_key, "primary", height=34, size=12)
        self.save_key_btn.pack(side="left")
        self.test_btn = ui.RoundButton(brow, "Test Connection", self.test_key, "secondary", height=34, size=12, min_width=140)
        self.test_btn.pack(side="left", padx=8)
        self.remove_btn = ui.RoundButton(brow, "Remove Key", self.remove_key, "danger", height=34, size=12)
        self.remove_btn.pack(side="left")

        ui.divider(c).grid(row=2, column=0, sticky="ew", pady=10)
        mrow = tk.Frame(c, bg=ui.CARD)
        mrow.grid(row=3, column=0, sticky="ew")
        mrow.columnconfigure(1, weight=1)
        ui.label(mrow, "AI Model", 13, "bold").grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.model_var = tk.StringVar(value=self.cfg["model"])
        self.model_dd = ui.RoundDropdown(mrow, self.model_var, ss.MODELS, height=38)
        self.model_dd.grid(row=0, column=1, sticky="ew")
        return card

    def _build_prompt(self, parent):
        card = ui.Card(parent, "Prompt & Behavior")
        self.instr_box = ui.RoundText(card.content, height=72, size=12)
        self.instr_box.grid(row=0, column=0, sticky="ew")
        self.instr = self.instr_box.text
        self.instr.insert("1.0", self.cfg["instruction"])
        self.instr.edit_reset()
        return card

    def _build_shortcuts(self, parent):
        card = ui.Card(parent, "Keyboard Shortcuts")
        self.capture_btn = ui.RoundButton(card.right, "Capture now", self.start_capture, "secondary", height=28, size=11, pad=14)
        self.capture_btn.pack()
        self.sc_wrap = tk.Frame(card.content, bg=ui.CARD)
        self.sc_wrap.grid(row=0, column=0, sticky="ew")
        self.sc_wrap.columnconfigure(0, weight=1)
        cfgkey = {"cap_var": "capture_hotkey", "tog_var": "toggle_hotkey", "col_var": "color_hotkey"}
        self.tiles = []
        for r, (title, attr) in enumerate(SHORTCUTS):
            var = tk.StringVar(value=self.cfg[cfgkey[attr]])
            setattr(self, attr, var)
            ui.label(self.sc_wrap, title, 13).grid(row=r, column=0, sticky="w", pady=3)
            t = ui.ShortcutButton(self.sc_wrap, var, title, conflict=self._conflict, on_message=self._set_status,
                                  on_listen=self._listening, height=34, compact=True)
            t.configure(width=170)
            t.grid(row=r, column=1, sticky="e", pady=3)
            self.tiles.append(t)
        return card

    def _build_appearance(self, parent):
        card = ui.Card(parent, "Appearance")
        c = card.content
        top = tk.Frame(c, bg=ui.CARD)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ui.label(top, "Popup Opacity", 13).grid(row=0, column=0, sticky="w")
        self.op_label = ui.label(top, f"{round(self.cfg['opacity'] * 100)}%", 13, "bold", fg=ui.GOLD)
        self.op_label.grid(row=0, column=1, sticky="e")
        self.op_var = tk.DoubleVar(value=self.cfg["opacity"])
        self.op_scale = ui.GoldSlider(c, self.op_var, from_=ss.OPACITY_MIN, to=ss.OPACITY_MAX, step=0.01, height=28,
                                      command=self._opacity_changed, release_command=lambda v: self._opacity_released())
        self.op_scale.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        rng = tk.Frame(c, bg=ui.CARD)
        rng.grid(row=2, column=0, sticky="ew")
        ui.label(rng, "10%", 10, fg=ui.TEXT2).pack(side="left", padx=(8, 0))
        ui.label(rng, "100%", 10, fg=ui.TEXT2).pack(side="right", padx=(0, 8))

        ui.divider(c).grid(row=3, column=0, sticky="ew", pady=8)
        stop = tk.Frame(c, bg=ui.CARD)
        stop.grid(row=4, column=0, sticky="ew")
        stop.columnconfigure(0, weight=1)
        ui.label(stop, "Popup Size", 13).grid(row=0, column=0, sticky="w")
        self.sc_label = ui.label(stop, f"{round(self.cfg['popup_scale'] * 100)}%", 13, "bold", fg=ui.GOLD)
        self.sc_label.grid(row=0, column=1, sticky="e")
        self.sc_var = tk.DoubleVar(value=self.cfg["popup_scale"])
        self.sc_scale = ui.GoldSlider(c, self.sc_var, from_=ss.SCALE_MIN, to=ss.SCALE_MAX, step=0.05, height=28,
                                      command=self._scale_changed, release_command=lambda v: self._scale_released())
        self.sc_scale.grid(row=5, column=0, sticky="ew", pady=(2, 0))
        srng = tk.Frame(c, bg=ui.CARD)
        srng.grid(row=6, column=0, sticky="ew")
        ui.label(srng, "50%", 10, fg=ui.TEXT2).pack(side="left", padx=(8, 0))
        ui.label(srng, "150%", 10, fg=ui.TEXT2).pack(side="right", padx=(0, 8))

        ui.divider(c).grid(row=7, column=0, sticky="ew", pady=8)
        row = tk.Frame(c, bg=ui.CARD)
        row.grid(row=8, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        txt = tk.Frame(row, bg=ui.CARD)
        txt.grid(row=0, column=0, sticky="ew")
        ui.label(txt, "Always on Top", 13).pack(anchor="w")
        d = ui.label(txt, "Keep popup above other windows", 11, fg=ui.TEXT2)
        d.pack(anchor="w", fill="x")
        self.top_var = tk.BooleanVar(value=self.cfg["always_on_top"])
        self.top_switch = ui.GoldSwitch(row, self.top_var, command=self._top_changed)
        self.top_switch.grid(row=0, column=1, padx=(16, 0))
        return card

    def _build_updates(self, parent):
        card = ui.Card(parent, "Updates")
        srow = tk.Frame(card.right, bg=ui.CARD)
        srow.pack()
        self.upd_dot = ui.StatusDot(srow, 9)
        self.upd_dot.pack(side="left")
        self.upd_status = ui.label(srow, "Not checked yet", 11, fg=ui.TEXT2)
        self.upd_status.pack(side="left", padx=(6, 0))
        c = card.content
        vrow = tk.Frame(c, bg=ui.CARD)
        vrow.grid(row=0, column=0, sticky="ew")
        vrow.columnconfigure(1, weight=1)
        self.ver_installed = ui.label(vrow, f"Installed  v{version.VERSION}", 13)
        self.ver_installed.grid(row=0, column=0, sticky="w")
        self.ver_latest = ui.label(vrow, "Latest  —", 13, fg=ui.TEXT2)
        self.ver_latest.grid(row=0, column=1, sticky="e")
        brow = tk.Frame(c, bg=ui.CARD)
        brow.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.check_btn = ui.RoundButton(brow, "Check for Updates", self.check_updates, "secondary", height=34, size=12, min_width=150)
        self.check_btn.pack(side="left")
        self.install_btn = ui.RoundButton(brow, "Install Update", self.install_update, "primary", height=34, size=12, min_width=130)
        self.install_btn.pack(side="left", padx=8)
        self.install_btn.set_enabled(False)
        prow = tk.Frame(c, bg=ui.CARD)
        prow.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        prow.columnconfigure(0, weight=1)
        self.upd_bar = ui.GoldProgress(prow)
        self.upd_bar.grid(row=0, column=0, sticky="ew")
        self.upd_pct = ui.label(prow, "", 11, fg=ui.TEXT2, width=5)
        self.upd_pct.grid(row=0, column=1, padx=(8, 0))
        self.notes_box = ui.RoundText(c, height=70, size=11, mono=False)
        self.notes_box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.notes = self.notes_box.text
        self._set_notes("Release notes appear here after you check for updates.")
        arow = tk.Frame(c, bg=ui.CARD)
        arow.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        arow.columnconfigure(0, weight=1)
        ui.label(arow, "Check for updates automatically", 13).grid(row=0, column=0, sticky="w")
        self.auto_var = tk.BooleanVar(value=self.cfg["auto_update_check"])
        self.auto_switch = ui.GoldSwitch(arow, self.auto_var, command=lambda f: self.store.save({"auto_update_check": bool(f)}))
        self.auto_switch.grid(row=0, column=1)
        ui.divider(c).grid(row=5, column=0, sticky="ew", pady=10)
        ui.label(c, "GitHub token: only needed if the releases are in a private repository (read-only access is enough)",
                 11, fg=ui.TEXT2).grid(row=6, column=0, sticky="w")
        trow = tk.Frame(c, bg=ui.CARD)
        trow.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        trow.columnconfigure(0, weight=1)
        self.token_var = tk.StringVar()
        self.token_field = ui.RoundEntry(trow, self.token_var, show="•", mono=True, size=12, height=34)
        self.token_field.grid(row=0, column=0, sticky="ew")
        ui.RoundButton(trow, "Save", self.save_token, "secondary", height=34, size=12, min_width=64).grid(row=0, column=1, padx=(8, 0))
        ui.RoundButton(trow, "Clear", self.clear_token, "danger", height=34, size=12, min_width=64).grid(row=0, column=2, padx=(8, 0))
        return card

    def _build_access(self, parent):
        card = ui.Card(parent, "Device Access")
        srow = tk.Frame(card.right, bg=ui.CARD)
        srow.pack()
        self.acc_dot = ui.StatusDot(srow, 9)
        self.acc_dot.pack(side="left")
        self.acc_status = ui.label(srow, "Not checked yet", 11, fg=ui.TEXT2)
        self.acc_status.pack(side="left", padx=(6, 0))
        c = card.content
        intro = ui.label(c, "Whoever shares this app with you can switch your access on or off. Send them your Device ID.",
                         11, fg=ui.TEXT2)
        intro.grid(row=0, column=0, sticky="ew")
        ui.autowrap(intro)
        r1 = tk.Frame(c, bg=ui.CARD)
        r1.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        r1.columnconfigure(1, weight=1)
        ui.label(r1, "Device", 13, fg=ui.TEXT2).grid(row=0, column=0, sticky="w")
        self.acc_name = ui.label(r1, self.access.device_name, 13)
        self.acc_name.grid(row=0, column=1, sticky="e")
        r2 = tk.Frame(c, bg=ui.CARD)
        r2.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        r2.columnconfigure(1, weight=1)
        ui.label(r2, "Device ID", 13, fg=ui.TEXT2).grid(row=0, column=0, sticky="w")
        ui.label(r2, self.access.device_id, 13, "bold", fg=ui.GOLD).grid(row=0, column=1, sticky="e", padx=(0, 8))
        ui.RoundButton(r2, "Copy", self.copy_device_id, "secondary", height=30, size=12, min_width=64).grid(row=0, column=2)
        r3 = tk.Frame(c, bg=ui.CARD)
        r3.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        r3.columnconfigure(1, weight=1)
        ui.label(r3, "Your name", 13, fg=ui.TEXT2).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.dname_var = tk.StringVar(value=self.cfg["display_name"])
        self.dname_field = ui.RoundEntry(r3, self.dname_var, size=12, height=34)
        self.dname_field.grid(row=0, column=1, sticky="ew")
        ui.RoundButton(r3, "Save", self.save_display_name, "secondary", height=34, size=12, min_width=64).grid(row=0, column=2, padx=(8, 0))
        priv = ui.label(c, "To manage access, this app reports your name, device name, Device ID, system, app version, "
                           "how many captures you took and when you were last active. Screenshots, answers, prompts "
                           "and your API key are never sent.", 11, fg=ui.TEXT2)
        priv.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ui.autowrap(priv)
        brow = tk.Frame(c, bg=ui.CARD)
        brow.grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.acc_btn = ui.RoundButton(brow, "Check access", self.refresh_access, "secondary", height=34, size=12, min_width=120)
        self.acc_btn.pack(side="left")
        return card

    def copy_device_id(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("%s (%s)" % (self.access.device_id, self.access.device_name))
        self._set_status("Device ID copied. Send it to the person who shares the app.", "ok")

    def save_display_name(self):
        name = self.dname_var.get().strip()[:40]
        self.store.save({"display_name": name})
        self.cfg = self.store.load()
        self._set_status("Name saved." if name else "Name cleared.", "ok")
        self.report_now()

    def refresh_access(self):
        self._bg(self.access.refresh, "access")

    def report_now(self):
        """Heartbeat to the owner's dashboard (no-op if the owner has not set one up). Off the UI thread."""
        if self.access.server:
            self._bg(lambda: self.access.report(version.VERSION, "mac", self.cfg["display_name"]), "access")

    def _update_access_ui(self):
        a = self.access
        if a.state == "pending":
            self.acc_dot.set_color(ui.GOLD); self.acc_status.configure(text="Waiting for approval", fg=ui.TEXT)
        elif a.state == "blocked":
            self.acc_dot.set_color(ui.ERROR); self.acc_status.configure(text="Turned off", fg=ui.TEXT)
        elif a.state == "allowed":
            self.acc_dot.set_color(ui.SUCCESS)
            self.acc_status.configure(text="Allowed" if a.source == "online" else "Allowed (saved copy)", fg=ui.TEXT)
        else:
            self.acc_dot.set_color(ui.TEXT2); self.acc_status.configure(text="Not checked", fg=ui.TEXT2)

    def _access_tick(self):
        self.refresh_access()
        self.root.after(30 * 60 * 1000, self._access_tick)

    def _report_tick(self):
        self.report_now()
        self.root.after(access.REPORT_SECONDS * 1000, self._report_tick)

    def _build_permissions(self, parent):
        card = ui.Card(parent, "macOS Permissions")
        c = card.content
        row = tk.Frame(c, bg=ui.CARD)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        left = tk.Frame(row, bg=ui.CARD)
        left.grid(row=0, column=0, sticky="w")
        top = tk.Frame(left, bg=ui.CARD)
        top.pack(anchor="w")
        ui.label(top, "Screen Recording", 13).pack(side="left")
        self.perm_dot = ui.StatusDot(top, 9)
        self.perm_dot.pack(side="left", padx=(10, 0))
        self.perm_label = ui.label(top, "", 11, fg=ui.TEXT2)
        self.perm_label.pack(side="left", padx=(5, 0))
        ui.label(left, "Used to capture screenshots", 11, fg=ui.TEXT2).pack(anchor="w")
        self.perm_btn = ui.RoundButton(row, "Open Settings", self.open_screen_settings, "secondary", height=34, size=12)
        self.perm_btn.grid(row=0, column=1, padx=(12, 0))
        hint = ui.label(c, "If Cursor AI is already listed under Screen Recording, select it and remove it with the minus (−) "
                           "button first. Then click the plus (+) button, go to Applications, and select Cursor AI.",
                        11, fg=ui.TEXT2)
        hint.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ui.autowrap(hint)
        return card

    # ---------- window state ----------
    def _on_reopen(self):
        if time.time() >= self._quiet_until:   # a selection just ended: stay hidden, pop nothing
            self.show_main()

    def show_main(self):
        self._hide_key()                       # the key is always masked when the window comes back
        if not self.key_var.get():
            self._load_key_field()
        self.root.deiconify()
        self.root.lift()
        self._refresh_permission()

    def hide_main(self):
        """Hide the settings window. The saved key is dropped from the text field (it is read from the
        Keychain again on reopen), unless the user has typed a different key that isn't saved yet."""
        self._hide_key()
        if self.key_var.get() == (self.store.get_key() or ""):
            self.key_var.set("")
        self.root.withdraw()

    def _load_key_field(self):
        """Puts the saved key (from the Keychain) into the masked field. No placeholder text is ever used."""
        self.key_var.set(self.store.get_key() or "")
        self._hide_key()
        self._refresh_key_status()

    def _hide_key(self):
        self.show_var.set(False)
        self.key_field.set_hidden(True)
        self.show_btn.set_text("Show")

    def _toggle_show(self):
        self.show_var.set(not self.show_var.get())
        self.key_field.set_hidden(not self.show_var.get())
        self.show_btn.set_text("Hide" if self.show_var.get() else "Show")

    def _set_status(self, msg, kind="info"):
        color = {"ok": ui.SUCCESS, "error": ui.ERROR, "busy": ui.GOLD}.get(kind, ui.TEXT2)
        self.status.configure(text=msg, fg=ui.TEXT if kind != "info" else ui.TEXT2)
        self.status_dot.set_color(color)

    def _set_key_state(self, text, kind="idle"):
        color = {"ok": ui.SUCCESS, "error": ui.ERROR, "busy": ui.GOLD}.get(kind, ui.TEXT2)
        self.key_dot.set_color(color)
        self.key_status.configure(text=text, fg=ui.TEXT if kind != "idle" else ui.TEXT2)

    def _refresh_key_status(self):
        k = self.store.get_key()
        if k:
            self._set_key_state(f"Saved {ss.mask(k)}", "ok")
        else:
            self._set_key_state("No key saved yet.", "idle")

    def _refresh_permission(self):
        state = permissions.screen_recording_granted()
        if state is True:
            self.perm_dot.set_color(ui.SUCCESS)
            self.perm_label.configure(text="Granted", fg=ui.SUCCESS)
        elif state is False:
            self.perm_dot.set_color(ui.ERROR)
            self.perm_label.configure(text="Not granted", fg=ui.ERROR)
        else:
            self.perm_dot.set_color(ui.TEXT2)
            self.perm_label.configure(text="Status unavailable", fg=ui.TEXT2)

    def open_screen_settings(self):
        if permissions.open_screen_recording_settings():
            self.root.after(2000, self._refresh_permission)
        else:
            self._set_status("This button only works on macOS.")

    # ---------- key / settings ----------
    def save_key(self):
        k = self.key_var.get().strip()
        if not k:
            self._set_status("Paste your key first.", "error")
            return
        where = self.store.set_key(k)
        self.key_var.set(k)                    # stays in the (masked) field so you can see/replace it
        self._hide_key()
        self._refresh_key_status()
        self._set_status("Key saved in the macOS Keychain." if where == "keychain"
                         else "Key saved to a private file (Keychain unavailable).", "ok")

    def remove_key(self):
        self.store.delete_key()
        self.key_var.set("")
        self._refresh_key_status()
        self._set_status("Key removed.")

    def test_key(self):
        if self._testing:
            return
        k = self.key_var.get().strip() or self.store.get_key()
        if not k:
            self._set_status("No key to test.", "error")
            return
        self._testing = True
        self.test_btn.set_enabled(False)
        self.test_btn.set_text("Testing…")
        self._set_key_state("Testing connection…", "busy")
        self._set_status("Testing key…", "busy")
        model = self.model_var.get()
        self._bg(lambda: claude_client.test_key(k, model), "test")   # off the UI thread

    def _test_done(self):
        self._testing = False
        self.test_btn.set_text("Test Connection")
        self.test_btn.set_enabled(True)

    def _instruction(self):
        return self.instr.get("1.0", "end").strip() or ss.DEFAULTS["instruction"]

    def _conflict(self, combo):
        for title, attr in SHORTCUTS:
            if getattr(self, attr).get() == combo:
                return title
        return None

    def _listening(self, on):
        """While a shortcut is being recorded, release the global hotkeys so the key combo reaches us."""
        if on:
            self.hk.stop()
        else:
            self.apply_hotkeys(quiet=True)

    def save_settings(self):
        for label, var in (("Capture", self.cap_var), ("Show/hide", self.tog_var), ("Text color", self.col_var)):
            err = hotkeys.validate(var.get().strip())
            if err:
                self._set_status(f"{label} hotkey: {err}", "error")
                return
        combos = [v.get().strip() for v in (self.cap_var, self.tog_var, self.col_var)]
        if len(set(combos)) < 3:
            self._set_status("The three hotkeys must all be different.", "error")
            return
        self.store.save({"model": self.model_var.get().strip(), "instruction": self._instruction(),
                         "capture_hotkey": combos[0], "toggle_hotkey": combos[1], "color_hotkey": combos[2],
                         "opacity": round(self.answer.opacity, 2), "popup_scale": self.answer.scale, "always_on_top": bool(self.top_var.get())})
        self.cfg = self.store.load()
        self.apply_hotkeys(quiet=True)
        self._set_status("Settings saved ✓", "ok")
        self.save_btn.set_enabled(False)          # brief confirmation, and no double-clicks
        self.save_btn.set_text("Saved ✓")
        self.root.after(900, self._save_done)

    def _save_done(self):
        self.save_btn.set_text("Save Settings")
        self.save_btn.set_enabled(True)

    def cancel(self):
        """Throw away unsaved edits (model, prompt, shortcuts) and go back to what is saved."""
        for t in self.tiles:
            t.stop()
        self.cfg = self.store.load()
        self.model_var.set(self.cfg["model"])
        self.instr.delete("1.0", "end")
        self.instr.insert("1.0", self.cfg["instruction"])
        self.cap_var.set(self.cfg["capture_hotkey"])
        self.tog_var.set(self.cfg["toggle_hotkey"])
        self.col_var.set(self.cfg["color_hotkey"])
        self._load_key_field()
        self._set_status("Unsaved changes discarded.")

    def _opacity_changed(self, value):
        self.answer.set_opacity(float(value))
        self.op_label.configure(text=f"{round(self.answer.opacity * 100)}%")

    def _scale_changed(self, value):
        self.answer.set_scale(float(value))
        self.sc_label.configure(text=f"{round(self.answer.scale * 100)}%")

    def _scale_released(self):
        self.store.save({"popup_scale": self.answer.scale})

    def _opacity_released(self):
        self.store.save({"opacity": round(self.answer.opacity, 2)})
        # If the popup is hidden, flash a preview so the effect can be seen, then hide it again.
        if self._preview_id is None and self.answer.is_visible():
            return
        if self._preview_id is not None:
            self.root.after_cancel(self._preview_id)
        else:
            self.answer.show("Opacity preview")
        self._preview_id = self.root.after(2500, self._end_preview)

    def _end_preview(self):
        self._preview_id = None
        self.answer.hide()

    def _top_changed(self, flag):
        self.answer.set_always_on_top(flag)
        self.store.save({"always_on_top": bool(flag)})

    def _save_color(self, dark):
        self.store.save({"dark_text": dark})

    # ---------- updates ----------
    def _set_upd_status(self, text, kind="idle"):
        color = {"ok": ui.SUCCESS, "error": ui.ERROR, "busy": ui.GOLD, "new": ui.GOLD}.get(kind, ui.TEXT2)
        self.upd_dot.set_color(color)
        self.upd_status.configure(text=text, fg=ui.TEXT if kind != "idle" else ui.TEXT2)

    def _set_notes(self, text):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def _set_progress(self, fraction, label=""):
        self.upd_bar.set(fraction)
        self.upd_pct.configure(text=label)

    def save_token(self):
        t = self.token_var.get().strip()
        if not t:
            self._set_status("Paste a GitHub token first.", "error")
            return
        self.store.set_token(t)
        self.token_var.set("")
        self._set_status("GitHub token saved (Keychain).", "ok")

    def clear_token(self):
        self.store.delete_token()
        self.token_var.set("")
        self._set_status("GitHub token removed.")

    def check_updates(self, silent=False):
        if self._upd_busy:
            return
        self._upd_busy = True
        self._silent_check = silent
        self.check_btn.set_enabled(False)
        self.install_btn.set_enabled(False)
        self._set_progress(0)
        self._set_upd_status("Checking…", "busy")
        token = self.store.get_token()
        self._bg(lambda: updater.check_latest(token=token), "update_check")   # network call off the UI thread

    def install_update(self):
        info = self._upd_info
        if self._upd_busy or not info or not info.get("newer"):
            return
        target = updater.current_target()
        if target is None:
            self._set_upd_status("Install from the packaged app", "error")
            self._set_status("Updates can only be installed into the packaged app. Download v%s from %s" %
                             (info["version"], info.get("url") or "GitHub Releases"), "error")
            return
        if not info.get("asset") or not info.get("sums"):
            self._set_upd_status("No build for this system", "error")
            self._set_status("This release has no %s download with a checksum, so it can't be installed." %
                             updater.platform_key(), "error")
            return
        self._upd_busy = True
        self.check_btn.set_enabled(False)
        self.install_btn.set_enabled(False)
        self._set_upd_status("Downloading…", "busy")
        token = self.store.get_token()
        last = [0.0, -1]

        def progress(done, total):          # worker thread: only post to the queue, and not too often
            now = time.time()
            pct = int(done * 100 / total) if total else -1
            if pct != last[1] and (now - last[0] > 0.1 or done == total):
                last[0], last[1] = now, pct
                self.q.put(("update_progress", (done, total)))

        def job():
            tmp = tempfile.mkdtemp(prefix="cursor-ai-dl-")
            try:
                path = updater.download(info["asset"], tmp, token, progress)
                self.q.put(("update_verifying", None))
                sums = updater.fetch_text(info["sums"], token)
                updater.verify_sha256(path, sums, info["asset"]["name"])
                sig = updater.fetch_text(info["sig"], token) if info.get("sig") else None
                signed = updater.verify_signature(path, sig)
                staged = updater.stage(path, target)
                staged["signed"] = signed
                return staged
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        self._bg(job, "update_install")

    def _confirm(self, title, message):
        return messagebox.askokcancel(title, message, parent=self.root)

    def _finish_update(self, staged):
        info = self._upd_info
        lines = [f"Install Cursor AI {info['version']}?",
                 "",
                 "The app will quit, replace itself and reopen. Your settings and API key are kept.",
                 "",
                 "Checked: SHA-256 checksum ✓" + ("  ·  publisher signature ✓" if staged.get("signed")
                                                   else "  ·  (no publisher key in this build: integrity only)")]
        lines += [""] + staged.get("notes", [])
        if self._confirm("Install update", "\n".join(lines)):
            try:
                updater.install(staged)
            except Exception as e:
                updater.discard(staged)
                self._set_upd_status("Install failed", "error")
                self._set_status(f"Couldn't start the installer: {e}", "error")
                self._upd_done()
                return
            self._set_upd_status("Restarting…", "ok")
            self.root.after(500, self.quit)
        else:
            updater.discard(staged)
            self._set_upd_status("Update cancelled", "idle")
            self._set_progress(0)
            self._upd_done()

    def _upd_done(self):
        self._upd_busy = False
        self.check_btn.set_enabled(True)
        self.install_btn.set_enabled(bool(self._upd_info and self._upd_info.get("newer")))

    # ---------- hotkeys ----------
    def apply_hotkeys(self, initial=False, quiet=False):
        try:
            self.hk.start({
                self.cfg["capture_hotkey"]: lambda: self.q.put(("hotkey_capture", None)),
                self.cfg["toggle_hotkey"]: lambda: self.q.put(("hotkey_toggle", None)),
                self.cfg["color_hotkey"]: lambda: self.q.put(("hotkey_color", None)),
            })
            if self.hk.backend == "carbon" and not quiet:
                self._set_status("Shortcuts active in every app.", "ok")
            elif self.hk.backend == "nsevent":
                self._set_status("Shortcuts are using fallback mode (" + getattr(self.hk, "carbon_error", "unknown") + ").")
                # Only on failure (there is no permissions-card entry for this): tell the user how to recover.
                if hotkeys.input_monitoring_granted(request=initial) is False:
                    self._set_status("Shortcuts only work inside Cursor AI until macOS allows key monitoring: "
                                     "System Settings > Privacy & Security > Input Monitoring, enable Cursor AI, "
                                     "then reopen the app. Capture now works without it.", "error")
        except Exception as e:
            self._set_status(f"Shortcuts unavailable: {e}. You can still use the Capture now button.", "error")

    # ---------- capture flow ----------
    def start_capture(self):
        if self.busy:
            return
        if self.access.stale():
            self.refresh_access()
        if not self.access.allowed:
            self.answer.show(self.access.message)
            self._set_status(self.access.message, "error")
            return
        k = self.store.get_key()
        if not k:
            self._set_status("Save your API key first.", "error")
            self.show_main()
            return
        self.busy = True
        self.answer.hide()
        self.hide_main()  # only the answer popup should be visible from here on
        self.root.after(250, self._begin_selection)  # let our window finish disappearing

    def _begin_selection(self):
        try:
            shot = capture.grab_screen()
            self._quiet_until = time.time() + 2.0
            sel = selector.RegionSelector(self.root, shot, lambda box: self._selected(shot, box))
            if not getattr(sel, "done", True):   # still open (it can finish instantly in tests)
                self._sel = sel
                self.hk.add_escape(lambda: self.q.put(("sel_cancel", None)))
        except Exception as e:
            self.busy = False
            self.answer.show(str(e))
            self._set_status(str(e), "error")

    def _selected(self, shot, box):
        self.hk.remove_escape()
        self._sel = None
        self._quiet_until = time.time() + 2.0
        if box is None:
            self.busy = False   # cancelled: show nothing at all (no popup, no settings window)
            self._set_status("Capture cancelled.")
            return
        k = self.store.get_key()
        cfg = self.store.load()
        self.access.note_capture()
        self.report_now()
        self.answer.show("Thinking…")

        def job():
            png = capture.crop_and_downscale(shot, box)
            return claude_client.ask_about_image(k, png, cfg["model"], cfg["instruction"], cfg["max_tokens"])

        self._bg(job, "capture")

    def _bg(self, fn, kind):
        def run():
            try:
                self.q.put((kind + "_ok", fn()))
            except Exception as e:
                self.q.put((kind + "_err", str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                self._handle(kind, val)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _handle(self, kind, val):
        if kind == "hotkey_capture":
            self.start_capture()
        elif kind == "sel_cancel":
            if self._sel is not None:
                self._sel.cancel()
        elif kind == "hotkey_toggle":
            self.answer.toggle()
        elif kind == "hotkey_color":
            self.answer.flip_color()
        elif kind == "thinking":
            self.answer.show("Thinking…")
        elif kind == "capture_ok":
            self.busy = False
            if val is None:
                self._set_status("Capture cancelled.")
            else:
                self.answer.show(val)
        elif kind == "capture_err":
            self.busy = False
            self.answer.show(val)
            self._set_status(val, "error")
        elif kind in ("access_ok", "access_err"):
            self._update_access_ui()
            if not self.access.allowed:
                self._set_status(self.access.message, "error")
        elif kind == "update_check_ok":
            self._upd_info = val
            self.store.save({"update_last_check": int(time.time())})
            self.ver_latest.configure(text=f"Latest  v{val['version']}", fg=ui.TEXT)
            self._set_notes(val["notes"])
            if val["newer"]:
                self._set_upd_status(f"Update available: v{val['version']}", "new")
            else:
                self._set_upd_status("You're up to date.", "ok")
            self._upd_done()
        elif kind == "update_check_err":
            self._set_upd_status("Couldn't check for updates", "error")
            if not getattr(self, "_silent_check", False):
                self._set_status(val, "error")
            self._upd_done()
        elif kind == "update_progress":
            done, total = val
            frac = done / total if total else 0
            self._set_progress(frac, f"{int(frac * 100)}%" if total else "")
            self._set_upd_status("Downloading…", "busy")
        elif kind == "update_verifying":
            self._set_progress(1.0, "100%")
            self._set_upd_status("Verifying…", "busy")
        elif kind == "update_install_ok":
            self._set_upd_status("Verified: ready to install", "ok")
            self._finish_update(val)
        elif kind == "update_install_err":
            self._set_upd_status("Update failed", "error")
            self._set_progress(0)
            self._set_status(val, "error")
            self._upd_done()
        elif kind == "test_ok":
            self._test_done()
            self._set_key_state("Connected: key verified", "ok")
            self._set_status("Key works ✔", "ok")
        elif kind == "test_err":
            self._test_done()
            self._set_key_state("Connection failed", "error")
            self._set_status(f"Key test failed: {val}", "error")

    def quit(self):
        self.hk.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
