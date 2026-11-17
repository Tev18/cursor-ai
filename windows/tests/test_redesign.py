import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings_store as ss


class FakeKR:
    def __init__(self): self.d = {}
    def get_password(self, s, a): return self.d.get((s, a))
    def set_password(self, s, a, v): self.d[(s, a)] = v
    def delete_password(self, s, a): self.d.pop((s, a), None)


class Redesign(unittest.TestCase):
    def make_app(self, **saved):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR())
        if saved: store.save(saved)
        a = app.App(root, store); root.update()
        return root, a, store
    def all_text(self, w):
        out = []
        def walk(x):
            try: out.append(str(x.cget("text")))
            except Exception: pass
            if x.winfo_class() == "Canvas":
                for i in x.find_all():
                    try: out.append(str(x.itemcget(i, "text")))
                    except Exception: pass
            for c in x.winfo_children(): walk(c)
        walk(w); return " | ".join(out)
    def test_no_input_monitoring_anywhere_in_gui(self):
        root, a, _ = self.make_app(); txt = self.all_text(root)
        self.assertNotIn("Screen Recording", txt)
        for need in ("Cursor AI", "Personalize your AI assistant.", "AI Configuration", "Save Key", "Test Connection",
                     "Remove Key", "AI Model", "Prompt & Behavior", "Keyboard Shortcuts", "Capture Screenshot", "Show/Hide Popup",
                     "Change Text Color", "Appearance", "Popup Opacity", "Always on Top", "Updates", "Windows Notes", "Save Settings", "Cancel", "Quit"):
            self.assertIn(need.lower(), txt.lower(), need)
        a.hk.stop(); root.destroy()
    def test_palette_is_the_specified_one(self):
        import ui_kit as ui
        self.assertEqual((ui.BG, ui.CARD, ui.SURFACE, ui.GOLD, ui.GOLD_HOVER, ui.TEXT, ui.TEXT2, ui.BORDER, ui.SUCCESS),
                         ("#0D0D0F", "#191919", "#252525", "#D4AF37", "#EAC85C", "#F5F2EA", "#9E9A92", "#34302A", "#76DCA1"))
    def test_slider_10_to_100_in_1_percent_steps(self):
        root, a, store = self.make_app(); sl = a.op_scale; root.update(); w = sl.winfo_width()
        self.assertEqual(a.op_var.get(), 0.85); self.assertEqual(a.op_label.cget("text"), "85%")
        def drag_to(x):
            sl.event_generate("<ButtonPress-1>", x=x, y=15); sl.event_generate("<B1-Motion>", x=x, y=15)
            sl.event_generate("<ButtonRelease-1>", x=x, y=15); root.update()
        drag_to(0); self.assertEqual(a.answer.opacity, 0.1); self.assertEqual(a.op_label.cget("text"), "10%"); self.assertEqual(store.load()["opacity"], 0.1)
        drag_to(w + 50); self.assertEqual(a.answer.opacity, 1.0); self.assertEqual(a.op_label.cget("text"), "100%")
        drag_to(sl.pad + (w - 2 * sl.pad) // 2); self.assertTrue(0.54 <= a.answer.opacity <= 0.56)
        for v in range(10, 101):                                   # every whole percent is reachable and applied to the popup
            sl.var.set(v / 100); sl._apply(v / 100); a._opacity_changed(v / 100)
            self.assertEqual(round(a.answer.opacity * 100), v)
        sl.focus_set(); sl.var.set(0.5); sl.event_generate("<Right>"); self.assertAlmostEqual(sl.var.get(), 0.51, 2)
        sl.event_generate("<Left>"); sl.event_generate("<Left>"); self.assertAlmostEqual(sl.var.get(), 0.49, 2)
        a.answer.hide(); a.hk.stop(); root.destroy()
    def test_popup_not_settings_window_gets_opacity(self):
        root, a, _ = self.make_app(opacity=0.3); root.update()
        self.assertEqual(a.answer.opacity, 0.3)
        self.assertNotAlmostEqual(float(root.attributes("-alpha")), 0.3, 2)    # settings window untouched
        a.hk.stop(); root.destroy()
    def test_existing_saved_opacity_kept_and_out_of_range_clamped(self):
        for saved, want in ((0.2, 0.2), (0.6, 0.6), (0.01, 0.1), (3, 1.0)):
            root, a, _ = self.make_app(opacity=saved)
            self.assertEqual(a.answer.opacity, want); a.hk.stop(); root.destroy()
    def test_always_on_top_switch(self):
        root, a, store = self.make_app(); self.assertTrue(a.answer.always_on_top)
        a.top_switch.event_generate("<ButtonRelease-1>"); root.update()
        self.assertFalse(a.top_var.get()); self.assertFalse(a.answer.always_on_top); self.assertFalse(store.load()["always_on_top"])
        seen = []; real = a.answer.win.attributes     # (no window manager under xvfb, so record what we ask for)
        a.answer.win.attributes = lambda *x: seen.append(x) or real(*x)
        a.answer.show("x"); root.update(); self.assertIn(("-topmost", False), seen); self.assertNotIn(("-topmost", True), seen)
        a.top_switch.toggle(); self.assertTrue(a.answer.always_on_top); self.assertIn(("-topmost", True), seen)
        del a.answer.win.attributes
        a.answer.hide(); a.hk.stop(); root.destroy()
    def test_shortcut_tiles_record_block_conflicts_and_pause_hotkeys(self):
        root, a, _ = self.make_app(); t = a.tiles[0]; msgs = []; a._set_status = lambda m, k="info": msgs.append(m)
        t.on_message = a._set_status; stopped = []; a.hk.stop = lambda: stopped.append(1)
        t.begin(); root.update(); self.assertTrue(t.listening); self.assertEqual(stopped, [1])        # global keys released while listening
        t.event_generate("<KeyPress>", keysym="Shift_L", state=0x1); self.assertTrue(t.listening)       # bare modifier: keep waiting
        t.event_generate("<KeyPress>", keysym="x", state=0); self.assertTrue(t.listening)               # no modifier: refused
        t.event_generate("<KeyPress>", keysym="h", state=0x5); self.assertTrue(t.listening)             # = Show/Hide combo: conflict
        self.assertTrue(any("already used" in m for m in msgs)); self.assertEqual(a.cap_var.get(), "<ctrl>+<shift>+a")
        t.event_generate("<KeyPress>", keysym="bracketright", state=0x4); self.assertFalse(t.listening)
        self.assertEqual(a.cap_var.get(), "<ctrl>+]")
        t.begin(); t.event_generate("<KeyPress>", keysym="Escape"); self.assertFalse(t.listening); self.assertEqual(a.cap_var.get(), "<ctrl>+]")
        a.answer.hide(); root.destroy()
    def test_symbols(self):
        import hotkey_recorder as r
        self.assertEqual(r.symbols("<ctrl>+<shift>+a", "darwin"), "⌃ ⇧ A")
        self.assertEqual(r.symbols("<cmd>+<alt>+<shift>+<ctrl>+]", "darwin"), "⌃ ⌥ ⇧ ⌘ ]")
        self.assertEqual(r.symbols("<cmd>+space", "darwin"), "⌘ Space"); self.assertEqual(r.symbols("<ctrl>+a", "linux"), "Ctrl + A")
        self.assertEqual(r.symbols("", "darwin"), "Not set")
    def test_test_connection_is_async_and_disables_button(self):
        import time, app
        root, a, store = self.make_app(); store.set_key("k")
        gate = []; orig = app.claude_client.test_key
        self.addCleanup(lambda: setattr(app.claude_client, "test_key", orig))
        app.claude_client.test_key = lambda k, m: (time.sleep(0.4), "ok")[1]
        t0 = time.time(); a.test_key(); self.assertLess(time.time() - t0, 0.2)                 # returns at once (no UI blocking)
        self.assertFalse(a.test_btn.enabled); a.test_key()                                       # second click ignored
        for _ in range(30): root.update(); time.sleep(0.05)
        self.assertTrue(a.test_btn.enabled); self.assertIn("Connected", a.key_status.cget("text"))
        app.claude_client.test_key = lambda k, m: (_ for _ in ()).throw(RuntimeError("bad key"))
        a.test_key()
        for _ in range(30): root.update(); time.sleep(0.05)
        self.assertIn("failed", a.key_status.cget("text")); self.assertIn("bad key", a.status.cget("text")); self.assertTrue(a.test_btn.enabled)
        a.hk.stop(); root.destroy()
    def test_save_feedback_and_cancel(self):
        root, a, store = self.make_app()
        a.model_var.set("claude-opus-5-5"); a.instr.delete("1.0", "end"); a.instr.insert("1.0", "hello")
        a.cancel(); self.assertEqual(a.model_var.get(), "claude-sonnet-5-5"); self.assertNotEqual(a._instruction(), "hello")
        a.model_var.set("claude-opus-5-5"); a.instr.delete("1.0", "end"); a.instr.insert("1.0", "hello")
        a.save_btn.invoke(); self.assertIn("saved", a.status.cget("text")); self.assertFalse(a.save_btn.enabled)   # brief lock + feedback
        self.assertEqual(store.load()["model"], "claude-opus-5-5"); self.assertEqual(store.load()["instruction"], "hello")
        a.save_btn.invoke()                                                                                          # ignored while locked
        a._save_done(); self.assertTrue(a.save_btn.enabled); self.assertEqual(a.save_btn._text, "Save Settings")
        a.hk.stop(); root.destroy()
    def test_capture_button_follows_busy(self):
        root, a, _ = self.make_app(); self.assertTrue(a.capture_btn.enabled)
        a.busy = True; self.assertFalse(a.capture_btn.enabled); a.busy = False; self.assertTrue(a.capture_btn.enabled)
        a.hk.stop(); root.destroy()
    def test_show_hide_key_and_dropdown(self):
        root, a, _ = self.make_app()
        self.assertEqual(a.key_entry.cget("show"), "•"); a.show_btn.invoke(); self.assertEqual(a.key_entry.cget("show"), ""); self.assertEqual(a.show_btn._text, "Hide")
        a.show_btn.invoke(); self.assertEqual(a.key_entry.cget("show"), "•")
        dd = a.model_dd; dd.open(); root.update(); self.assertIsNotNone(dd._pop)
        class E: y = 6 + 2 * dd.ROW_H + 5
        dd._menu_pick(E); self.assertEqual(a.model_var.get(), "claude-opus-5-5"); self.assertIsNone(dd._pop)
        dd.open(); dd.close(); self.assertIsNone(dd._pop)
        a.hk.stop(); root.destroy()
    def test_layout_adapts_to_window_size(self):
        root, a, _ = self.make_app()
        for w, h in ((560, 560), (740, 820), (1000, 700), (1400, 1000)):
            root.geometry(f"{w}x{h}"); root.update(); root.update_idletasks()
            self.assertLessEqual(a.scroll.inner.winfo_width(), 820)
            self.assertLessEqual(a.scroll.inner.winfo_x() + a.scroll.inner.winfo_width(), a.scroll.canvas.winfo_width() + 1)
            self.assertGreater(a.save_btn.winfo_ismapped(), 0)                           # footer always visible
        a.hk.stop(); root.destroy()
    def test_key_never_shown_or_logged(self):
        import io, contextlib
        root, a, store = self.make_app(); buf = io.StringIO(); secret = "sk-ant-api03-SECRETSECRETSECRET99"
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            a.key_var.set(secret); a.save_key(); root.update()
        self.assertNotIn("SECRETSECRET", buf.getvalue() + self.all_text(root)); self.assertEqual(store.get_key(), secret)
        a.hk.stop(); root.destroy()



if __name__ == "__main__":
    unittest.main()
