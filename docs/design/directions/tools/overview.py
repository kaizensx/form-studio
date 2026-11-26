"""overview.png: the three workspace mockups side by side, and overview-all.png: every screen of every direction.

    .venv/bin/python docs/design/directions/tools/overview.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT.parents[2] / "form/app/assets/fonts/InstrumentSans.ttf"
NAMES = {"a": "A  Lightbox", "b": "B  Console", "c": "C  Atelier"}
NOTES = {"a": "full-bleed studio, floating glass", "b": "command line, program listing, readouts", "c": "notebook and gallery, serif, vermilion"}
BG, INK, INK2 = (9, 9, 10), (240, 238, 234), (150, 148, 144)


def font(size, weight=600):
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_axes([weight, 100])
    except Exception:
        pass
    return f


def sheet(rows, out, w=1440, h=900, pad=48, gap=36, head=96):
    cols = 3
    W = pad * 2 + cols * w + (cols - 1) * gap
    H = pad + head + len(rows) * (h + gap) - gap + pad
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for c, k in enumerate("abc"):
        x = pad + c * (w + gap)
        d.text((x, pad), NAMES[k], font=font(40), fill=INK)
        d.text((x + d.textlength(NAMES[k], font=font(40)) + 20, pad + 18), NOTES[k], font=font(22, 400), fill=INK2)
        for r, name in enumerate(rows):
            shot = Image.open(ROOT / k / name).convert("RGB").resize((w, h), Image.LANCZOS)
            im.paste(shot, (x, pad + head + r * (h + gap)))
    im.save(out, optimize=True)
    print(out.relative_to(ROOT), im.size)


sheet(["workspace-dark.png"], ROOT / "overview.png")
sheet(["workspace-dark.png", "build-dark.png", "home-dark.png", "workspace-light.png"], ROOT / "overview-all.png", w=960, h=600, pad=40, gap=24, head=84)
