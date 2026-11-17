#!/usr/bin/env python3
"""Draws the Cursor AI app icon (gold rounded square, dark pointer) and writes
mac/icon.icns, mac/icon.png and windows/icon.ico. Needs Pillow.   python3 tools/make_icon.py"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD, GOLD_HI, DARK = (212, 175, 55), (234, 200, 92), (22, 19, 10)


def draw(size=1024, margin=0.0):
    S = size * 2                                   # draw big, shrink for smooth edges
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    m = int(S * margin)
    box = (m, m, S - m, S - m)
    side = S - 2 * m
    # vertical gold gradient clipped to a rounded square
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=tuple(round(GOLD_HI[i] + (GOLD[i] - GOLD_HI[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=int(side * 0.225), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    k = side / 48.0
    ox = oy = m
    pts = [(15, 11), (15, 34), (21, 28.5), (25.5, 38), (30, 36), (25.5, 27), (33.5, 27)]
    d.polygon([(ox + x * k, oy + y * k) for x, y in pts], fill=DARK)
    d.line([(ox + x * k, oy + y * k) for x, y in pts + [pts[0]]], fill=DARK, width=max(1, int(k * 1.2)), joint="curve")
    for cx, cy, r in ((35, 14, 2.4), (39.5, 20, 1.5)):                       # sparkles
        d.ellipse([ox + (cx - r) * k, oy + (cy - r) * k, ox + (cx + r) * k, oy + (cy + r) * k], fill=DARK)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    mac = draw(1024, margin=0.098)                 # macOS icons leave ~10% transparent margin
    mac.save(os.path.join(ROOT, "mac", "icon.png"))
    mac.save(os.path.join(ROOT, "mac", "icon.icns"), format="ICNS")
    win = draw(256, margin=0.03)
    win.save(os.path.join(ROOT, "windows", "icon.ico"), format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote mac/icon.png, mac/icon.icns, windows/icon.ico")
