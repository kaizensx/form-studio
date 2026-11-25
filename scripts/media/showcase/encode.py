"""Crop and encode the chosen renders: WebP into site/assets/shots, JPEG into docs/readme, and brand/og-part.png.

    .venv/bin/python scripts/media/showcase/encode.py
    .venv/bin/python brand/build.py          # then: site/assets/og.png from brand/og-part.png

Reads .dev/showcase/out (SHOWCASE_WORK). Every picture on the page is listed in JOBS with its crop, so the framing is
kept with the source.
"""
import os
import sys
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[3]
S = Path(os.environ.get("SHOWCASE_WORK") or ROOT / ".dev" / "showcase") / "out"
SITE = ROOT / "site" / "assets" / "shots"
DOCS = ROOT / "docs" / "readme"
C = (0.11, 0.11, 0.89, 0.89)          # the middle of a frame: the camera leaves a wide margin
JOBS = [  # source, name, crop (l, t, r, b as fractions), width, quality
    ("hero_helmet-hero", "hero", (0.06, 0.17, 0.94, 0.83), 2400, 80),
    ("hero_helmet-hero", "hero-1200", (0.06, 0.17, 0.94, 0.83), 1200, 78),
    ("hero_helmet-asm", "helmet", (0.14, 0.10, 0.86, 0.82), 1400, 80),
    ("ratchet_wrench-ex", "ratchet", (0.12, 0.08, 0.92, 0.88), 1200, 80),
    ("cam_follower-as", "cam", (0.14, 0.14, 0.98, 0.94), 1200, 80),
    ("readme_planetary-as", "planetary", (0.10, 0.06, 0.90, 0.86), 1200, 80),
    ("spiral_vase-a", "vase", (0.20, 0.06, 0.80, 0.86), 1000, 80),
    ("perforated_lampshade-a", "shade", (0.16, 0.14, 0.84, 0.90), 1000, 80),
    ("cube_speaker-a", "speaker", (0.18, 0.12, 0.86, 0.92), 1000, 80),
    ("woven_basket-a", "basket", (0.12, 0.14, 0.88, 0.94), 1000, 80),
    ("bottle_and_cap-a", "bottle", (0.20, 0.08, 0.80, 0.88), 1000, 80),
    ("refine_before-a", "refine-before", C, 1200, 80),
    ("refine_after-a", "refine-after", C, 1200, 80),
    ("game-treasure_chest-hero", "game-chest", (0.10, 0.04, 0.90, 0.84), 1200, 82),
    ("game-treasure_chest-ladder", "game-lods", (0.03, 0.02, 0.99, 0.86), 2000, 82),
    ("game-vehicle_wheel-hero", "game-wheel", (0.14, 0.06, 0.94, 0.86), 1000, 80),
    ("recon-stepped_bracket-mesh", "recon-mesh", (0.0, 0.08, 1.0, 0.92), 1100, 84),
    ("recon-stepped_bracket-cad", "recon-cad", (0.0, 0.08, 1.0, 0.92), 1100, 84),
]
SITE.mkdir(parents=True, exist_ok=True)
for src, name, (l, t, r, b), w, q in JOBS:
    im = Image.open(S / f"{src}.png").convert("RGB")
    W, H = im.size
    im = im.crop((round(l * W), round(t * H), round(r * W), round(b * H)))
    if im.width > w:
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    im.save(SITE / f"{name}.webp", "WEBP", quality=q, method=6)
    print(name, im.size, (SITE / f"{name}.webp").stat().st_size)
# README: JPEG (GitHub shows it everywhere), the hero and a strip of four
h = Image.open(SITE / "hero.webp").convert("RGB")
h = h.resize((1656, round(1656 * h.height / h.width)), Image.LANCZOS)
h.save(DOCS / "hero-render.jpg", quality=86, optimize=True, progressive=True)
for n in ("planetary", "ratchet", "game-chest", "vase", "helmet", "cam", "bottle", "speaker"):
    im = Image.open(SITE / f"{n}.webp").convert("RGB")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2)).resize((800, 800), Image.LANCZOS)
    im.save(DOCS / f"made-{n}.jpg", quality=84, optimize=True, progressive=True)
# the social card: the hero helmet, square (brand/build.py fades its edges into the card)
Image.open(S / "hero_helmet-hero.png").convert("RGB").crop((690, 280, 2030, 1620)).resize((1000, 1000), Image.LANCZOS).save(ROOT / "brand" / "og-part.png", optimize=True)
print("readme and og-part ok")
