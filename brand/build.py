"""Build every Form Studio brand file from the chosen direction (option 1, "Frame"; see brand/options/).

    .venv/bin/python brand/build.py

Writes brand/*.svg, the app icon (form/app/assets/icon.{svg,png,icns,ico} + sized PNGs), the web icons and og image
(site/assets/*, site/favicon.ico) and the wordmark outlines the app draws (form/app/qml/Form/LogoPaths.js).
Geometry, type and rendering come from brand/options/build.py so the record of the choice and the result cannot drift.
Needs skia-pathops (merges the variable font's overlapping contours) in the dev environment.
"""
from __future__ import annotations

import importlib.util
import io
import math
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = ROOT / "form" / "app" / "assets"
SITE = ROOT / "site"

_spec = importlib.util.spec_from_file_location("brand_options", HERE / "options" / "build.py")
O = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(O)

from PySide6.QtCore import QByteArray, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

FRAME = O.OPTIONS[0]                  # the chosen direction
PLATE, INK, INK2, CLAY, DATUM = O.PLATE, O.INK, O.INK2, O.CLAY, O.DATUM
DARK, LIGHT = O.DARK, O.LIGHT
MONO = {"part": PLATE, "accent": PLATE, "ink": PLATE, "ink2": PLATE, "line": PLATE}


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print("  ", path.relative_to(ROOT))


def save(im: QImage, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert im.save(str(path)), path
    print("  ", path.relative_to(ROOT), f"{im.width()}x{im.height()}")


def to_pil(im: QImage):
    from PIL import Image
    from PySide6.QtCore import QBuffer
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    im.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


# ── the app icon: graphite squircle on the macOS grid (824 body in 1024), the mark lifted by a soft shadow ──────
def icon_svg(small: bool = False) -> str:
    C, half = 512, 412
    body = O.squircle(C, C, half)
    mark, (bx, by, bw, bh) = O.m_frame(DARK, small)
    s = 8.2                                          # the F is 394 px tall in the 824 body
    fx = C - (bx + bw / 2) * s + 10                  # optical centre: the F's weight sits on its stem
    fy = C - (by + bh / 2) * s
    shadow = O.m_frame({"part": "#000", "accent": "#000"}, small)[0]
    soft = "" if small else f'<path d="{O.squircle(C, C + 12, half)}" fill="#000" fill-opacity="0.38" filter="url(#drop)"/>'
    lift = "" if small else f'<g transform="translate(0 {10 / s:.3f})" filter="url(#lift)" opacity="0.55">{shadow}</g>'
    face = mark.replace(f'fill="{CLAY}"', 'fill="url(#clay)"').replace(f'fill="{DATUM}"', 'fill="url(#datum)"')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024"><title>Form Studio</title>
<defs>
  <filter id="drop" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14"/></filter>
  <filter id="lift" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="{9 / s:.3f}"/></filter>
  <linearGradient id="body" x1="0" y1="100" x2="0" y2="924" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#2a3237"/><stop offset="0.5" stop-color="#171c1f"/><stop offset="1" stop-color="#0c0f11"/></linearGradient>
  <radialGradient id="lamp" cx="380" cy="260" r="620" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <linearGradient id="rim" x1="0" y1="100" x2="0" y2="924" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff" stop-opacity="0.28"/><stop offset="0.3" stop-color="#fff" stop-opacity="0.07"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0.04"/></linearGradient>
  <linearGradient id="clay" x1="0" y1="8" x2="0" y2="56" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#e7e2d8"/><stop offset="1" stop-color="#cec8bb"/></linearGradient>
  <linearGradient id="datum" x1="0" y1="8" x2="0" y2="20" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#c8efe1"/><stop offset="1" stop-color="#b0e2cf"/></linearGradient>
</defs>{soft}
<path d="{body}" fill="url(#body)"/><path d="{body}" fill="url(#lamp)"/>
<g transform="translate({fx:.1f} {fy:.1f}) scale({s})">{lift}{face}</g>
<path d="{O.squircle(C, C, half - 1.5)}" fill="none" stroke="url(#rim)" stroke-width="3"/>
</svg>
"""


def icon_at(px: int) -> QImage:
    return O.render(icon_svg(small=px < 64), px)      # below 64 px the hairline cut and the soft shadows only blur


def tile_svg(px: int, scale: float, radius: float = 0) -> str:
    """The mark on a graphite tile, for browsers and home screens (they round touch icons themselves)."""
    mark, (bx, by, bw, bh) = O.m_frame(DARK, small=px < 64)
    s = 64 * scale / bh
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><title>Form Studio</title>'
            f'<rect width="64" height="64" rx="{radius}" fill="{PLATE}"/>'
            f'<g transform="translate({32 - (bx + bw / 2) * s + 0.6:.2f} {32 - (by + bh / 2) * s:.2f}) scale({s:.4f})">{mark}</g></svg>\n')


# ── outputs ──────────────────────────────────────────────────────────────────────────────────────────────────
def build_sources():
    print("brand/")
    write(HERE / "mark.svg", O.mark_svg(FRAME, DARK, pad=0))
    write(HERE / "mark-32.svg", O.mark_svg(FRAME, DARK, px=32, small=True, pad=0.06))
    write(HERE / "mark-mono.svg", O.mark_svg(FRAME, MONO, pad=0))
    paths, w, cap = O.wordmark(FRAME["words"])
    o = cap * 0.02
    for name, c in (("wordmark.svg", DARK), ("wordmark-light.svg", LIGHT)):
        body = "".join(f'<path d="{d}" fill="{c[r]}"/>' for d, r in paths)
        write(HERE / name, O.svg_doc(math.ceil(w), math.ceil(cap + 2 * o), body,
                                     vb=f"0 {-o:.1f} {math.ceil(w)} {math.ceil(cap + 2 * o)}"))
    write(HERE / "lockup.svg", O.lockup(FRAME, DARK))
    write(HERE / "lockup-light.svg", O.lockup(FRAME, LIGHT))
    write(HERE / "lockup-mono.svg", O.lockup(FRAME, MONO))
    write(HERE / "icon.svg", icon_svg())


def build_app_icon():
    print("form/app/assets/")
    write(ASSETS / "icon.svg", icon_svg())
    save(icon_at(1024), ASSETS / "icon.png")
    for px in (512, 256, 128, 64, 32, 16):
        save(icon_at(px), ASSETS / f"icon-{px}.png")
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            iset = Path(tmp) / "icon.iconset"
            iset.mkdir()
            for base in (16, 32, 128, 256, 512):
                icon_at(base).save(str(iset / f"icon_{base}x{base}.png"))
                icon_at(base * 2).save(str(iset / f"icon_{base}x{base}@2x.png"))
            subprocess.run(["iconutil", "-c", "icns", str(iset), "-o", str(ASSETS / "icon.icns")], check=True)
        print("   form/app/assets/icon.icns (iconutil, 16 to 1024)")
    else:
        print("   icon.icns not rebuilt: iconutil is macOS only")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = {px: to_pil(icon_at(px)) for px in sizes}
    imgs[256].save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes], append_images=[imgs[s] for s in sizes[:-1]])
    print("   form/app/assets/icon.ico", sizes)


def build_web():
    print("site/")
    fav = tile_svg(16, 0.74, 14)
    write(SITE / "assets" / "favicon.svg", fav)
    save(O.render(fav, 32), SITE / "assets" / "favicon.png")
    ico = {px: to_pil(O.render(tile_svg(px, 0.74, 14), px)) for px in (16, 32, 48)}
    ico[48].save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=[ico[16], ico[32]])
    print("   site/favicon.ico [16, 32, 48]")
    for px, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        save(O.render(tile_svg(px, 0.6), px), SITE / "assets" / name)
    build_og()
    build_og(2, ROOT / "docs" / "readme" / "banner.png")


def build_og(scale: int = 1, out: Path | None = None):
    """1200x630: the lockup on graphite, two lines, and a real build photographed in the app (brand/og-part.png).
    scale 2 draws the same card at 2400x1260: the banner at the top of the README and in Discord's #welcome."""
    W, H = 1200, 630
    im = QImage(W * scale, H * scale, QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(QColor(PLATE))
    p = QPainter(im)
    p.scale(scale, scale)
    for h in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.SmoothPixmapTransform, QPainter.RenderHint.TextAntialiasing):
        p.setRenderHint(h)
    part = HERE / "og-part.png"
    if part.exists():
        pim = QImage(str(part))
        th = 600
        tw = round(pim.width() * th / pim.height())
        x, top = W - tw + 70, (H - th) / 2 + 20
        p.drawImage(QRectF(x, top, tw, th), pim)
        clear = QColor(PLATE)
        clear.setAlpha(0)
        for (x0, y0, x1, y1, rect) in ((x, 0, x + 260, 0, QRectF(x - 1, 0, 261, H)),
                                       (0, top, 0, top + 170, QRectF(x, top, tw, 170)),
                                       (0, top + th - 140, 0, top + th, QRectF(x, top + th - 140, tw, 140))):
            g = QLinearGradient(x0, y0, x1, y1)
            a, b = (QColor(PLATE), clear) if rect.top() <= top or rect.left() < x else (clear, QColor(PLATE))
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            p.fillRect(rect, g)
        p.fillRect(QRectF(x, 0, tw, top + 1), QColor(PLATE))
        p.fillRect(QRectF(x, top + th - 1, tw, H), QColor(PLATE))
    lk = O.lockup(FRAME, DARK)
    lw = 420
    lh = lw * O.ratio(lk)
    QSvgRenderer(QByteArray(lk.encode())).render(p, QRectF(80, 238, lw, lh))
    f = O._font("sans", 440, 0)
    f.setPixelSize(30)
    p.setFont(f)
    p.setPen(QColor(INK2))
    p.drawText(80, round(238 + lh + 66), "Describe anything.")
    p.drawText(80, round(238 + lh + 108), "The open-source AI CAD studio.")
    p.end()
    save(im, out or SITE / "assets" / "og.png")


def build_qml():
    paths, w, cap = O.wordmark(FRAME["words"])
    (form_d, _), (studio_d, _) = paths
    write(ROOT / "form" / "app" / "qml" / "Form" / "LogoPaths.js",
          "// Generated by brand/build.py: \"Form Studio\" in Instrument Sans (SIL OFL 1.1) as outlines. Do not edit by hand.\n"
          ".pragma library\n"
          f'var form = "{form_d}"\n'
          f'var studio = "{studio_d}"\n'
          f"var width = {w:.1f}\n"
          f"var capHeight = {cap:.1f}\n")


def main():
    QGuiApplication(sys.argv[:1])
    build_sources()
    build_app_icon()
    build_web()
    build_qml()


if __name__ == "__main__":
    main()
