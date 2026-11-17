import os, sys, io, tempfile, subprocess, unittest
os.environ["CURSORAI_ACCESS_SERVER"] = ""   # tests never talk to the owner's server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings_store as ss, claude_client as cc, capture, hotkeys
from PIL import Image


class FakeKR:
    def __init__(self): self.d = {}
    def get_password(self, s, a): return self.d.get((s, a))
    def set_password(self, s, a, v): self.d[(s, a)] = v
    def delete_password(self, s, a): self.d.pop((s, a), None)

class BrokenKR:
    def get_password(self, *a): raise RuntimeError("no keychain")
    set_password = delete_password = get_password

class Resp:
    def __init__(s, code=200, js=None): s.status_code, s._js, s.text = code, js or {}, str(js)
    def json(s): return s._js

class Http:
    def __init__(s, resp): s.resp, s.calls = resp, []
    def post(s, url, **kw): s.calls.append((url, kw)); return s.resp


def png(w, h):
    b = io.BytesIO(); Image.new("RGB", (w, h), "red").save(b, "PNG"); return b.getvalue()


class Settings(unittest.TestCase):
    def test_keychain_roundtrip(self):
        d = tempfile.mkdtemp(); kr = FakeKR(); s = ss.SettingsStore(d, kr)
        self.assertIsNone(s.get_key())
        self.assertEqual(s.set_key("  sk-ant-abc  "), "keychain")
        self.assertEqual(s.get_key(), "sk-ant-abc")
        self.assertFalse(os.path.exists(s.key_path))
        s.delete_key(); self.assertIsNone(s.get_key())
    def test_file_fallback_private(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, BrokenKR())
        self.assertEqual(s.set_key("sk-ant-x"), "file")
        self.assertEqual(oct(os.stat(s.key_path).st_mode & 0o777), "0o600")
        self.assertEqual(s.get_key(), "sk-ant-x"); s.delete_key(); self.assertIsNone(s.get_key())
    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError): ss.SettingsStore(tempfile.mkdtemp(), FakeKR()).set_key("  ")
    def test_settings_persist_and_ignore_unknown(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR())
        self.assertEqual(s.load()["model"], "claude-sonnet-5-5")
        s.save({"model": "claude-haiku-5-5", "evil": 1})
        self.assertEqual(ss.SettingsStore(d, FakeKR()).load()["model"], "claude-haiku-5-5")
        self.assertNotIn("evil", s.load())
    def test_key_never_in_settings_file(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR()); s.set_key("sk-ant-secret"); s.save({"model": "m"})
        self.assertNotIn("secret", open(s.settings_path).read())
    def test_corrupt_settings_file(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR()); open(s.settings_path, "w").write("{bad")
        self.assertEqual(s.load()["max_tokens"], 4096)
    def test_mask(self):
        self.assertNotIn("abcdefghijk", ss.mask("sk-ant-abcdefghijklmnop")); self.assertEqual(ss.mask(""), "")


class Client(unittest.TestCase):
    def test_request_shape_and_answer(self):
        h = Http(Resp(200, {"content": [{"type": "text", "text": " 42 "}]}))
        self.assertEqual(cc.ask_about_image("k", b"ABC", "claude-sonnet-5-5", "ins", 300, h), "42")
        url, kw = h.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(kw["headers"]["x-api-key"], "k"); self.assertEqual(kw["headers"]["anthropic-version"], "2023-06-01")
        c = kw["json"]["messages"][0]["content"]
        self.assertEqual((c[0]["type"], c[0]["source"]["data"], c[1]["text"]), ("image", "QUJD", "ins"))
    def test_401_hint(self):
        with self.assertRaises(cc.ClaudeError) as e: cc.ask_about_image("k", b"x", "m", "i", http=Http(Resp(401, {"error": {"message": "invalid x-api-key"}})))
        self.assertIn("401", str(e.exception)); self.assertIn("API key", str(e.exception))
    def test_empty_answer(self):
        with self.assertRaises(cc.ClaudeError) as e: cc.test_key("k", "m", Http(Resp(200, {"content": [], "stop_reason": "refusal"})))
        self.assertIn("refusal", str(e.exception))
    def test_no_key(self):
        with self.assertRaises(cc.ClaudeError): cc.ask_about_image("", b"x", "m", "i")
    def test_network_error(self):
        import requests
        class Bad:
            def post(s, *a, **k): raise requests.ConnectionError("down")
        with self.assertRaises(cc.ClaudeError): cc.test_key("k", "m", Bad())


class MaxTokens(unittest.TestCase):
    def test_retries_bigger_when_budget_spent_on_reasoning(self):
        class Seq:
            def __init__(s): s.calls = []
            def post(s, url, **kw):
                s.calls.append(kw["json"]["max_tokens"])
                return Resp(200, {"content": [], "stop_reason": "max_tokens"}) if len(s.calls) == 1 else Resp(200, {"content": [{"type": "text", "text": "B"}], "stop_reason": "end_turn"})
        h = Seq(); self.assertEqual(cc.ask_about_image("k", b"x", "m", "i", 300, h), "B"); self.assertEqual(h.calls, [300, 1800])
    def test_gives_up_after_one_retry(self):
        class Always:
            calls = 0
            def post(s, url, **kw): Always.calls += 1; return Resp(200, {"content": [], "stop_reason": "max_tokens"})
        with self.assertRaises(cc.ClaudeError) as e: cc.ask_about_image("k", b"x", "m", "i", 300, Always())
        self.assertEqual(Always.calls, 2); self.assertIn("max_tokens", str(e.exception))
    def test_truncated_text_is_still_returned(self):
        h = Http(Resp(200, {"content": [{"type": "text", "text": "part"}], "stop_reason": "max_tokens"}))
        self.assertEqual(cc.ask_about_image("k", b"x", "m", "i", 300, h), "part"); self.assertEqual(len(h.calls), 1)
    def test_old_saved_300_is_upgraded(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR()); open(s.settings_path, "w").write('{"max_tokens": 300}')
        self.assertEqual(s.load()["max_tokens"], 4096)
        open(s.settings_path, "w").write('{"max_tokens": 8000}'); self.assertEqual(s.load()["max_tokens"], 8000)


class Select(unittest.TestCase):
    def test_box_math(self):
        import selector as sel
        self.assertEqual(sel.image_box(10, 20, 110, 70, 2, 2, 2000, 1000), (20, 40, 220, 140))
        self.assertEqual(sel.image_box(110, 70, 10, 20, 2, 2, 2000, 1000), (20, 40, 220, 140))   # reversed drag
        self.assertEqual(sel.image_box(900, 450, 1400, 800, 1, 1, 1000, 500), (900, 450, 1000, 500))  # clamped
    def test_crop(self):
        out = capture.crop_and_downscale(png(400, 300), (10, 10, 110, 60))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (100, 50))
    def test_window_is_hidden_until_screenshot_is_loaded(self):
        import tkinter as tk, selector as sel
        from unittest import mock
        order = []
        class SpyTop(tk.Toplevel):
            def withdraw(s): order.append("withdraw"); return super().withdraw()
            def deiconify(s): order.append("show"); return super().deiconify()
        class SpyCanvas(tk.Canvas):
            def create_image(s, *a, **k): order.append("image"); return super().create_image(*a, **k)
        root = tk.Tk(); root.update()
        with mock.patch.object(sel.tk, "Toplevel", SpyTop), mock.patch.object(sel.tk, "Canvas", SpyCanvas):
            w = sel.RegionSelector(root, png(200, 100), lambda b: None); root.update()
        self.assertEqual(order, ["withdraw", "image", "show"])           # hidden -> picture loaded -> shown
        self.assertEqual(float(w.win.attributes("-alpha")), 1.0)         # and opaque once shown
        root.destroy()
    def test_escape_key_and_cancel_call_back_once(self):
        import tkinter as tk, selector as sel
        root = tk.Tk(); root.update(); got = []
        w = sel.RegionSelector(root, png(100, 100), got.append); root.update()
        w.win.event_generate("<Escape>"); root.update()
        self.assertEqual(got, [None])
        w2 = sel.RegionSelector(root, png(100, 100), got.append); root.update()
        w2.cancel(); w2.cancel(); root.update()
        self.assertEqual(got, [None, None])
        root.destroy()
    def test_two_clicks_no_drawing(self):
        import tkinter as tk, selector as sel
        root = tk.Tk(); root.update(); got = []
        w = sel.RegionSelector(root, png(root.winfo_screenwidth() * 2, root.winfo_screenheight() * 2), got.append); root.update()
        c = w.canvas
        self.assertEqual(c.cget("cursor"), "arrow")   # the pointer stays the normal arrow
        c.event_generate("<ButtonPress-1>", x=50, y=60); root.update()
        self.assertEqual(len(c.find_all()), 1)                              # only the screenshot: no outline, no fill
        c.event_generate("<ButtonPress-1>", x=150, y=160); root.update()
        self.assertEqual(got, [(100, 120, 300, 320)])                       # 2x scale, no mouse-hold needed
        w2 = sel.RegionSelector(root, png(100, 100), got.append); root.update()
        w2.canvas.event_generate("<ButtonPress-1>", x=5, y=5); w2.canvas.event_generate("<ButtonPress-1>", x=8, y=8); root.update()
        self.assertEqual(len(got), 1)                                       # second click too close: ignored
        w2.canvas.event_generate("<ButtonPress-1>", x=50, y=5); root.update()   # too thin (same y band): still ignored
        self.assertEqual(len(got), 1)
        w2.canvas.event_generate("<ButtonPress-3>", x=1, y=1); root.update()
        self.assertEqual(got[-1], None)                                     # right-click cancels
        w3 = sel.RegionSelector(root, png(root.winfo_screenwidth(), root.winfo_screenheight()), got.append); root.update()
        w3.canvas.event_generate("<ButtonPress-1>", x=90, y=80); w3.canvas.event_generate("<ButtonPress-1>", x=20, y=10); root.update()
        self.assertEqual(got[-1], (20, 10, 90, 80)); root.destroy()         # corners in any order


class Recorder(unittest.TestCase):
    def test_combos(self):
        import hotkey_recorder as r
        f = lambda k, c, st, pl="linux": r.combo_from_event(k, c, st, pl)
        self.assertEqual(f("a", 38, 0x5), "<ctrl>+<shift>+a")
        self.assertEqual(f("bracketright", 0, 0x4), "<ctrl>+]")
        self.assertEqual(f("backslash", 0, 0x4), "<ctrl>+\\")
        self.assertEqual(f("braceright", 0, 0x5), "<ctrl>+<shift>+]")      # shift+] reports braceright
        self.assertEqual(f("space", 0, 0x40), "<cmd>+space")
        self.assertEqual(f("a", 0, 0x8 | 0x10, "darwin"), "<alt>+<cmd>+a")
        self.assertEqual(f("a", 0, 0x4, "darwin"), "<ctrl>+a")
        self.assertIsNone(f("Control_L", 0, 0x4))
        for bad in (("a", 0, 0), ("F5", 0, 0x4), ("Return", 0, 0x4)):
            with self.assertRaises(ValueError): f(*bad)
    def test_pretty(self):
        import hotkey_recorder as r
        self.assertEqual(r.pretty("<ctrl>+<shift>+a", "darwin"), "Ctrl + Shift + A")
        self.assertEqual(r.pretty("<alt>+]", "darwin"), "Option + ]")
    def test_widget_records(self):
        import tkinter as tk, hotkey_recorder as r
        root = tk.Tk(); v = tk.StringVar(value="<ctrl>+<shift>+a"); msgs = []
        w = r.HotkeyRecorder(root, v, msgs.append); w.pack(); root.update(); w.focus_force(); root.update()
        w.begin(); root.update()
        w.event_generate("<KeyPress>", keysym="bracketright", state=0x4); root.update()
        self.assertEqual(v.get(), "<ctrl>+]"); self.assertFalse(w.recording)
        w.begin(); w.event_generate("<KeyPress>", keysym="x", state=0); root.update()
        self.assertEqual(v.get(), "<ctrl>+]"); self.assertTrue(msgs and "Hold" in msgs[-1]); self.assertTrue(w.recording)
        w.event_generate("<KeyPress>", keysym="Escape"); root.update()
        self.assertFalse(w.recording); self.assertEqual(v.get(), "<ctrl>+]")
        root.destroy()


class AnswerWin(unittest.TestCase):
    def test_transparent_path_on_mac(self):
        import tkinter as tk, answer_window as aw
        root = tk.Tk()
        w = aw.AnswerWindow(root); self.assertFalse(w.transparent)   # Linux: falls back to opaque
        seen = []
        for wd in (w.win, w.bar, w.text, w.close_btn, w.color_btn, w.grip, w.drag_hint):
            wd.configure = (lambda **kw: seen.append(kw))        # Mac-only colour name: record, don't apply
        w.transparent = True; w._apply_colors()
        self.assertTrue(any(kw.get("bg") == "#010101" for kw in seen))
        del w.win.configure, w.bar.configure, w.text.configure, w.close_btn.configure, w.color_btn.configure, w.grip.configure, w.drag_hint.configure
        w.transparent = False; w._apply_colors(); self.assertEqual(w.text.cget("bg"), "#1c1c1e")
        w.flip_color(); self.assertEqual(w.text.cget("fg"), "#000000")
        root.destroy()

class Opacity(unittest.TestCase):
    def test_setting_default_clamp_persist(self):
        import json
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR())
        self.assertEqual(s.load()["opacity"], 0.85); self.assertEqual(ss.OPACITY_MIN, 0.10)
        s.save({"opacity": 0.55}); self.assertEqual(ss.SettingsStore(d, FakeKR()).load()["opacity"], 0.55)
        for raw, want in ((5, 1.0), (-1, 0.1), (0.0, 0.1), ("x", 0.85), (None, 0.85), ("0.5", 0.5), (0.2, 0.2), (0.1, 0.1)):
            open(s.settings_path, "w").write(json.dumps({"opacity": raw}))
            self.assertEqual(s.load()["opacity"], want, raw)
    def test_popup_alpha(self):
        import tkinter as tk, answer_window as aw
        root = tk.Tk(); w = aw.AnswerWindow(root, opacity=0.5); root.update()
        w.show("x"); root.update()      # alpha is (re)applied whenever the popup is shown
        self.assertEqual(w.opacity, 0.5); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.5, 2)
        w.hide(); w.toggle(); root.update(); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.5, 2)
        w.set_opacity(5); self.assertEqual(w.opacity, 1.0); w.set_opacity(0); self.assertEqual(w.opacity, 0.1)
        w.set_opacity(0.1); w.show("x"); root.update(); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.1, 2)
        w.set_opacity("junk"); self.assertEqual(w.opacity, 1.0); root.destroy()
    def test_slider_updates_popup_label_and_saves_on_release(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR()); store.save({"opacity": 0.8})
        a = app.App(root, store); root.update()
        self.assertEqual(a.answer.opacity, 0.8); self.assertEqual(a.op_label.cget("text"), "80%")     # restored at start
        a.op_var.set(0.4); a._opacity_changed(0.4)
        self.assertEqual(a.answer.opacity, 0.4); self.assertEqual(a.op_label.cget("text"), "40%")
        self.assertEqual(store.load()["opacity"], 0.8)                                                  # not saved mid-drag
        a._opacity_released(); self.assertEqual(store.load()["opacity"], 0.4)
        self.assertTrue(a.answer.is_visible())                                                          # hidden popup -> preview shown
        a._end_preview(); self.assertFalse(a.answer.is_visible())
        a.answer.show("real answer"); a._opacity_released(); self.assertTrue(a.answer.is_visible()); self.assertIsNone(a._preview_id)
        a.hk.stop(); root.destroy()


class Gui(unittest.TestCase):
    def test_app_smoke(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR())
        a = app.App(root, store); root.update()
        a.key_var.set("sk-ant-api03-guitestKEYlongenough1234"); a.save_key(); root.update()
        self.assertEqual(store.get_key(), "sk-ant-api03-guitestKEYlongenough1234"); self.assertEqual(a.key_var.get(), "sk-ant-api03-guitestKEYlongenough1234")
        self.assertIn("sk-ant", a.key_status.cget("text")); self.assertNotIn("guitestKEY", a.key_status.cget("text"))
        a.cap_var.set("a"); a.save_settings(); self.assertIn("modifier", a.status.cget("text"))
        a.cap_var.set("<ctrl>+<shift>+a"); a.tog_var.set("<ctrl>+<shift>+a"); a.save_settings(); self.assertIn("different", a.status.cget("text"))
        a.tog_var.set("<ctrl>+<shift>+j"); a.col_var.set("<ctrl>+<shift>+j"); a.save_settings(); self.assertIn("different", a.status.cget("text"))
        a.col_var.set("<ctrl>+<shift>+k"); a.model_var.set("claude-haiku-5-5"); a.save_settings()
        self.assertEqual(store.load()["model"], "claude-haiku-5-5")
        a._handle("capture_ok", "Paris"); self.assertTrue(a.answer.is_visible()); self.assertEqual(a.answer.text.cget("text"), "Paris")
        a.answer.flip_color(); self.assertTrue(store.load()["dark_text"])
        before = a.answer.dark_text; a._handle("hotkey_color", None); self.assertNotEqual(a.answer.dark_text, before)
        self.assertEqual(store.load()["color_hotkey"], "<ctrl>+<shift>+k")
        a._handle("hotkey_toggle", None); self.assertFalse(a.answer.is_visible())
        a._handle("capture_ok", None); self.assertIn("cancel", a.status.cget("text"))
        a.remove_key(); self.assertIsNone(store.get_key())
        a.start_capture(); self.assertIn("API key", a.status.cget("text"))
        a.hk.stop(); root.destroy()
    def test_full_flow_with_mocks(self):
        import tkinter as tk, app, time
        orig = (app.capture.grab_screen, app.selector.RegionSelector, app.claude_client.ask_about_image)
        self.addCleanup(lambda: (setattr(app.capture, 'grab_screen', orig[0]), setattr(app.selector, 'RegionSelector', orig[1]), setattr(app.claude_client, 'ask_about_image', orig[2])))
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR()); store.set_key("k")
        a = app.App(root, store)
        app.capture.grab_screen = lambda: png(400, 300)
        class FakeSel:
            def __init__(self, r, shot, cb, area=None): cb((10, 10, 200, 150))
        app.selector.RegionSelector = FakeSel
        app.claude_client.ask_about_image = lambda *x, **y: "B"
        hid = []; a.hide_main = lambda: hid.append(1)
        a.start_capture()
        for _ in range(40): root.update(); time.sleep(0.05)
        self.assertEqual(a.answer.text.cget("text"), "B"); self.assertFalse(a.busy)
        self.assertTrue(hid)   # settings window was minimised; only the popup shows
        a.hk.stop(); root.destroy()


class CancelQuietly(unittest.TestCase):
    def test_cancel_shows_nothing(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR()); store.set_key("k")
        a = app.App(root, store); root.update(); shown = []
        a.show_main = lambda: shown.append("settings"); a.answer.show = lambda m: shown.append("answer:" + m)
        a.busy = True; a.answer.hide(); a._selected(b"png", None)
        self.assertFalse(a.busy); self.assertEqual(shown, [])
        self.assertFalse(a.hk.add_escape(lambda: None))      # Windows: Tk's own Esc binding is used
        a.hk.stop(); root.destroy()


import queue, threading, time as _time

class FakeUser32:
    def __init__(s, fail_vk=None):
        s.reg, s.unreg, s.q, s.fail_vk = [], [], queue.Queue(), fail_vk
    def PeekMessageW(s, *a): return 0
    def RegisterHotKey(s, hwnd, i, mods, vk):
        if vk == s.fail_vk: return 0
        s.reg.append((i, mods, vk)); return 1
    def UnregisterHotKey(s, hwnd, i): s.unreg.append(i); return 1
    def GetMessageW(s, ref, h, a, b):
        m = s.q.get(timeout=3)
        if m is None: return 0
        ref._obj.message, ref._obj.wParam = m; return 1
    def PostThreadMessageW(s, tid, msg, w, l): s.q.put(None); return 1

class FakeKernel32:
    def GetCurrentThreadId(s): return 77


class WinHot(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(hotkeys.parse("<ctrl>+<shift>+a"), (2 | 4, 0x41))
        self.assertEqual(hotkeys.parse("<alt>+]"), (1, 0xDD)); self.assertEqual(hotkeys.parse("<ctrl>+\\"), (2, 0xDC))
        self.assertEqual(hotkeys.parse("<ctrl>+<cmd>+5"), (2 | 8, 0x35)); self.assertEqual(hotkeys.parse("<ctrl>+space"), (2, 0x20))
        for bad in ("", "a", "<ctrl>", "<ctrl>+nonsense", "<ctrl>+a+b", "<ctrl>+<shift>"): self.assertIsNotNone(hotkeys.validate(bad), bad)
    def test_register_dispatch_unregister(self):
        u = FakeUser32(); hits = []; got = threading.Event()
        m = hotkeys.HotkeyManager(u, FakeKernel32())
        m.start({"<ctrl>+<shift>+a": lambda: hits.append("cap"), "<ctrl>+]": lambda: (hits.append("tog"), got.set())})
        self.assertEqual(m.backend, "win32")
        self.assertEqual(u.reg, [(1, 2 | 4 | 0x4000, 0x41), (2, 2 | 0x4000, 0xDD)])   # MOD_NOREPEAT set
        u.q.put((0x0312, 2)); self.assertTrue(got.wait(3)); self.assertEqual(hits, ["tog"])
        u.q.put((0x0312, 99)); u.q.put((0x0001, 1))                                      # unknown id / other message: ignored
        m.stop(); self.assertEqual(sorted(u.unreg), [1, 2]); self.assertEqual(hits, ["tog"])
    def test_callback_error_does_not_kill_loop(self):
        u = FakeUser32(); hits = []; done = threading.Event()
        m = hotkeys.HotkeyManager(u, FakeKernel32())
        m.start({"<ctrl>+<shift>+a": lambda: 1 / 0, "<ctrl>+b": lambda: (hits.append(1), done.set())})
        u.q.put((0x0312, 1)); u.q.put((0x0312, 2)); self.assertTrue(done.wait(3)); m.stop()
    def test_refused_combo(self):
        u = FakeUser32(fail_vk=0x42); m = hotkeys.HotkeyManager(u, FakeKernel32())
        with self.assertRaises(RuntimeError) as e: m.start({"<ctrl>+a": lambda: None, "<ctrl>+b": lambda: None})
        self.assertIn("<ctrl>+b", str(e.exception)); self.assertEqual(u.unreg, [1])   # the one that did register is released
    def test_restart_replaces_old_registrations(self):
        u = FakeUser32(); m = hotkeys.HotkeyManager(u, FakeKernel32())
        m.start({"<ctrl>+a": lambda: None}); m.start({"<ctrl>+b": lambda: None}); m.stop()
        self.assertEqual(len(u.reg), 2); self.assertEqual(len(u.unreg), 2)


class WinCapture(unittest.TestCase):
    def test_grab_ok_and_error(self):
        out = capture.grab_screen(lambda: Image.new("RGBA", (40, 30), "blue"))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (40, 30))
        def boom(): raise OSError("screen grab failed")
        with self.assertRaises(capture.CaptureError): capture.grab_screen(boom)
    def test_virtual_screen_fallback(self):
        import tkinter as tk
        root = tk.Tk(); l, t, w, h = capture.virtual_screen(root)
        self.assertEqual((l, t, w, h), (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())); root.destroy()
        with self.assertRaises(capture.CaptureError): capture.virtual_screen(None)


class WinSelector(unittest.TestCase):
    def test_multi_monitor_area_with_negative_origin(self):
        import tkinter as tk, selector as sel
        root = tk.Tk(); root.update(); got = []
        w = sel.RegionSelector(root, png(600, 400), got.append, area=(-100, -50, 300, 200)); root.update()
        self.assertTrue(w.win.geometry().startswith("300x200"))
        w.canvas.event_generate("<ButtonPress-1>", x=50, y=60); w.canvas.event_generate("<ButtonPress-1>", x=150, y=160); root.update()
        self.assertEqual(got, [(100, 120, 300, 320)])      # 2x: image is twice the area size
        root.destroy()


class WinRecorder(unittest.TestCase):
    def test_windows_modifiers(self):
        import hotkey_recorder as r
        f = lambda k, st: r.combo_from_event(k, 0, st, "win32")
        self.assertEqual(f("a", 0x4 | 0x1), "<ctrl>+<shift>+a"); self.assertEqual(f("bracketright", 0x20000), "<alt>+]")
        self.assertEqual(f("a", 0x4 | 0x8), "<ctrl>+a")          # 0x8 is NumLock, not a modifier
        with self.assertRaises(ValueError): f("a", 0x8)           # NumLock alone is not enough
        self.assertEqual(r.pretty("<ctrl>+<alt>+a", "win32"), "Ctrl + Alt + A")


if __name__ == "__main__":
    unittest.main(verbosity=1)
