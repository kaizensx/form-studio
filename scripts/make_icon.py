"""Draw FORM's app icon: a clay block on a graphite plate with one drawn dimension. Run: python scripts/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 4                      # supersample
N = 1024 * S
OUT = Path(__file__).resolve().parents[1] / "form" / "app" / "assets"


def main():
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    m = int(N * 0.098)                       # macOS icon grid margin
    box = (m, m, N - m, N - m)
    r = int((N - 2 * m) * 0.225)
    # plate: vertical graphite gradient inside a rounded square
    grad = Image.new("RGBA", (N, N))
    gd = ImageDraw.Draw(grad)
    for y in range(N):
        t = y / N
        gd.line([(0, y), (N, y)], fill=(int(30 - 14 * t), int(36 - 16 * t), int(41 - 18 * t), 255))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, r, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # faint 10 mm grid on the plate, in perspective-free isometric
    cx, cy, u = N * 0.5, N * 0.555, N * 0.148
    ax, ay = (0.866 * u, 0.5 * u), (-0.866 * u, 0.5 * u)     # plate axes on screen
    def P(x, y, z=0.0): return (cx + x * ax[0] + y * ay[0], cy + x * ax[1] + y * ay[1] - z * u)
    grid = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for i in range(-6, 7):
        k = i / 3
        g.line([P(k, -2), P(k, 2)], fill=(255, 255, 255, 16), width=S * 2)
        g.line([P(-2, k), P(2, k)], fill=(255, 255, 255, 16), width=S * 2)
    img.alpha_composite(Image.composite(grid, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask))
    # shadow
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([P(-1, -1), P(1.15, -1), P(1.15, 1.15), P(-1, 1.15)], fill=(0, 0, 0, 150))
    img.alpha_composite(Image.composite(sh.filter(ImageFilter.GaussianBlur(N * 0.02)), Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask))
    # the block: an L-shaped part (a step), three shaded faces per box
    clay_top, clay_l, clay_r, ink = (232, 228, 219), (176, 171, 161), (205, 200, 190), (33, 31, 28)
    def block(x0, y0, x1, y1, z0, z1):
        d.polygon([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], fill=clay_top, outline=ink, width=S * 4)
        d.polygon([P(x0, y1, z1), P(x1, y1, z1), P(x1, y1, z0), P(x0, y1, z0)], fill=clay_l, outline=ink, width=S * 4)
        d.polygon([P(x1, y0, z1), P(x1, y1, z1), P(x1, y1, z0), P(x1, y0, z0)], fill=clay_r, outline=ink, width=S * 4)
    block(-1, -1, 1, 0.0, 0, 1.25)          # tall back
    block(-1, 0.0, 1, 1, 0, 0.55)           # low front step
    # one dimension, drawn like a drawing, in the datum colour
    datum = (62, 230, 255, 255)
    o = 1.36
    a, b = P(-1, o), P(1, o)
    d.line([a, b], fill=datum, width=S * 7)
    for p, q in ((P(-1, o - 0.14), P(-1, o + 0.14)), (P(1, o - 0.14), P(1, o + 0.14))):
        d.line([p, q], fill=datum, width=S * 7)
    out = img.resize((1024, 1024), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    out.save(OUT / "icon.png")
    out.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    out.save(OUT / "icon.icns")
    print("wrote", OUT / "icon.png")


if __name__ == "__main__":
    main()
