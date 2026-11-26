"""h/compare.png: the workspaces of A, the hybrid H and B, side by side.

    .venv/bin/python docs/design/directions/tools/compare.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT.parents[2] / "form/app/assets/fonts/InstrumentSans.ttf"
COLS = [("a", "A  Lightbox", "full-bleed studio, floating glass"),
        ("h", "H  Lightdesk", "A's room and light, B's program listing and command line"),
        ("b", "B  Console", "command line, program listing, readouts")]
BG, INK, INK2 = (9, 9, 10), (240, 238, 234), (150, 148, 144)


def font(size, weight=600):
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_axes([weight, 100])
    except Exception:
        pass
    return f


def sheet(out, w=1440, h=900, pad=48, gap=36, head=96):
    W = pad * 2 + len(COLS) * w + (len(COLS) - 1) * gap
    im = Image.new("RGB", (W, pad + head + h + pad), BG)
    d = ImageDraw.Draw(im)
    for c, (k, name, note) in enumerate(COLS):
        x = pad + c * (w + gap)
        d.text((x, pad), name, font=font(40), fill=INK)
        d.text((x + d.textlength(name, font=font(40)) + 20, pad + 18), note, font=font(22, 400), fill=INK2)
        im.paste(Image.open(ROOT / k / "workspace-dark.png").convert("RGB").resize((w, h), Image.LANCZOS), (x, pad + head))
    im.save(out, optimize=True)
    print(out.relative_to(ROOT), im.size, out.stat().st_size // 1024, "kB")


sheet(ROOT / "h" / "compare.png")
