import os, sys, io, tempfile, subprocess, unittest
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


class Capture(unittest.TestCase):
    def runner_writing(self, data, rc=0):
        def r(cmd, **kw):
            self.cmd = cmd
            if data is not None: open(cmd[-1], "wb").write(data)
            return subprocess.CompletedProcess(cmd, rc, b"", b"")
        return r
    def test_ok_downscales(self):
        out = capture.capture_region(self.runner_writing(png(4000, 2000)))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (2576, 1288))
        self.assertEqual(self.cmd[:4], ["screencapture", "-i", "-s", "-x"])
    def test_retina_region_keeps_full_resolution(self):
        out = capture.capture_region(self.runner_writing(png(2400, 1500)))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (2400, 1500))
    def test_huge_noisy_image_stays_under_api_limit(self):
        import os as _os
        noisy = Image.frombytes("RGB", (2600, 1800), _os.urandom(2600 * 1800 * 3)); b = io.BytesIO(); noisy.save(b, "PNG")
        out = capture.downscale_png(b.getvalue()); self.assertLessEqual(len(out), capture.MAX_BYTES)
    def test_small_not_upscaled(self):
        self.assertEqual(Image.open(io.BytesIO(capture.capture_region(self.runner_writing(png(200, 100))))).size, (200, 100))
    def test_cancel_returns_none(self):
        self.assertIsNone(capture.capture_region(self.runner_writing(None, rc=1)) if False else capture.capture_region(lambda c, **k: subprocess.CompletedProcess(c, 0, b"", b"")))
    def test_failure_raises(self):
        def r(c, **k): return subprocess.CompletedProcess(c, 1, b"", b"permission denied")
        with self.assertRaises(capture.CaptureError): capture.capture_region(r)
    def test_not_mac(self):
        def r(c, **k): raise FileNotFoundError()
        with self.assertRaises(capture.CaptureError): capture.capture_region(r)
    def test_temp_file_cleaned(self):
        paths = []
        def r(c, **k): paths.append(c[-1]); open(c[-1], "wb").write(png(10, 10)); return subprocess.CompletedProcess(c, 0, b"", b"")
        capture.capture_region(r); self.assertFalse(os.path.exists(paths[0]))


class Hot(unittest.TestCase):
    def test_validate(self):
        self.assertIsNone(hotkeys.validate("<ctrl>+<shift>+a"))
        self.assertIsNone(hotkeys.validate("<cmd>+<shift>+8"))
        for bad in ("", "a", "<ctrl>", "<ctrl>+<shift>", "<ctrl>+nonsense", "<ctrl>+a+b"): self.assertIsNotNone(hotkeys.validate(bad), bad)
    def test_brackets_and_backslash(self):
        self.assertEqual(hotkeys.parse("<ctrl>+]")[1], 30); self.assertEqual(hotkeys.parse("<ctrl>+\\")[1], 42)
        self.assertEqual(hotkeys.parse("<cmd>+<shift>+[")[1], 33); self.assertIsNotNone(hotkeys.validate("]"))
    def test_matching(self):
        p = hotkeys.parse("<ctrl>+<shift>+a"); F = hotkeys.MODS
        self.assertTrue(hotkeys.matches(p, 0, F["<ctrl>"] | F["<shift>"]))
        self.assertTrue(hotkeys.matches(p, 0, F["<ctrl>"] | F["<shift>"] | 0x100))  # unrelated flag bits ignored
        self.assertFalse(hotkeys.matches(p, 0, F["<ctrl>"]))                      # missing shift
        self.assertFalse(hotkeys.matches(p, 0, F["<ctrl>"] | F["<shift>"] | F["<cmd>"]))  # extra modifier
        self.assertFalse(hotkeys.matches(p, 1, F["<ctrl>"] | F["<shift>"]))       # wrong key
    def test_mac_path_never_uses_pynput(self):
        import inspect; src = inspect.getsource(hotkeys.HotkeyManager.start)
        self.assertIn("NSEvent", src); self.assertIn('sys.platform == "darwin"', src)


class Select(unittest.TestCase):
    def test_box_math(self):
        import selector as sel
        self.assertEqual(sel.image_box(10, 20, 110, 70, 2, 2, 2000, 1000), (20, 40, 220, 140))
        self.assertEqual(sel.image_box(110, 70, 10, 20, 2, 2, 2000, 1000), (20, 40, 220, 140))   # reversed drag
        self.assertEqual(sel.image_box(900, 450, 1400, 800, 1, 1, 1000, 500), (900, 450, 1000, 500))  # clamped
    def test_crop(self):
        out = capture.crop_and_downscale(png(400, 300), (10, 10, 110, 60))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (100, 50))
    def test_grab_screen(self):
        def r(c, **k): open(c[-1], "wb").write(png(20, 20)); return subprocess.CompletedProcess(c, 0, b"", b"")
        self.assertEqual(Image.open(io.BytesIO(capture.grab_screen(r))).size, (20, 20))
        with self.assertRaises(capture.CaptureError): capture.grab_screen(lambda c, **k: subprocess.CompletedProcess(c, 1, b"", b"no permission"))
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
        self.assertEqual(got, [None, None])               # idempotent: one callback per selector
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
        self.assertEqual(f("aring", 0x1E0000, 0x10, "darwin"), "<alt>+a")   # Option+A on a Mac: fall back to key code 0
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
        self.assertTrue(any(kw.get("bg") == "systemTransparent" for kw in seen))
        del w.win.configure, w.bar.configure, w.text.configure, w.close_btn.configure, w.color_btn.configure, w.grip.configure, w.drag_hint.configure
        w.transparent = False; w._apply_colors(); self.assertEqual(w.text.cget("bg"), "#1c1c1e")
        w.flip_color(); self.assertEqual(w.text.cget("fg"), "#000000")
        root.destroy()

class Pinned(unittest.TestCase):
    def test_pin_calls_cocoa_on_mac(self):
        import tkinter as tk, types, answer_window as aw
        from unittest import mock
        calls = []
        class FakeWin:
            def __init__(s, t): s.t = t
            def title(s): return s.t
            def setLevel_(s, v): calls.append(("level", s.t, v))
            def setCollectionBehavior_(s, v): calls.append(("behavior", s.t, v))
            def setHidesOnDeactivate_(s, v): calls.append(("hides", s.t, v))
        fake = types.ModuleType("AppKit"); fake.NSApp = types.SimpleNamespace(windows=lambda: [FakeWin("other"), FakeWin(aw.TITLE)])
        root = tk.Tk(); w = aw.AnswerWindow(root)
        with mock.patch.dict(sys.modules, {"AppKit": fake}), mock.patch.object(sys, "platform", "darwin"):
            w._pin_mac()
        self.assertEqual(calls, [("level", aw.TITLE, 25), ("behavior", aw.TITLE, 1 | 16 | 64 | 256), ("hides", aw.TITLE, False)])
        root.destroy()
    def test_pin_noop_off_mac_and_survives_errors(self):
        import tkinter as tk, answer_window as aw
        root = tk.Tk(); w = aw.AnswerWindow(root); w._pin_mac()
        from unittest import mock
        with mock.patch.object(sys, "platform", "darwin"):
            w._pin_mac()   # no AppKit on Linux -> must not raise
        root.destroy()
    def test_keepalive_relifts_only_when_visible(self):
        import tkinter as tk, answer_window as aw
        root = tk.Tk(); w = aw.AnswerWindow(root); lifts = []
        w.win.lift = lambda *a: lifts.append(1)
        w._keepalive(); self.assertEqual(lifts, [])      # hidden: nothing
        w.show("x"); n = len(lifts); w._keepalive(); self.assertGreater(len(lifts), n)
        root.destroy()


class Carbon(unittest.TestCase):
    def make_lib(self, fail_on=None):
        import types, ctypes
        lib = types.SimpleNamespace(registered=[], unregistered=[], installed=[], removed=[], upp=None, hkid=None)
        lib.GetApplicationEventTarget = lambda: 1234
        def install(target, upp, n, spec, data, ref): lib.installed.append((target, n)); lib.upp = upp; return 0
        def register(code, mods, hkid, target, opts, ref):
            if fail_on == code: return -9878
            lib.registered.append((code, mods, hkid.signature, hkid.id)); return 0
        def getparam(event, name, typ, a, size, b, out):
            out._obj.signature, out._obj.id = lib.hkid; return 0
        lib.InstallEventHandler, lib.RegisterEventHotKey, lib.GetEventParameter = install, register, getparam
        lib.UnregisterEventHotKey = lambda ref: lib.unregistered.append(1) or 0
        lib.RemoveEventHandler = lambda ref: lib.removed.append(1) or 0
        return lib
    def test_fourcc_and_mods(self):
        import carbon_hotkeys as ch
        self.assertEqual(ch.fourcc("keyb"), 0x6B657962)
        self.assertEqual(ch.carbon_mods(hotkeys.MODS["<ctrl>"] | hotkeys.MODS["<shift>"]), 0x1000 | 0x0200)
        self.assertEqual(ch.carbon_mods(hotkeys.MODS["<cmd>"] | hotkeys.MODS["<alt>"]), 0x0100 | 0x0800)
    def test_register_dispatch_unregister(self):
        import carbon_hotkeys as ch
        lib = self.make_lib(); hits = []
        c = ch.CarbonHotkeys(lib)
        p1, p2 = hotkeys.parse("<ctrl>+<shift>+a"), hotkeys.parse("<ctrl>+]")
        c.register([(p1[0], p1[1], lambda: hits.append("cap")), (p2[0], p2[1], lambda: hits.append("tog"))])
        self.assertEqual([(r[0], r[1], r[3]) for r in lib.registered], [(0, 0x1200, c._base + 1), (30, 0x1000, c._base + 2)])
        lib.hkid = (ch.SIGNATURE, c._base + 2); self.assertEqual(c._on_event(None, 1, None), 0); self.assertEqual(hits, ["tog"])
        lib.hkid = (ch.SIGNATURE, c._base + 1); c._on_event(None, 1, None); self.assertEqual(hits, ["tog", "cap"])
        lib.hkid = (0xDEAD, 1); self.assertEqual(c._on_event(None, 1, None), ch.NOT_HANDLED); self.assertEqual(hits, ["tog", "cap"])   # not ours: let others try
        c._callbacks[c._base + 1] = lambda: 1 / 0; lib.hkid = (ch.SIGNATURE, c._base + 1); self.assertEqual(c._on_event(None, 1, None), ch.NOT_HANDLED)  # never raises into Cocoa
        c.unregister_all(); self.assertEqual((len(lib.unregistered), len(lib.removed)), (2, 1))
    def test_two_instances_do_not_collide(self):
        import carbon_hotkeys as ch
        lib = self.make_lib(); a, b = ch.CarbonHotkeys(lib), ch.CarbonHotkeys(lib); hits = []
        a.register([(2, 0, lambda: hits.append("a"))]); b.register([(0, 53, lambda: hits.append("esc"))])
        lib.hkid = (ch.SIGNATURE, b._base + 1)
        self.assertEqual(a._on_event(None, 1, None), ch.NOT_HANDLED); self.assertEqual(hits, [])   # a ignores b's key
        self.assertEqual(b._on_event(None, 1, None), 0); self.assertEqual(hits, ["esc"])
    def test_escape_registers_bare_esc_and_cleans_up(self):
        import carbon_hotkeys as ch
        from unittest import mock
        lib = self.make_lib(); real = ch.CarbonHotkeys; hits = []
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(ch, "CarbonHotkeys", lambda: real(lib)):
            m = hotkeys.HotkeyManager()
            self.assertTrue(m.add_escape(lambda: hits.append(1)))
            self.assertEqual([(r[0], r[1]) for r in lib.registered], [(53, 0)])      # Esc, no modifiers
            m.remove_escape(); self.assertEqual(len(lib.unregistered), 1); m.remove_escape()   # idempotent
            m.add_escape(lambda: None); m.stop(); self.assertEqual(len(lib.unregistered), 2)   # stop() releases it too
        self.assertFalse(hotkeys.HotkeyManager().add_escape(lambda: None))   # not a Mac: no-op
    def test_failure_raises(self):
        import carbon_hotkeys as ch
        c = ch.CarbonHotkeys(self.make_lib(fail_on=30))
        with self.assertRaises(OSError): c.register([(hotkeys.parse("<ctrl>+]")[0], 30, lambda: None)])
    def test_manager_prefers_carbon_on_mac(self):
        import types, carbon_hotkeys as ch
        from unittest import mock
        lib = self.make_lib(); hits = []
        real = ch.CarbonHotkeys
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(ch, "CarbonHotkeys", lambda: real(lib)):
            m = hotkeys.HotkeyManager(); m.start({"<ctrl>+<shift>+a": lambda: hits.append(1)})
            self.assertEqual(m.backend, "carbon"); self.assertEqual(len(lib.registered), 1)
            m.stop(); self.assertEqual(len(lib.unregistered), 1)
    def test_manager_falls_back_to_key_monitor(self):
        import types, carbon_hotkeys as ch
        from unittest import mock
        lib = self.make_lib(fail_on=0); added = []
        fake = types.ModuleType("AppKit")
        fake.NSEvent = types.SimpleNamespace(addGlobalMonitorForEventsMatchingMask_handler_=lambda m, h: added.append("g") or "G",
                                             addLocalMonitorForEventsMatchingMask_handler_=lambda m, h: added.append("l") or "L",
                                             removeMonitor_=lambda m: None)
        real = ch.CarbonHotkeys
        with mock.patch.dict(sys.modules, {"AppKit": fake}), mock.patch.object(sys, "platform", "darwin"), mock.patch.object(ch, "CarbonHotkeys", lambda: real(lib)):
            m = hotkeys.HotkeyManager(); m.start({"<ctrl>+<shift>+a": lambda: None})
            self.assertEqual(m.backend, "nsevent"); self.assertEqual(added, ["g", "l"])


class Background(unittest.TestCase):
    def test_keep_awake_and_permission(self):
        import types
        from unittest import mock
        seen = {}
        class PI:
            def beginActivityWithOptions_reason_(s, o, r): seen["opts"], seen["reason"] = o, r; return "token"
        fnd = types.ModuleType("Foundation"); fnd.NSProcessInfo = types.SimpleNamespace(processInfo=lambda: PI())
        qz = types.ModuleType("Quartz"); asked = []
        qz.CGPreflightListenEventAccess = lambda: False; qz.CGRequestListenEventAccess = lambda: asked.append(1)
        self.assertIsNone(hotkeys.keep_awake()); self.assertIsNone(hotkeys.input_monitoring_granted())   # not a Mac
        with mock.patch.dict(sys.modules, {"Foundation": fnd, "Quartz": qz}), mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(hotkeys.keep_awake(), "token")
            self.assertEqual(seen["opts"] & (1 << 20), 0)          # does not block system sleep
            self.assertNotEqual(seen["opts"] & 0xFF, 0)            # user-initiated bits (disables App Nap)
            self.assertFalse(hotkeys.input_monitoring_granted()); self.assertEqual(asked, [])
            self.assertFalse(hotkeys.input_monitoring_granted(request=True)); self.assertEqual(asked, [1])
    def test_color_default(self):
        self.assertEqual(ss.DEFAULTS["color_hotkey"], "<ctrl>+<shift>+c")
        self.assertIsNone(hotkeys.validate(ss.DEFAULTS["color_hotkey"]))


class CancelQuietly(unittest.TestCase):
    def make_app(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR()); store.set_key("k")
        a = app.App(root, store); root.update()
        return root, a
    def test_cancel_shows_nothing_and_blocks_reopen(self):
        import time, app
        root, a = self.make_app(); shown = []
        a.show_main = lambda: shown.append("settings")
        a.answer.show = lambda m: shown.append("answer:" + m)
        a.busy = True; a.answer.hide()
        a._selected(b"png", None)
        self.assertFalse(a.busy); self.assertEqual(shown, [])                 # nothing popped up
        a._on_reopen(); self.assertEqual(shown, [])                            # macOS 'reopen' right after: ignored
        a._quiet_until = time.time() - 1; a._on_reopen(); self.assertEqual(shown, ["settings"])   # a real Dock click later still works
        a.hk.stop(); root.destroy()
    def test_global_esc_cancels_open_selector_and_is_released(self):
        import app
        root, a = self.make_app(); events = []
        class Sel:
            done = False
            def __init__(s, r, shot, cb, area=None): s.cb = cb; events.append("open")
            def cancel(s): s.done = True; events.append("cancel"); s.cb(None)
        orig = (app.capture.grab_screen, app.selector.RegionSelector)
        self.addCleanup(lambda: (setattr(app.capture, "grab_screen", orig[0]), setattr(app.selector, "RegionSelector", orig[1])))
        app.capture.grab_screen = lambda: png(50, 50); app.selector.RegionSelector = Sel
        added, removed = [], []
        a.hk.add_escape = lambda cb: added.append(cb) or True; a.hk.remove_escape = lambda: removed.append(1)
        a._begin_selection()
        self.assertEqual(events, ["open"]); self.assertEqual(len(added), 1)   # Esc armed while the selector is open
        added[0](); root.update()
        kind, val = a.q.get_nowait(); a._handle(kind, val)                       # what the Esc key puts on the queue
        self.assertEqual(events, ["open", "cancel"]); self.assertTrue(removed); self.assertFalse(a.busy)
        a.hk.stop(); root.destroy()


class Opacity(unittest.TestCase):
    def test_setting_default_clamp_persist(self):
        import json
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, FakeKR())
        self.assertEqual(s.load()["opacity"], 0.85)                      # new installs
        self.assertEqual(ss.OPACITY_MIN, 0.10)
        s.save({"opacity": 0.55}); self.assertEqual(ss.SettingsStore(d, FakeKR()).load()["opacity"], 0.55)
        for raw, want in ((5, 1.0), (-1, 0.1), (0.0, 0.1), ("x", 0.85), (None, 0.85), ("0.5", 0.5), (0.2, 0.2), (0.1, 0.1),
                          (1.0, 1.0), (0.123, 0.12), (float("nan"), 0.85)):
            open(s.settings_path, "w").write(json.dumps({"opacity": raw}))
            self.assertEqual(s.load()["opacity"], want, raw)
    def test_popup_alpha(self):
        import tkinter as tk, answer_window as aw
        root = tk.Tk(); w = aw.AnswerWindow(root, opacity=0.5); root.update()
        w.show("x"); root.update()      # alpha is (re)applied whenever the popup is shown
        self.assertEqual(w.opacity, 0.5); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.5, 2)
        w.hide(); w.toggle(); root.update(); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.5, 2)
        w.set_opacity(5); self.assertEqual(w.opacity, 1.0); w.set_opacity(0); self.assertEqual(w.opacity, 0.1)
        w.set_opacity(0.1); w.show("x"); root.update(); self.assertAlmostEqual(float(w.win.attributes("-alpha")), 0.1, 2)   # 10 % works
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
        self.assertNotIn("Input Monitoring", txt); self.assertNotIn("Privacy_ListenEvent", txt)
        for need in ("Cursor AI", "Personalize your AI assistant.", "AI Configuration", "Save Key", "Test Connection",
                     "Remove Key", "AI Model", "Prompt & Behavior", "Keyboard Shortcuts", "Capture Screenshot", "Show/Hide Popup",
                     "Change Text Color", "Appearance", "Popup Opacity", "Always on Top", "Screen Recording", "Save Settings", "Cancel"):
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
    def test_permissions(self):
        import permissions as p
        from unittest import mock
        self.assertIsNone(p.screen_recording_granted()); self.assertFalse(p.open_screen_recording_settings())   # Linux
        with mock.patch.object(p.sys, "platform", "darwin"), mock.patch.object(p.subprocess, "run") as run:
            self.assertTrue(p.open_screen_recording_settings()); self.assertIn("Privacy_ScreenCapture", run.call_args[0][0][1])
        root, a, _ = self.make_app()
        for state, word in ((True, "Granted"), (False, "Not granted"), (None, "unavailable")):
            with mock.patch.object(p, "screen_recording_granted", lambda s=state: s):
                a._refresh_permission(); self.assertIn(word, a.perm_label.cget("text"))
        a.hk.stop(); root.destroy()
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


class WheelScroll(unittest.TestCase):
    def make(self):
        import time, tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR())
        a = app.App(root, store); root.geometry("760x560+0+0")
        for _ in range(6): root.update(); time.sleep(0.03)
        return root, a
    def test_mouse_wheel_scrolls_from_any_control_and_clamps(self):
        root, a = self.make(); c = a.scroll.canvas
        self.assertLess(c.yview()[1], 1.0)                                       # content taller than the window
        for target in (c, a.scroll.inner, a.instr_box, a.op_scale, a.tiles[0], a.check_btn, a.key_field, a.instr):
            c.yview_moveto(0); root.update()
            target.event_generate("<MouseWheel>", delta=-120, x=5, y=5); root.update()
            self.assertGreater(c.yview()[0], 0.0, type(target).__name__)         # wheel down moves the page
            target.event_generate("<MouseWheel>", delta=120, x=5, y=5); root.update()
            self.assertEqual(c.yview()[0], 0.0, type(target).__name__)           # and back up, never above the top
        for _ in range(200): c.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
        root.update(); self.assertAlmostEqual(c.yview()[1], 1.0, 3)              # clamps at the bottom
        a.hk.stop(); root.destroy()
    def test_touchpad_scroll_decoding_and_no_scroll_when_content_fits(self):
        import ui_kit
        root, a = self.make(); sf = a.scroll; sf.canvas.yview_moveto(0.0)
        class E:  # a Tk 9 <TouchpadScroll> event, delta already decoded by Tk's own helper
            widget = a.check_btn; delta = 0
        orig = ui_kit._touchpad_dy; self.addCleanup(lambda: setattr(ui_kit, "_touchpad_dy", orig))
        ui_kit._touchpad_dy = lambda e: -30.0; sf._touchpad(E()); self.assertGreater(sf.canvas.yview()[0], 0)
        sf.canvas.yview_moveto(0); real = sf.canvas.yview; sf.canvas.yview = lambda *a: (0.0, 1.0) if not a else real(*a)
        sf._scroll(100); sf.canvas.yview = real; self.assertEqual(real()[0], 0.0)    # everything fits: nothing moves
        a.hk.stop(); root.destroy()



class Gui(unittest.TestCase):
    def test_app_smoke(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), FakeKR())
        a = app.App(root, store); root.update()
        a.key_var.set("sk-ant-api03-guitestKEYlongenough1234"); a.save_key(); root.update()
        self.assertEqual(store.get_key(), "sk-ant-api03-guitestKEYlongenough1234"); self.assertEqual(a.key_var.get(), "sk-ant-api03-guitestKEYlongenough1234")   # stays in the masked field
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
            def __init__(self, r, shot, cb): cb((10, 10, 200, 150))
        app.selector.RegionSelector = FakeSel
        app.claude_client.ask_about_image = lambda *x, **y: "B"
        a.start_capture()
        for _ in range(40): root.update(); time.sleep(0.05)
        self.assertEqual(a.answer.text.cget("text"), "B"); self.assertFalse(a.busy)
        self.assertEqual(root.state(), "withdrawn")   # settings window hidden; only the popup shows
        a.show_main(); root.update(); self.assertEqual(root.state(), "normal")
        a.hk.stop(); root.destroy()

if __name__ == "__main__":
    unittest.main(verbosity=1)


class PopupScale(unittest.TestCase):
    def test_clamp_and_persist(self):
        import settings_store as ss
        self.assertEqual(ss.clamp_scale(0.1), 0.5); self.assertEqual(ss.clamp_scale(9), 1.5)
        self.assertEqual(ss.clamp_scale("x"), 1.0); self.assertEqual(ss.clamp_scale(0.73), 0.75)

    def test_window_and_text_shrink(self):
        import tkinter as tk, answer_window
        root = tk.Tk(); w = answer_window.AnswerWindow(root); w.win.update_idletasks()
        big = int(str(w.text.cget("font")).split()[1]) if False else w.text.cget("font")
        w.win.geometry("420x140"); w.win.update_idletasks()
        w.set_scale(0.5); w.win.update_idletasks()
        self.assertEqual(w.scale, 0.5)
        self.assertLess(w.win.winfo_width(), 300); self.assertLess(w.win.winfo_height(), 100)
        self.assertIn("8", str(w.text.cget("font")))
        w.set_scale(1.0); self.assertIn("15", str(w.text.cget("font")))
        root.destroy()
