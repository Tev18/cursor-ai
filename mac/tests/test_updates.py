"""Key visibility + update system tests (no real network: a local fake GitHub serves the releases)."""
import base64, hashlib, http.server, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings_store as ss, updater, version


class KR:
    def __init__(s): s.d = {}
    def get_password(s, a, b): return s.d.get((a, b))
    def set_password(s, a, b, v): s.d[(a, b)] = v
    def delete_password(s, a, b): s.d.pop((a, b), None)


# ---------------- a tiny fake GitHub ----------------
class Fake:
    def __init__(self, tag="v1.1.0", private=True, token="tok", payload=b"NEW-APP", sign=True, tamper=False):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.priv = Ed25519PrivateKey.generate()
        raw = self.priv.public_key().public_bytes_raw()
        self.pub_b64 = base64.b64encode(raw).decode()
        self.tag, self.private, self.token = tag, private, token
        self.cdn_auth = []          # Authorization headers seen by the "CDN" host
        d = tempfile.mkdtemp()
        zpath = os.path.join(d, "Cursor-AI-%s-%s.zip" % (updater.platform_key(), tag))
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("Cursor AI.exe" if sys.platform == "win32" else "Cursor AI.exe", payload)
        self.zip = open(zpath, "rb").read()
        self.zname = os.path.basename(zpath)
        self.sums = ("%s  %s\n" % (hashlib.sha256(self.zip).hexdigest(), self.zname)).encode()
        if tamper:
            self.zip = self.zip + b"x"
        self.sig = base64.b64encode(self.priv.sign(open(zpath, "rb").read())) if sign else None
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _auth_ok(self):
                return not fake.private or self.headers.get("Authorization") == "Bearer " + fake.token
            def do_GET(self):
                base = "http://127.0.0.1:%d" % self.server.server_port
                if self.path.startswith("/cdn/"):
                    fake.cdn_auth.append(self.headers.get("Authorization"))
                    return self._send(fake.blob(self.path[5:]))
                if not self._auth_ok():
                    self.send_response(404); self.end_headers(); return
                if self.path == "/repos/o/r/releases/latest":
                    assets = [{"name": fake.zname, "size": len(fake.zip), "url": base + "/assets/zip"},
                              {"name": "SHA256SUMS.txt", "size": len(fake.sums), "url": base + "/assets/sums"}]
                    if fake.sig: assets.append({"name": fake.zname + ".sig", "size": len(fake.sig), "url": base + "/assets/sig"})
                    body = json.dumps({"tag_name": fake.tag, "body": "## Notes\n- shiny", "html_url": base + "/rel", "assets": assets}).encode()
                    return self._send(body, "application/json")
                if self.path.startswith("/assets/"):
                    self.send_response(302)    # like GitHub: redirect to a signed CDN URL on another host
                    self.send_header("Location", "http://localhost:%d/cdn/%s" % (self.server.server_port, self.path[8:]))
                    self.end_headers(); return
                self.send_response(404); self.end_headers()
            def _send(self, body, ctype="application/octet-stream"):
                self.send_response(200); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.api = "http://127.0.0.1:%d" % self.srv.server_port

    def blob(self, name): return {"zip": self.zip, "sums": self.sums, "sig": self.sig or b""}[name]
    def close(self): self.srv.shutdown(); self.srv.server_close()


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.is_newer("v1.1.0", "1.0.0")); self.assertTrue(updater.is_newer("2.0", "1.9.9"))
        self.assertFalse(updater.is_newer("v1.0.0", "1.0.0")); self.assertFalse(updater.is_newer("0.9.9", "1.0.0"))
        self.assertTrue(updater.is_newer("1.0.0", "1.0.0-beta.1")); self.assertFalse(updater.is_newer("1.1.0-rc1", "1.1.0"))
        self.assertTrue(updater.is_newer("v1.10.0", "v1.9.0"))                      # numeric, not alphabetic
        with self.assertRaises(updater.UpdateError): updater.parse_version("banana")
    def test_not_configured_until_repo_is_set(self):
        self.assertFalse(updater.configured("OWNER/cursor-ai")); self.assertTrue(updater.configured("me/cursor-ai"))
        with self.assertRaises(updater.UpdateError): updater.check_latest(repo="OWNER/cursor-ai")
    def test_version_file_is_semver(self):
        updater.parse_version(version.VERSION)


class Github(unittest.TestCase):
    def test_check_download_verify_private_repo_token_not_leaked(self):
        f = Fake(); self.addCleanup(f.close)
        with self.assertRaises(updater.UpdateError) as c: updater.check_latest("o/r", None, "1.0.0", f.api)       # private + no token
        self.assertIn("token", str(c.exception))
        info = updater.check_latest("o/r", "tok", "1.0.0", f.api)
        self.assertTrue(info["newer"]); self.assertEqual(info["version"], "1.1.0"); self.assertIn("shiny", info["notes"])
        self.assertTrue(info["asset"] and info["sums"] and info["sig"])
        seen = []; d = tempfile.mkdtemp()
        path = updater.download(info["asset"], d, "tok", lambda a, b: seen.append((a, b)))
        self.assertEqual(open(path, "rb").read(), f.zip); self.assertEqual(seen[-1][0], len(f.zip))
        self.assertEqual(f.cdn_auth, [None])                                                                      # token never went to the CDN host
        self.assertTrue(updater.verify_sha256(path, updater.fetch_text(info["sums"], "tok")))
        self.assertTrue(updater.verify_signature(path, updater.fetch_text(info["sig"], "tok"), f.pub_b64))
    def test_up_to_date(self):
        f = Fake(tag="v1.0.0", private=False); self.addCleanup(f.close)
        self.assertFalse(updater.check_latest("o/r", None, "1.0.0", f.api)["newer"])
    def test_network_down(self):
        with self.assertRaises(updater.UpdateError) as c: updater.check_latest("o/r", None, "1.0.0", "http://127.0.0.1:9")
        self.assertIn("reach", str(c.exception))
    def test_cancel_and_truncation(self):
        f = Fake(private=False); self.addCleanup(f.close)
        info = updater.check_latest("o/r", None, "1.0.0", f.api)
        with self.assertRaises(updater.UpdateError): updater.download(info["asset"], tempfile.mkdtemp(), None, cancelled=lambda: True)
        bad = dict(info["asset"]); bad["size"] = len(f.zip) + 5
        with self.assertRaises(updater.UpdateError): updater.download(bad, tempfile.mkdtemp())


class Verify(unittest.TestCase):
    def test_tampered_zip_rejected_by_checksum_and_signature(self):
        f = Fake(tamper=True, private=False); self.addCleanup(f.close)
        info = updater.check_latest("o/r", None, "1.0.0", f.api); d = tempfile.mkdtemp()
        path = updater.download(info["asset"], d)
        with self.assertRaises(updater.UpdateError) as c: updater.verify_sha256(path, f.sums); self.assertIn("mismatch", str(c.exception))
        with self.assertRaises(updater.UpdateError) as c2: updater.verify_signature(path, f.sig, f.pub_b64)
        self.assertIn("not signed by the publisher", str(c2.exception))
    def test_signature_from_other_key_and_missing_signature(self):
        f = Fake(private=False); g = Fake(private=False); self.addCleanup(f.close); self.addCleanup(g.close)
        p = os.path.join(tempfile.mkdtemp(), "x.zip"); open(p, "wb").write(f.zip)
        with self.assertRaises(updater.UpdateError): updater.verify_signature(p, g.sig, f.pub_b64)
        with self.assertRaises(updater.UpdateError): updater.verify_signature(p, None, f.pub_b64)                 # key configured => signature required
        self.assertFalse(updater.verify_signature(p, None, ""))                                                  # no key configured: reports "not signature-checked"
    def test_missing_checksum_entry(self):
        p = os.path.join(tempfile.mkdtemp(), "x.zip"); open(p, "wb").write(b"1")
        with self.assertRaises(updater.UpdateError): updater.verify_sha256(p, "abc  other.zip")


class Install(unittest.TestCase):
    def run_script(self, new_exists=True):
        """Runs the real swap script against a fake .app directory."""
        root = tempfile.mkdtemp(); target = os.path.join(root, "Cursor AI.app"); work = os.path.join(root, ".work")
        os.makedirs(target); open(os.path.join(target, "v"), "w").write("old")
        os.makedirs(work); new = os.path.join(work, "Cursor AI.app")
        if new_exists: os.makedirs(new); open(os.path.join(new, "v"), "w").write("new")
        dead = subprocess.Popen(["true"]); dead.wait()
        marker = os.path.join(root, "opened"); os.environ["OPEN_CMD"] = "/bin/echo"
        saved = sys.platform
        cmd = updater.install({"new": new, "target": target, "dir": work}, pid=dead.pid)
        for _ in range(60):
            time.sleep(0.1)
            if not os.path.exists(cmd[1]): break
        return root, target, work
    def test_swap_keeps_backup_until_done_then_cleans(self):
        root, target, work = self.run_script()
        self.assertEqual(open(os.path.join(target, "v")).read(), "new")
        self.assertFalse(os.path.exists(target + ".previous")); self.assertFalse(os.path.exists(work))
    def test_failed_swap_rolls_back(self):
        root, target, work = self.run_script(new_exists=False)
        self.assertEqual(open(os.path.join(target, "v")).read(), "old")                                         # old app restored
    def test_stage_rejects_unwritable_and_path_traversal(self):
        d = tempfile.mkdtemp(); z = os.path.join(d, "a.zip")
        with zipfile.ZipFile(z, "w") as zf: zf.writestr("../evil.exe", b"x")
        target = os.path.join(d, "Cursor AI.exe"); open(target, "w").close()
        with self.assertRaises(updater.UpdateError): updater.stage(z, target)
        self.assertEqual([p for p in os.listdir(d) if p.startswith(".cursor-ai-update-")], [])                   # temp dir cleaned
        with zipfile.ZipFile(z, "w") as zf: zf.writestr("Cursor AI.exe", b"fine")
        st = updater.stage(z, target); self.assertEqual(open(st["new"], "rb").read(), b"fine"); updater.discard(st)
    def test_current_target_only_when_packaged(self):
        self.assertIsNone(updater.current_target())
    def test_auto_check_interval(self):
        self.assertTrue(updater.should_auto_check(0)); self.assertFalse(updater.should_auto_check(time.time()))
        self.assertTrue(updater.should_auto_check(time.time() - 90000))


class Settings(unittest.TestCase):
    def test_defaults_and_token_storage(self):
        d = tempfile.mkdtemp(); s = ss.SettingsStore(d, KR())
        self.assertTrue(s.load()["auto_update_check"]); self.assertEqual(s.load()["update_last_check"], 0)
        s.set_token("ghp_x"); self.assertEqual(s.get_token(), "ghp_x"); s.delete_token(); self.assertIsNone(s.get_token())
        s.set_key("sk-ant-keep"); s.save({"model": "claude-haiku-5-5", "opacity": 0.4, "auto_update_check": False})
        self.assertEqual(s.get_key(), "sk-ant-keep")                                                             # unrelated settings never erase the key
        self.assertNotIn("sk-ant", open(s.settings_path).read())


class AppKey(unittest.TestCase):
    def make(self, key=None):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), KR())
        if key: store.set_key(key)
        a = app.App(root, store); root.update(); return root, a, store
    def test_saved_key_loads_masked_and_show_hide_toggles(self):
        K = "sk-ant-api03-REALKEY1234567890"; root, a, store = self.make(K)
        self.assertEqual(a.key_var.get(), K); self.assertEqual(a.key_entry.cget("show"), "•"); self.assertEqual(a.show_btn._text, "Show")
        a.show_btn.invoke(); self.assertEqual(a.key_entry.cget("show"), ""); self.assertEqual(a.key_entry.get(), K); self.assertEqual(a.show_btn._text, "Hide")
        a.show_btn.invoke(); self.assertEqual(a.key_entry.cget("show"), "•"); self.assertEqual(a.show_btn._text, "Show")
        a.hk.stop(); root.destroy()
    def test_hides_on_reopen_and_not_kept_in_field_while_window_hidden(self):
        K = "sk-ant-api03-REALKEY1234567890"; root, a, store = self.make(K)
        a.show_btn.invoke(); self.assertEqual(a.key_entry.cget("show"), "")
        a.hide_main(); self.assertEqual(root.state(), "withdrawn"); self.assertEqual(a.key_var.get(), "")       # not retained while hidden
        self.assertEqual(store.get_key(), K)
        a.show_main(); root.update(); self.assertEqual(a.key_entry.cget("show"), "•"); self.assertEqual(a.key_var.get(), K)   # masked again, reloaded
        a.hk.stop(); root.destroy()
    def test_unsaved_new_key_survives_close_and_can_replace(self):
        root, a, store = self.make("sk-ant-old-1234567890")
        a.key_var.set("sk-ant-new-0987654321"); a.hide_main(); a.show_main()
        self.assertEqual(a.key_var.get(), "sk-ant-new-0987654321"); self.assertEqual(store.get_key(), "sk-ant-old-1234567890")
        a.save_key(); self.assertEqual(store.get_key(), "sk-ant-new-0987654321"); self.assertEqual(a.key_var.get(), "sk-ant-new-0987654321")
        a.cancel(); self.assertEqual(a.key_var.get(), "sk-ant-new-0987654321")
        a.hk.stop(); root.destroy()
    def test_other_settings_never_erase_key_and_remove_works(self):
        root, a, store = self.make("sk-ant-keepme-1234567890")
        a.model_var.set("claude-opus-5-5"); a.save_settings(); a.op_scale._apply(0.5); a._opacity_released(); a._top_changed(False)
        self.assertEqual(store.get_key(), "sk-ant-keepme-1234567890"); self.assertEqual(a.key_var.get(), "sk-ant-keepme-1234567890")
        a.remove_key(); self.assertIsNone(store.get_key()); self.assertEqual(a.key_var.get(), "")
        a.hk.stop(); root.destroy()
    def test_no_placeholder_when_nothing_saved_and_test_uses_field(self):
        import app
        root, a, store = self.make(); self.assertEqual(a.key_var.get(), ""); a.show_btn.invoke(); self.assertEqual(a.key_entry.get(), "")
        got = []; orig = app.claude_client.test_key; self.addCleanup(lambda: setattr(app.claude_client, "test_key", orig))
        app.claude_client.test_key = lambda k, m: got.append(k) or "ok"
        a.key_var.set("typed-but-unsaved"); a.test_key()
        for _ in range(20): root.update(); time.sleep(0.05)
        self.assertEqual(got, ["typed-but-unsaved"]); a.hk.stop(); root.destroy()


class AppUpdates(unittest.TestCase):
    def make(self, **saved):
        import tkinter as tk, app
        root = tk.Tk(); store = ss.SettingsStore(tempfile.mkdtemp(), KR())
        if saved: store.save(saved)
        a = app.App(root, store); root.update(); return root, a, store
    def pump(self, root, a, n=40):
        for _ in range(n): root.update(); time.sleep(0.03)
    def test_card_shows_version_and_controls(self):
        root, a, _ = self.make(); self.assertIn(version.VERSION, a.ver_installed.cget("text")); self.assertFalse(a.install_btn.enabled)
        self.assertEqual(a.upd_bar.value, 0); self.assertTrue(a.auto_var.get())
        a.auto_switch.toggle(); self.assertFalse(a.store.load()["auto_update_check"])
        a.hk.stop(); root.destroy()
    def test_up_to_date_and_update_available_and_errors_against_fake_github(self):
        import app
        f = Fake(tag="v1.0.0", private=False); self.addCleanup(f.close)
        root, a, store = self.make()
        real = updater.check_latest; self.addCleanup(lambda: setattr(updater, "check_latest", real))
        updater.check_latest = lambda token=None: real("o/r", token, "1.0.0", f.api)
        t0 = time.time(); a.check_btn.invoke(); self.assertLess(time.time() - t0, 0.3); self.assertFalse(a.check_btn.enabled)   # async + locked
        self.pump(root, a); self.assertIn("up to date", a.upd_status.cget("text")); self.assertFalse(a.install_btn.enabled); self.assertTrue(a.check_btn.enabled)
        self.assertGreater(store.load()["update_last_check"], 0)
        f.tag = "v1.2.0"; a.check_btn.invoke(); self.pump(root, a)
        self.assertIn("v1.2.0", a.upd_status.cget("text")); self.assertTrue(a.install_btn.enabled); self.assertIn("shiny", a.notes.get("1.0", "end"))
        self.assertIn("1.2.0", a.ver_latest.cget("text"))
        updater.check_latest = lambda token=None: real("o/r", token, "1.0.0", "http://127.0.0.1:9")
        a.check_btn.invoke(); self.pump(root, a); self.assertIn("Couldn't", a.upd_status.cget("text")); self.assertIn("reach", a.status.cget("text"))
        a.hk.stop(); root.destroy()
    def test_install_flow_download_verify_confirm_restart(self):
        import app
        f = Fake(tag="v1.2.0", private=True); self.addCleanup(f.close)
        root, a, store = self.make(); store.set_token("tok"); store.set_key("sk-ant-survive-me-123")
        folder = tempfile.mkdtemp(); target = os.path.join(folder, "Cursor AI.exe"); open(target, "w").write("old")
        real = (updater.check_latest, updater.current_target, updater.install, version.UPDATE_PUBLIC_KEY)
        def restore(): updater.check_latest, updater.current_target, updater.install, version.UPDATE_PUBLIC_KEY = real
        self.addCleanup(restore)
        updater.check_latest = lambda token=None: real[0]("o/r", token, "1.0.0", f.api)
        updater.current_target = lambda: target; version.UPDATE_PUBLIC_KEY = f.pub_b64
        a.check_btn.invoke(); self.pump(root, a); self.assertTrue(a.install_btn.enabled)
        asked, installed, quits = [], [], []
        a._confirm = lambda title, msg: asked.append(msg) or True
        updater.install = lambda staged, pid=None: installed.append(staged)
        a.quit = lambda: quits.append(1)
        a.install_btn.invoke(); self.assertFalse(a.install_btn.enabled); self.assertFalse(a.check_btn.enabled)
        self.pump(root, a, 80)
        self.assertEqual(len(asked), 1); self.assertIn("1.2.0", asked[0]); self.assertIn("publisher signature", asked[0]); self.assertIn("settings and API key are kept", asked[0])
        self.assertEqual(len(installed), 1); self.assertEqual(open(installed[0]["new"], "rb").read(), b"NEW-APP"); self.assertEqual(a.upd_bar.value, 1.0)
        self.assertEqual(quits, [1])
        self.assertEqual(store.get_key(), "sk-ant-survive-me-123"); self.assertEqual(store.load()["model"], "claude-sonnet-5-5")   # settings + key untouched by an update
        shutil.rmtree(installed[0]["dir"], ignore_errors=True); a.hk.stop(); root.destroy()
    def test_declining_confirmation_installs_nothing_and_unlocks(self):
        f = Fake(tag="v1.2.0", private=False); self.addCleanup(f.close)
        root, a, store = self.make(); folder = tempfile.mkdtemp(); target = os.path.join(folder, "Cursor AI.exe"); open(target, "w").write("old")
        real = (updater.check_latest, updater.current_target, updater.install, version.UPDATE_PUBLIC_KEY)
        self.addCleanup(lambda: (setattr(updater, "check_latest", real[0]), setattr(updater, "current_target", real[1]), setattr(updater, "install", real[2]), setattr(version, "UPDATE_PUBLIC_KEY", real[3])))
        updater.check_latest = lambda token=None: real[0]("o/r", token, "1.0.0", f.api); updater.current_target = lambda: target; version.UPDATE_PUBLIC_KEY = ""
        called = []; updater.install = lambda *x, **k: called.append(1)
        a.check_btn.invoke(); self.pump(root, a); a._confirm = lambda t, m: False
        a.install_btn.invoke(); self.pump(root, a, 80)
        self.assertEqual(called, []); self.assertTrue(a.install_btn.enabled and a.check_btn.enabled); self.assertIn("cancelled", a.upd_status.cget("text"))
        self.assertEqual([p for p in os.listdir(folder) if p.startswith(".cursor-ai-update-")], [])
        a.hk.stop(); root.destroy()
    def test_tampered_download_is_refused(self):
        f = Fake(tag="v1.2.0", private=False, tamper=True); self.addCleanup(f.close)
        root, a, store = self.make(); folder = tempfile.mkdtemp(); target = os.path.join(folder, "Cursor AI.exe"); open(target, "w").write("old")
        real = (updater.check_latest, updater.current_target)
        self.addCleanup(lambda: (setattr(updater, "check_latest", real[0]), setattr(updater, "current_target", real[1])))
        updater.check_latest = lambda token=None: real[0]("o/r", token, "1.0.0", f.api); updater.current_target = lambda: target
        a.check_btn.invoke(); self.pump(root, a); asked = []; a._confirm = lambda t, m: asked.append(1) or True
        # the fake serves a zip that is 1 byte longer than advertised: refused as a cut/damaged download
        a.install_btn.invoke(); self.pump(root, a, 80)
        self.assertEqual(asked, []); self.assertIn("failed", a.upd_status.cget("text")); self.assertEqual(open(target).read(), "old")
        a.hk.stop(); root.destroy()
    def test_install_from_source_run_explains(self):
        f = Fake(tag="v1.2.0", private=False); self.addCleanup(f.close)
        root, a, _ = self.make(); real = updater.check_latest; self.addCleanup(lambda: setattr(updater, "check_latest", real))
        updater.check_latest = lambda token=None: real("o/r", token, "1.0.0", f.api)
        a.check_btn.invoke(); self.pump(root, a); a.install_btn.invoke()
        self.assertIn("packaged app", a.status.cget("text")); a.hk.stop(); root.destroy()
    def test_unconfigured_repo_message(self):
        root, a, _ = self.make(); a.check_btn.invoke(); self.pump(root, a)
        self.assertIn("aren't set up", a.status.cget("text")); a.hk.stop(); root.destroy()


if __name__ == "__main__":
    unittest.main()
