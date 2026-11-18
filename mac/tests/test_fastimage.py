import io
import os
import unittest

os.environ["CURSORAI_ACCESS_SERVER"] = ""

import capture
import claude_client


def noisy_png(w, h):
    from PIL import Image
    b = io.BytesIO(); Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(b, "PNG"); return b.getvalue()


class FastImage(unittest.TestCase):
    def test_big_capture_is_small_jpeg(self):
        from PIL import Image
        src = noisy_png(3000, 2000)
        out = capture.crop_and_downscale(src, (0, 0, 3000, 2000))
        self.assertEqual(out[:3], b"\xff\xd8\xff")
        self.assertLessEqual(max(Image.open(io.BytesIO(out)).size), capture.MAX_EDGE)
        self.assertLess(len(out), capture.MAX_BYTES)

    def test_media_type_follows_bytes(self):
        seen = []
        class R:
            status_code = 200
            def json(s): return {"content": [{"type": "text", "text": "x"}]}
        class H:
            def post(s, url, **kw): seen.append(kw["json"]["messages"][0]["content"][0]["source"]["media_type"]); return R()
        jpg = capture.crop_and_downscale(noisy_png(100, 100), (0, 0, 100, 100))
        claude_client.ask_about_image("k", jpg, "m", "q", http=H())
        claude_client.ask_about_image("k", noisy_png(10, 10), "m", "q", http=H())
        self.assertEqual(seen, ["image/jpeg", "image/png"])


if __name__ == "__main__":
    unittest.main()
