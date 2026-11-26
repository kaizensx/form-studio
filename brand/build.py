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

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

FRAME = O.OPTIONS[0]                  # the chosen direction
# The palette is Lightdesk's (docs/design/directions/h): a near-black room, paper, and one accent, electric cyan, which
# marks the origin. brand/options/ keeps the graphite and mint the six directions were first drawn in, as the record
# of the choice; only the geometry and the type are taken from there.
PLATE, INK, INK2, CLAY, DATUM = "#0b0b0c", "#f4f3f1", "#a9a8a5", "#d8d3c8", "#3ee6ff"
PAPER, PAPER_INK, PAPER_INK2, DATUM_PAPER = "#eeece8", "#161616", "#5d5c59", "#0a8fb3"
# DATUM_PAPER is for the origin square. Words and controls on paper use the deeper #06708d (4.8:1), set where they are drawn.
DATUM_SMALL = "#1fcff2"               # the origin at 3 to 12 px, where it is a handful of pixels beside the clay
DARK = {"part": CLAY, "accent": DATUM, "ink": INK, "ink2": INK2, "line": CLAY}
LIGHT = {"part": PAPER_INK, "accent": DATUM_PAPER, "ink": PAPER_INK, "ink2": PAPER_INK2, "line": PAPER_INK}
SMALL = {**DARK, "accent": DATUM_SMALL}
MONO = {"part": PAPER_INK, "accent": PAPER_INK, "ink": PAPER_INK, "ink2": PAPER_INK, "line": PAPER_INK}


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print("  ", path.relative_to(ROOT))


def save(im: QImage, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert im.save(str(path)), path
    print("  ", path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, f"{im.width()}x{im.height()}")


def to_pil(im: QImage):
    from PIL import Image
    from PySide6.QtCore import QBuffer
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    im.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


# ── the app icon: near-black squircle on the macOS grid (824 body in 1024), the mark lifted by a soft shadow ──────
DATUM_TOP, DATUM_FOOT = "#7df0ff", "#22d2f4"      # the origin on the icon: lit from above, a shade deeper at its foot


def icon_svg(small: bool = False) -> str:
    C, half = 512, 412
    body = O.squircle(C, C, half)
    mark, (bx, by, bw, bh) = O.m_frame(SMALL if small else DARK, small)
    s = 8.2                                          # the F is 394 px tall in the 824 body
    fx = C - (bx + bw / 2) * s + 10                  # optical centre: the F's weight sits on its stem
    fy = C - (by + bh / 2) * s
    shadow = O.m_frame({"part": "#000", "accent": "#000"}, small)[0]
    soft = "" if small else f'<path d="{O.squircle(C, C + 12, half)}" fill="#000" fill-opacity="0.38" filter="url(#drop)"/>'
    lift = "" if small else f'<g transform="translate(0 {10 / s:.3f})" filter="url(#lift)" opacity="0.55">{shadow}</g>'
    face = mark.replace(f'fill="{CLAY}"', 'fill="url(#clay)"').replace(f'fill="{DATUM}"', 'fill="url(#datum)"').replace(f'fill="{DATUM_SMALL}"', 'fill="url(#datum)"')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024"><title>Form Studio</title>
<defs>
  <filter id="drop" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14"/></filter>
  <filter id="lift" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="{9 / s:.3f}"/></filter>
  <linearGradient id="body" x1="0" y1="100" x2="0" y2="924" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#2b2b2e"/><stop offset="0.5" stop-color="#171718"/><stop offset="1" stop-color="#0b0b0c"/></linearGradient>
  <radialGradient id="lamp" cx="380" cy="260" r="620" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff" stop-opacity="0.06"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <linearGradient id="rim" x1="0" y1="100" x2="0" y2="924" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff" stop-opacity="0.28"/><stop offset="0.3" stop-color="#fff" stop-opacity="0.07"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0.04"/></linearGradient>
  <linearGradient id="clay" x1="0" y1="8" x2="0" y2="56" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#e7e2d8"/><stop offset="1" stop-color="#cec8bb"/></linearGradient>
  <linearGradient id="datum" x1="0" y1="8" x2="0" y2="20" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="{DATUM_TOP}"/><stop offset="1" stop-color="{DATUM_FOOT}"/></linearGradient>
</defs>{soft}
<path d="{body}" fill="url(#body)"/><path d="{body}" fill="url(#lamp)"/>
<g transform="translate({fx:.1f} {fy:.1f}) scale({s})">{lift}{face}</g>
<path d="{O.squircle(C, C, half - 1.5)}" fill="none" stroke="url(#rim)" stroke-width="3"/>
</svg>
"""


def icon_at(px: int) -> QImage:
    return O.render(icon_svg(small=px < 64), px)      # below 64 px the hairline cut and the soft shadows only blur


def tile_svg(px: int, scale: float, radius: float = 0) -> str:
    """The mark on a near-black tile, for browsers and home screens (they round touch icons themselves)."""
    mark, (bx, by, bw, bh) = O.m_frame(SMALL if px < 64 else DARK, small=px < 64)
    s = 64 * scale / bh
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><title>Form Studio</title>'
            f'<rect width="64" height="64" rx="{radius}" fill="{PLATE}"/>'
            f'<g transform="translate({32 - (bx + bw / 2) * s + 0.6:.2f} {32 - (by + bh / 2) * s:.2f}) scale({s:.4f})">{mark}</g></svg>\n')


# ── outputs ──────────────────────────────────────────────────────────────────────────────────────────────────
def build_sources():
    print("brand/")
    write(HERE / "mark.svg", O.mark_svg(FRAME, DARK, pad=0))
    write(HERE / "mark-32.svg", O.mark_svg(FRAME, SMALL, px=32, small=True, pad=0.06))
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
    for name in ("lockup.svg", "lockup-light.svg"):          # the website's header draws these two
        write(SITE / "assets" / name, (HERE / name).read_text())
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


OG_MARK = 88                          # the mark's height on the 630 px card; the wordmark's cap height follows it


# The card's surroundings are Lightdesk (docs/design/directions/h): the studio's near-black room, a pool of warm key
# light under the build, Geist for the two lines and a Geist Mono caption in the one accent. The lockup is unchanged.
ROOM, ROOM_INK, ROOM_INK2, ACCENT, KEY = PLATE, INK, INK2, DATUM, (255, 233, 207)


def _geist(weight: int, px: int, mono: bool = False):
    """Geist (the website's copy, SIL OFL 1.1) at one weight, or the app's Geist Mono, as a QFont."""
    from PySide6.QtGui import QFont, QFontDatabase
    if mono:
        f = O._font("mono", weight, 0)
    else:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        tmp = Path(tempfile.gettempdir()) / f"form-geist-{weight}.ttf"
        if not tmp.exists():
            ft = instancer.instantiateVariableFont(TTFont(SITE / "fonts" / "Geist.woff2"), {"wght": weight})
            ft.flavor = None
            ft.save(tmp)
        fam = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(tmp)))[0]
        f = QFont(fam)
    f.setPixelSize(px)
    return f


def build_og(scale: int = 1, out: Path | None = None, mark: float = OG_MARK):
    """1200x630: the lockup in the studio's room, two lines, and a real build photographed in the app
    (brand/og-part.png) standing in the key light. scale 2 draws the same card at 2400x1260: the banner at the top
    of the README and in Discord's #welcome. mark is the height of the mark in px on the 1200x630 card; the lockup,
    the lines and the build's place all follow it, so the logo leads at any size."""
    from PySide6.QtGui import QFont, QRadialGradient
    W, H = 1200, 630
    im = QImage(W * scale, H * scale, QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(QColor(ROOM))
    p = QPainter(im)
    p.scale(scale, scale)
    for h in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.SmoothPixmapTransform, QPainter.RenderHint.TextAntialiasing):
        p.setRenderHint(h)
    floor = QLinearGradient(0, 0, 0, H)                  # the sweep of the studio floor
    for at, c in ((0, "#0a0a0b"), (.38, "#131314"), (.6, "#1b1b1c"), (1, "#0d0d0e")):
        floor.setColorAt(at, QColor(c))
    p.fillRect(QRectF(0, 0, W, H), floor)
    lk = O.lockup(FRAME, DARK)
    left = 72
    lh = float(mark)
    lw = lh / O.ratio(lk)
    part = HERE / "og-part.png"
    if part.exists():
        pim = to_qimage_soft(QImage(str(part)))
        th = 600
        tw = round(pim.width() * th / pim.height())
        # the build keeps clear of the wordmark: it slides right (and off the edge a little) as the lockup grows
        x, top = max(W - tw + 70, left + lw - 36), (H - th) / 2 + 20
        pool = QRadialGradient(x + tw * 0.5, top + th * 0.62, tw * 0.62)
        pool.setColorAt(0, QColor(*KEY, 46))
        pool.setColorAt(.55, QColor(*KEY, 14))
        pool.setColorAt(1, QColor(*KEY, 0))
        p.fillRect(QRectF(0, 0, W, H), pool)
        p.drawImage(QRectF(x, top, tw, th), pim)
    size = round(22 + lh * 0.14)                     # 34 px beside an 88 px mark
    lead = round(size * 1.38)
    cap = round(size * 0.4)                          # the caption under the two lines
    block = lh + size * 1.9 + lead + cap * 3.4       # lockup, a gap, two lines, the caption
    y = (H - block) / 2 - 2
    QSvgRenderer(QByteArray(lk.encode())).render(p, QRectF(left, y, lw, lh))
    p.setFont(_geist(450, size))
    base = round(y + lh + size * 1.9)
    p.setPen(QColor(ROOM_INK))
    p.drawText(left, base, "Describe anything.")
    p.setPen(QColor(ROOM_INK2))
    p.drawText(left, base + lead, "The open-source AI CAD studio.")
    f = _geist(500, cap, mono=True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, cap * 0.16)
    p.setFont(f)
    cy = base + lead + cap * 3.4
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(62, 230, 255, 56))
    p.drawEllipse(QRectF(left - 4, cy - cap * 0.36 - 7, 14, 14))
    p.setBrush(QColor(ACCENT))
    p.drawEllipse(QRectF(left, cy - cap * 0.36 - 3, 6, 6))
    p.setPen(QColor(ACCENT))
    p.drawText(left + 20, round(cy), "MIT · MACOS · WINDOWS · LINUX")
    p.end()
    save(im, out or SITE / "assets" / "og.png")


def to_qimage_soft(pim: QImage) -> QImage:
    """The build's photograph with its own dark backdrop faded out towards its edges, so it stands in the room
    instead of in a rectangle: alpha falls off with a wide feather on every side (more on the left, where the
    wordmark is)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    src = to_pil(pim)
    w, h = src.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((w * 0.10, h * 0.10, w * 1.02, h * 0.92), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w * 0.075))
    src.putalpha(ImageChops.multiply(src.getchannel("A"), mask))
    buf = io.BytesIO()
    src.save(buf, "PNG")
    out = QImage()
    out.loadFromData(buf.getvalue(), "PNG")
    return out


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
