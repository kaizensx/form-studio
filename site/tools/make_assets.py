"""Prepare the website's static assets from files already in the repository.

    python site/tools/make_assets.py        (needs pillow, fonttools and brotli; run from the repository root)

- fonts: the app's Instrument Sans and Geist Mono (form/app/assets/fonts), subset to Latin and written as woff2
- shots: crops of docs/screenshots/app-*.jpg as webp, at the size the page shows them
- icons: favicon and touch icon from form/app/assets/icon.png
- vendor: three.js and OrbitControls from form/web/vendor (the copy the bench already ships)

The output is committed, so the GitHub Pages workflow does not need any of these tools.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
SHOTS = ROOT / "docs" / "screenshots"

UNICODES = ("U+0020-007E,U+00A0-00FF,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2022,U+2026,U+2190-2194,"
            "U+2197,U+00D7,U+00B1,U+00B7,U+2264,U+2265,U+2318,U+00D8,U+00B3,U+00B2,U+2212,U+0394,U+25B8,U+2713,U+2717")

# name: (source, crop box in source pixels or None, output width)
CROPS = {
    "chat": ("app-chat.jpg", (0, 56, 1300, 1160), 1300),
    "chat-talk": ("app-chat.jpg", (0, 56, 424, 820), 424),
    "draft": ("app-chat.jpg", (1300, 740, 1800, 1160), 500),
    "viewport": ("app-shape.jpg", (424, 56, 1800, 1160), 1376),
    "fit": ("app-fit.jpg", (424, 56, 1800, 1160), 1376),
    "fit-panel": ("app-fit.jpg", (1300, 136, 1800, 900), 500),
    "layers": ("app-layers.jpg", (424, 56, 1300, 1160), 876),
    "layers-wide": ("app-layers.jpg", (424, 56, 1800, 1160), 1376),
    "checks": ("app-layers.jpg", (1300, 136, 1800, 1160), 500),
    "assembly": ("app-assembly.jpg", (424, 56, 1300, 1160), 876),
    "release": ("app-release.jpg", (1300, 136, 1800, 1160), 500),
    "release-wide": ("app-release.jpg", (424, 56, 1800, 1160), 1376),
    "welcome": ("app-welcome.jpg", (380, 56, 1420, 1160), 1040),
    "slicers": ("app-slicers.jpg", (424, 56, 1800, 1160), 1376),
    "home": ("app-home.jpg", (500, 56, 1800, 940), 1300),
    "reference": ("app-reference-part.jpg", (424, 56, 1300, 1160), 876),
    "enclosure": ("app-enclosure.jpg", (424, 56, 1300, 1160), 876),
    "render": ("app-render-sheet.jpg", (200, 96, 1600, 1060), 1400),
    "app": ("app-chat.jpg", None, 1800),
    "app-m": ("app-chat.jpg", (424, 56, 1300, 1160), 876),
    "analysis": ("app-thickness.jpg", (424, 56, 1300, 1160), 876),
    "measure": ("app-measure.jpg", (424, 56, 1300, 1160), 876),
}


def fonts() -> None:
    out = SITE / "fonts"
    out.mkdir(parents=True, exist_ok=True)
    src = ROOT / "form" / "app" / "assets" / "fonts"
    for name in ("InstrumentSans", "GeistMono"):
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "calt", "tnum", "zero", "ss01", "case", "frac"]
        opts.unicodes = subset.parse_unicodes(UNICODES)
        font = TTFont(src / f"{name}.ttf")
        s = subset.Subsetter(opts)
        s.populate(unicodes=opts.unicodes)
        s.subset(font)
        font.flavor = "woff2"
        font.save(out / f"{name}.woff2")
        shutil.copy(src / f"{name}-LICENSE.txt", out / f"{name}-LICENSE.txt")
        print("font", name, (out / f"{name}.woff2").stat().st_size // 1024, "KB")


def shots() -> None:
    out = SITE / "assets" / "shots"
    out.mkdir(parents=True, exist_ok=True)
    for name, (src, box, width) in CROPS.items():
        im = Image.open(SHOTS / src).convert("RGB")
        if box:
            im = im.crop(box)
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(out / f"{name}.webp", "WEBP", quality=84, method=6)
        print("shot", name, im.size, (out / f"{name}.webp").stat().st_size // 1024, "KB")
    for src, name in (("render-dock-studio.jpg", "render-dock"), ("pi5-case-by-claude.png", "pi5-case")):
        im = Image.open(ROOT / "docs" / "assets" / src).convert("RGB")
        im.save(out / f"{name}.webp", "WEBP", quality=84, method=6)
        print("shot", name, im.size, (out / f"{name}.webp").stat().st_size // 1024, "KB")


def icons() -> None:
    icon = Image.open(ROOT / "form" / "app" / "assets" / "icon.png").convert("RGBA")
    icon.resize((180, 180), Image.LANCZOS).save(SITE / "assets" / "apple-touch-icon.png")
    icon.resize((192, 192), Image.LANCZOS).save(SITE / "assets" / "icon-192.png")
    icon.resize((48, 48), Image.LANCZOS).save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    icon.resize((64, 64), Image.LANCZOS).save(SITE / "assets" / "favicon.png")


def vendor() -> None:
    out = SITE / "vendor"
    out.mkdir(parents=True, exist_ok=True)
    for f in ("three.module.js", "OrbitControls.js", "THREE_LICENSE"):
        shutil.copy(ROOT / "form" / "web" / "vendor" / f, out / f)


if __name__ == "__main__":
    fonts()
    shots()
    icons()
    vendor()
