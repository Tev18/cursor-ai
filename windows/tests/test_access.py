"""Remote on/off per device."""
import io, json, os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import access, settings_store as ss

ME = "a1b2c3d4e5f6"


class KR:
    def __init__(s): s.d = {}
    def get_password(s, a, b): return s.d.get((a, b))
    def set_password(s, a, b, v): s.d[(a, b)] = v
    def delete_password(s, a, b): s.d.pop((a, b), None)


class Evaluate(unittest.TestCase):
    def test_no_policy_allows(self):
        self.assertEqual(access.evaluate({}, ME), (True, "")); self.assertTrue(access.evaluate(None, ME)[0])
    def test_blocklist(self):
        p = {"devices": {ME: {"name": "Ali", "enabled": False}, "x": {"enabled": True}}}
        ok, msg = access.evaluate(p, ME); self.assertFalse(ok); self.assertIn("turned off", msg)
        self.assertTrue(access.evaluate(p, "0" * 12)[0]); self.assertTrue(access.evaluate(p, "x")[0])
    def test_allowlist(self):
        p = {"mode": "allowlist", "devices": {ME: {"enabled": True}}}
        self.assertTrue(access.evaluate(p, ME)[0]); self.assertFalse(access.evaluate(p, "0" * 12)[0])
        p["devices"][ME]["enabled"] = False; self.assertFalse(access.evaluate(p, ME)[0])
    def test_everyone_off(self):
        self.assertFalse(access.evaluate({"enabled": False, "message": "closed"}, ME)[0])
        self.assertEqual(access.evaluate({"enabled": False, "message": "closed"}, ME)[1], "closed")
    def test_junk_is_harmless(self):
        self.assertTrue(access.evaluate({"devices": [1, 2], "mode": 5}, ME)[0])


class Device(unittest.TestCase):
    def test_id_is_short_stable_and_hashed(self):
        a = access.device_id("RAW-UUID-1"); self.assertEqual(a, access.device_id("RAW-UUID-1"))
        self.assertRegex(a, r"^[0-9a-f]{12}$"); self.assertNotIn("RAW", a); self.assertNotEqual(a, access.device_id("RAW-UUID-2"))
    def test_real_id_and_name(self):
        self.assertRegex(access.device_id(), r"^[0-9a-f]{12}$"); self.assertTrue(access.device_name())


class Refresh(unittest.TestCase):
    def mk(self, fetcher, d=None):
        return access.Access(directory=d or tempfile.mkdtemp(), fetcher=fetcher, dev_id=ME, name="Test PC")
    def test_online_block_then_allow(self):
        pol = {"devices": {ME: {"enabled": False}}}
        a = self.mk(lambda: pol); self.assertEqual(a.state, "unknown"); self.assertTrue(a.allowed)
        a.refresh(); self.assertEqual((a.state, a.allowed, a.source), ("blocked", False, "online"))
        pol["devices"][ME]["enabled"] = True; a.refresh(); self.assertEqual((a.state, a.allowed), ("allowed", True))
    def test_offline_without_saved_copy_allows(self):
        def boom(): raise OSError("offline")
        a = self.mk(boom); a.refresh(); self.assertEqual(a.state, "unknown"); self.assertTrue(a.allowed)
    def test_offline_keeps_saved_block(self):
        d = tempfile.mkdtemp(); self.mk(lambda: {"devices": {ME: {"enabled": False}}}, d).refresh()
        def boom(): raise OSError("offline")
        b = self.mk(boom, d); self.assertEqual((b.state, b.source), ("blocked", "saved")); b.refresh(); self.assertFalse(b.allowed)
    def test_missing_file_means_allowed(self):
        a = self.mk(lambda: {}); a.refresh(); self.assertEqual(a.state, "allowed")
    def test_fetch_404_is_no_policy_and_other_errors_raise(self):
        def op404(req, t): raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        self.assertEqual(access.fetch("http://x/access.json", opener=op404), {})
        def op500(req, t): raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
        with self.assertRaises(urllib.error.HTTPError): access.fetch("http://x/access.json", opener=op500)
    def test_fetch_parses_json(self):
        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): return False
        self.assertEqual(access.fetch("http://x", opener=lambda req, t: R(b'{"enabled": false}')), {"enabled": False})
    def test_url_uses_repo(self):
        self.assertTrue(access.policy_url("a/b").endswith("/a/b/main/access.json"))


class AppGate(unittest.TestCase):
    def mkapp(self, policy):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), KR())
        acc = access.Access(directory=store.dir, fetcher=lambda: policy, dev_id=ME, name="Test PC")
        a = app.App(root, store, access_obj=acc); a.hk.stop(); return root, a, acc
    def test_blocked_device_cannot_capture_and_sees_message(self):
        import capture
        root, a, acc = self.mkapp({"devices": {ME: {"enabled": False}}, "message": "Switched off by Yousef"})
        acc.refresh(); a._update_access_ui(); a.store.set_key("sk-ant-x")
        called = []; orig = capture.grab_screen; capture.grab_screen = lambda *x, **k: called.append(1)
        try:
            a.start_capture()
            root.update()
        finally:
            capture.grab_screen = orig
        self.assertFalse(called); self.assertFalse(a.busy); self.assertIn("Switched off by Yousef", a.status.cget("text"))
        self.assertEqual(a.acc_status.cget("text"), "Turned off"); root.destroy()
    def test_allowed_device_card_and_copy(self):
        root, a, acc = self.mkapp({}); acc.refresh(); a._update_access_ui()
        self.assertEqual(a.acc_status.cget("text"), "Allowed"); a.copy_device_id()
        self.assertEqual(root.clipboard_get(), ME + " (Test PC)"); root.destroy()


class Tracker(unittest.TestCase):
    def mk(self, policy=None):
        a = access.Access(directory=tempfile.mkdtemp(), fetcher=lambda: policy or {}, dev_id=ME, name="Test PC")
        return a
    def test_server_url_comes_from_policy_and_must_be_https(self):
        a = self.mk({"server": "https://x.workers.dev/"}); a.refresh(); self.assertEqual(a.server, "https://x.workers.dev")
        b = self.mk({"server": "http://evil.example"}); b.refresh(); self.assertEqual(b.server, "")
        c = self.mk({}); c.refresh(); self.assertEqual(c.server, ""); self.assertIsNone(c.report("1.0.5", "mac"))   # nothing configured: no call
    def test_heartbeat_payload_has_no_secrets(self):
        a = self.mk({"server": "https://x.workers.dev"}); a.refresh(); a.note_capture(); a.note_capture(); seen = {}
        def post(url, body, t): seen["u"] = url; seen["b"] = json.loads(body); return {"allowed": True, "message": ""}
        a.report("1.0.5", "mac", "Ali", poster=post)
        self.assertEqual(seen["u"], "https://x.workers.dev/ping")
        self.assertEqual(sorted(seen["b"]), sorted(["id", "name", "display_name", "platform", "version", "captures", "last_capture"]))
        self.assertEqual((seen["b"]["id"], seen["b"]["name"], seen["b"]["display_name"], seen["b"]["captures"]), (ME, "Test PC", "Ali", 2))
    def test_owner_can_block_through_the_server_and_it_sticks_offline(self):
        d = tempfile.mkdtemp()
        a = access.Access(directory=d, fetcher=lambda: {"server": "https://x.workers.dev"}, dev_id=ME, name="PC"); a.refresh()
        a.report("1", "mac", "", poster=lambda u, b, t: {"allowed": False, "message": "Off by owner"})
        self.assertFalse(a.allowed); self.assertEqual((a.state, a.message), ("blocked", "Off by owner"))
        def boom(): raise OSError("offline")
        b = access.Access(directory=d, fetcher=boom, dev_id=ME, name="PC"); self.assertFalse(b.allowed); self.assertEqual(b.message, "Off by owner")
        a.report("1", "mac", "", poster=lambda u, b_, t: {"allowed": True, "message": ""}); self.assertTrue(a.allowed)
    def test_offline_heartbeat_is_silent_and_keeps_state(self):
        a = self.mk({"server": "https://x.workers.dev"}); a.refresh()
        def boom(u, b, t): raise OSError("down")
        self.assertIsNone(a.report("1", "mac", "", poster=boom)); self.assertTrue(a.allowed)
    def test_capture_count_survives_restart(self):
        d = tempfile.mkdtemp(); a = access.Access(directory=d, fetcher=lambda: {}, dev_id=ME); a.refresh(); a.note_capture(); a.note_capture()
        b = access.Access(directory=d, fetcher=lambda: {}, dev_id=ME); self.assertEqual(b.captures, 2); self.assertGreater(b.last_capture, 0)
    def test_app_reports_on_capture_and_saves_name(self):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), KR()); sent = []
        acc = access.Access(directory=store.dir, fetcher=lambda: {"server": "https://x.workers.dev"}, dev_id=ME, name="PC"); acc.refresh()
        acc.report = lambda v, p, n, **k: sent.append((v, p, n)) or {"allowed": True}
        a = app.App(root, store, access_obj=acc); a.hk.stop()
        a.dname_var.set("  Yousef  "); a.save_display_name()
        for _ in range(50):
            root.update(); import time; time.sleep(0.02)
            if sent: break
        self.assertEqual(store.load()["display_name"], "Yousef"); self.assertTrue(sent); self.assertEqual(sent[-1][2], "Yousef")
        root.destroy()


class WindowIcon(unittest.TestCase):
    def test_icon_file_is_a_real_multi_size_ico(self):
        import app
        from PIL import Image
        p = app.resource_path("icon.ico"); self.assertTrue(os.path.exists(p))
        im = Image.open(p); self.assertEqual(im.format, "ICO"); self.assertIn((16, 16), im.info["sizes"]); self.assertIn((256, 256), im.info["sizes"])
    def test_set_window_icon_never_crashes(self):
        import tkinter as tk, app
        root = tk.Tk(); self.assertIn(app.set_window_icon(root), (True, False)); root.destroy()   # Linux Tk can't use .ico: must fail softly
    def test_bundled_exe_looks_in_meipass(self):
        import app
        sys._MEIPASS = "/tmp/xyz"
        try: self.assertEqual(app.resource_path("icon.ico"), os.path.join("/tmp/xyz", "icon.ico"))
        finally: del sys._MEIPASS


class OwnerTool(unittest.TestCase):
    def test_cli_round_trip(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("owner_access", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "access.py"))
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        tool.PATH = os.path.join(tempfile.mkdtemp(), "access.json")
        tool.main(["block", ME, "--name", "Ali"]); d = json.load(open(tool.PATH))
        self.assertEqual(d["devices"][ME], {"name": "Ali", "enabled": False}); self.assertFalse(access.evaluate(d, ME)[0])
        tool.main(["allow", ME]); self.assertTrue(access.evaluate(json.load(open(tool.PATH)), ME)[0])
        tool.main(["mode", "allowlist"]); tool.main(["everyone", "off"]); tool.main(["message", "bye"]); d = json.load(open(tool.PATH))
        self.assertEqual((d["mode"], d["enabled"], d["message"]), ("allowlist", False, "bye"))
        with self.assertRaises(SystemExit): tool.main(["block", "nothex"])


if __name__ == "__main__":
    unittest.main()
