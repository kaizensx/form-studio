"""Cut the part out of real app screenshots, for the direction mockups.

The part pictures in docs/design/directions/assets are the app's own 3D view (Qt Quick 3D), taken from the
journey screenshots and keyed by colour: clay against the floor. Nothing is redrawn.

    .venv/bin/python docs/design/directions/tools/cutout.py <dir with after/dark and after/light screenshots>
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1] / "assets"
F = 1.44   # screenshots are 2880 wide; boxes below are in 2000-wide coordinates


def key(rgb, theme):
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    lum = (r + g + b) / 3
    if theme == "dark":
        return (lum > 84) & (r >= b - 2) & (r >= g - 3)
    return (r - g >= 0) & (r - b >= 2) & (lum < 216) & (lum > 60)


def cut(shot, theme, box, name, min_area=4000):
    im = Image.open(SRC / theme / shot).convert("RGB")
    x0, y0, x1, y1 = (int(v * F) for v in box)
    rgb = np.asarray(im.crop((x0, y0, x1, y1)))
    m = key(rgb, theme)
    m = ndi.binary_closing(m, iterations=3)
    m = ndi.binary_fill_holes(m)
    m = ndi.binary_opening(m, iterations=2)
    lab, n = ndi.label(m)
    sizes = ndi.sum(m, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= min_area])
    keep = ndi.binary_erosion(keep, iterations=1)
    ys, xs = np.where(keep)
    a = Image.fromarray((keep * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    out = Image.fromarray(rgb).convert("RGBA")
    out.putalpha(a)
    out = out.crop((xs.min() - 6, ys.min() - 6, xs.max() + 7, ys.max() + 7))
    out.save(OUT / name, optimize=True)
    print(name, out.size)


VIEW = (575, 150, 1415, 1130)
for theme in ("dark", "light"):
    cut("design-stage-shape.png", theme, VIEW, f"part-sensor-case-{theme}.png")
    cut("viewport-calm-growing-new-design.png", theme, VIEW, f"part-build-6of12-{theme}.png")
    cut("home-grid.png", theme, (170, 880, 565, 1170), f"thumb-echo-dock-{theme}.png", 1500)
    cut("home-grid.png", theme, (592, 880, 987, 1170), f"thumb-kilo-box-{theme}.png", 1500)
    cut("home-grid.png", theme, (1436, 880, 1831, 1170), f"thumb-bravo-bin-{theme}.png", 1500)
