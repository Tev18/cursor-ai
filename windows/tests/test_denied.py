import os
import unittest

os.environ["CURSORAI_ACCESS_SERVER"] = ""

import tkinter as tk

import denied


class Denied(unittest.TestCase):
    def test_shows_and_closes(self):
        root = tk.Tk()
        try:
            win = denied.show(root, "Turned off")
            root.update()
            texts = [w.cget("text") for w in win.winfo_children()[0].winfo_children()]
            self.assertEqual(texts[0], "ACCESS DENIED")
            self.assertIn("Turned off", texts)
            win.event_generate("<Button-1>")
            root.update()
            self.assertFalse(win.winfo_exists())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
