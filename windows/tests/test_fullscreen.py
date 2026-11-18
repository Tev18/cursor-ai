import io
import os
import tempfile
import unittest

os.environ["CURSORAI_ACCESS_SERVER"] = ""

import capture
import settings_store as ss


def png(w, h):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (w, h), "white").save(b, "PNG"); return b.getvalue()


class FakeKR:
    def __init__(self): self.d = {}
    def get_password(self, s, u): return self.d.get((s, u))
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def delete_password(self, s, u): self.d.pop((s, u), None)


class FullScreen(unittest.TestCase):
    def test_setting_default_and_persist(self):
        st = ss.SettingsStore(tempfile.mkdtemp(), FakeKR())
        self.assertFalse(st.load()["full_screen"])
        st.save({"full_screen": True}); self.assertTrue(st.load()["full_screen"])

    def test_full_box(self):
        self.assertEqual(capture.full_box(png(400, 300)), (0, 0, 400, 300))

    def test_capture_skips_selector(self):
        import time, tkinter as tk, app
        orig = (app.capture.grab_screen, app.selector.RegionSelector, app.claude_client.ask_about_image)
        self.addCleanup(lambda: (setattr(app.capture, "grab_screen", orig[0]), setattr(app.selector, "RegionSelector", orig[1]), setattr(app.claude_client, "ask_about_image", orig[2])))
        root = tk.Tk(); st = ss.SettingsStore(tempfile.mkdtemp(), FakeKR()); st.set_key("k"); st.save({"full_screen": True})
        a = app.App(root, st)
        seen = []
        app.capture.grab_screen = lambda *x, **y: png(400, 300)
        def boom(*x, **y): raise AssertionError("selector must not open")
        app.selector.RegionSelector = boom
        app.claude_client.ask_about_image = lambda k, p, *x, **y: seen.append(p) or "OK"
        a.access.approved = True; a.access._pol_allowed = True; a.access.remote_blocked = False
        a.start_capture()
        for _ in range(60): root.update(); time.sleep(0.05)
        self.assertEqual(a.answer.text.cget("text"), "OK")
        from PIL import Image
        self.assertEqual(Image.open(io.BytesIO(seen[0])).size, (400, 300))
        a.hk.stop(); root.destroy()


if __name__ == "__main__":
    unittest.main()
