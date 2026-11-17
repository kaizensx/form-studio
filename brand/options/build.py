"""Six logo directions for Form Studio, for the owner to choose from. Writes only into brand/options/.

    .venv/bin/python brand/options/build.py

Per option N:  option-N.svg (lockup on graphite), option-N-light.svg (lockup on white), option-N-mark.svg (1024),
option-N-mark-32.svg (the mark tuned for 32 px and below), option-N-icon.svg (mock macOS app icon, 1024),
option-N.png (1600×1000 presentation sheet). Plus overview.png (all six, labelled 1–6).

Marks are hand-drawn on a 64-unit grid (4 units = 1 px at 16 px). Wordmarks are Instrument Sans or Geist Mono
(both SIL OFL 1.1, already shipped in form/app/assets/fonts), shaped with Qt (kerning, tracking), overlaps merged with
skia-pathops, written as outlines so they render identically everywhere. Rasters come from Qt's QSvgRenderer.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QPainterPath)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FONTS = ROOT / "form" / "app" / "assets" / "fonts"

# Theme.qml
PLATE, PLATE1, PLATE2 = "#0e1113", "#13171a", "#191e22"
INK, INK2, INK3 = "#e8edeb", "#a8b2af", "#717b78"
CLAY, DATUM = "#d8d3c8", "#b9e8d7"
# for white backgrounds: the same roles, dark enough to read on paper
LIGHT = {"part": PLATE, "accent": "#2f8a6c", "ink": PLATE, "ink2": "#5b6562", "line": PLATE}
DARK = {"part": CLAY, "accent": DATUM, "ink": INK, "ink2": INK2, "line": CLAY}

FAM: dict = {}


# ── type ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _font(family: str, weight: int, track: float) -> QFont:
    if family not in FAM:
        fid = QFontDatabase.addApplicationFont(str(FONTS / ("InstrumentSans.ttf" if family == "sans" else "GeistMono.ttf")))
        FAM[family] = QFontDatabase.applicationFontFamilies(fid)[0]
    f = QFont(FAM[family])
    f.setPixelSize(1000)
    f.setVariableAxis(QFont.Tag("wght"), weight)
    f.setKerning(True)
    f.setLetterSpacing(QFont.PercentageSpacing, 100 + track)
    return f


def _outline(path: QPainterPath, dx: float, dy: float) -> str:
    import pathops
    from fontTools.pens.svgPathPen import SVGPathPen
    pp = pathops.Path()
    pen = pp.getPen()
    open_ = False
    i, n = 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        pt = (e.x + dx, e.y + dy)
        if e.type == QPainterPath.ElementType.MoveToElement:
            if open_:
                pen.closePath()
            pen.moveTo(pt)
            open_ = True
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            pen.lineTo(pt)
            i += 1
        else:
            c1, c2 = path.elementAt(i + 1), path.elementAt(i + 2)
            pen.curveTo(pt, (c1.x + dx, c1.y + dy), (c2.x + dx, c2.y + dy))
            i += 3
    if open_:
        pen.closePath()
    pp.simplify(fix_winding=True)
    sp = SVGPathPen(None, ntos=lambda v: f"{round(v, 1):g}")
    pp.draw(sp)
    return sp.getCommands()


def wordmark(spans) -> tuple[list, float, float]:
    """spans: [(text, family, weight, track%, role)] set on one baseline, a word space between spans.
    Returns ([(path, role)], width, cap height); y = 0 is the cap line, y = cap the baseline."""
    cap = None
    x = 0.0
    out = []
    left = None
    right = 0.0
    for k, (text, fam, w, tr, role) in enumerate(spans):
        f = _font(fam, w, tr)
        if cap is None:
            ref = QPainterPath()
            ref.addText(0, 0, f, "H")
            cap = -ref.boundingRect().top()
        p = QPainterPath()
        p.addText(x, 0, f, text)
        br = p.boundingRect()
        if left is None:
            left = br.left()
        right = br.right()
        out.append((p, role))
        fm = QFontMetricsF(f)
        x += fm.horizontalAdvance(text) + 0.26 * 1000          # word space: the same for sans and mono
    return [(_outline(p, -left, cap), role) for p, role in out], right - left, cap


# ── marks: each returns SVG markup on the 64 grid and its own bounds (x, y, w, h) ──────────────────────────
def m_frame(c, small=False):
    g = 0 if small else 2
    return (f'<path d="M{24 + g} 8H52V20H{24 + g}Z M12 {20 + g}H24V28H44V40H24V56H12Z" fill="{c["part"]}"/>'
            f'<path d="M12 8H24V20H12Z" fill="{c["accent"]}"/>'), (12, 8, 40, 48)


def m_caliper(c, small=False):
    beam = "M14 6H24V58H14Z"
    jaw = "M24 6H44L54 18H24Z"                       # fixed jaw: measuring face underneath, tip down
    slide = "M24 30H54L44 42H24Z"                    # sliding jaw: measuring face on top, tip up
    return (f'<path d="{beam} {jaw}" fill="{c["part"]}"/><path d="{slide}" fill="{c["accent"]}"/>'), (14, 6, 40, 52)


def _fpath(dx, dy):
    return (f"M{16 + dx} {14 + dy}H{54 + dx}V{26 + dy}H{28 + dx}V{32 + dy}H{48 + dx}V{44 + dy}H{28 + dx}"
            f"V{58 + dy}H{16 + dx}Z")


def m_sketch(c, small=False):
    sw = 4 if small else 2.5
    return (f'<path d="{_fpath(-6, -6)}" fill="none" stroke="{c["accent"]}" stroke-width="{sw}" stroke-linejoin="miter"/>'
            f'<path d="{_fpath(0, 0)}" fill="{c["part"]}"/>'), (8.75, 6.75, 46.25, 51.25)


def _rrect(x, y, w, h, r):
    import pathops
    k = 0.5523 * r
    pp = pathops.Path()
    pen = pp.getPen()
    pen.moveTo((x + r, y)); pen.lineTo((x + w - r, y))
    pen.curveTo((x + w - r + k, y), (x + w, y + r - k), (x + w, y + r)); pen.lineTo((x + w, y + h - r))
    pen.curveTo((x + w, y + h - r + k), (x + w - r + k, y + h), (x + w - r, y + h)); pen.lineTo((x + r, y + h))
    pen.curveTo((x + r - k, y + h), (x, y + h - r + k), (x, y + h - r)); pen.lineTo((x, y + r))
    pen.curveTo((x, y + r - k), (x + r - k, y), (x + r, y)); pen.closePath()
    return pp


def _poly_path(pts):
    import pathops
    pp = pathops.Path()
    pen = pp.getPen()
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.closePath()
    return pp


def _svgd(pp):
    from fontTools.pens.svgPathPen import SVGPathPen
    sp = SVGPathPen(None, ntos=lambda v: f"{round(v, 2):g}")
    pp.draw(sp)
    return sp.getCommands()


def m_section(c, small=False):
    # a rounded block cut on the diagonal; the far piece lifts off along the cut, its face in datum
    import pathops
    g = 3 if small else 2.4
    blk = _rrect(8, 8, 48, 48, 12)
    near = pathops.op(blk, _poly_path([(0, g), (0, 64), (64 - g, 64)]), pathops.PathOp.INTERSECTION)
    far = pathops.op(blk, _poly_path([(g, 0), (64, 0), (64, 64 - g)]), pathops.PathOp.INTERSECTION)
    return (f'<path d="{_svgd(near)}" fill="{c["part"]}"/>'
            f'<path transform="translate({g} -{g})" d="{_svgd(far)}" fill="{c["accent"]}"/>'), (8, 8 - g, 48 + g, 48 + g)


def m_datum(c, small=False):
    sw = 5 if small else 4
    R = 20
    q = (f'<path d="M32 32V{32 - R}A{R} {R} 0 0 0 {32 - R} 32Z" fill="{c["accent"]}"/>'
         f'<path d="M32 32V{32 + R}A{R} {R} 0 0 0 {32 + R} 32Z" fill="{c["accent"]}"/>')
    ring = f'<circle cx="32" cy="32" r="{R}" fill="none" stroke="{c["part"]}" stroke-width="{sw}"/>'
    t = 2 if small else 1.5
    cross = "" if small else (f'<path d="M32 4V60M4 32H60" stroke="{c["part"]}" stroke-width="{t}"/>')
    return q + cross + ring, ((4, 4, 56, 56) if not small else (10, 10, 44, 44))


def m_monogram(c, small=False):
    F = "M8 8H30V16H16V28H26V36H16V56H8Z"
    # S: the strokes of a 5, with its outer corners turned so it reads as an S
    S = "M42 8H56V16H42V28H48A8 8 0 0 1 56 36V48A8 8 0 0 1 48 56H34V48H48V36H42A8 8 0 0 1 34 28V16A8 8 0 0 1 42 8Z"
    return f'<path d="{F}" fill="{c["part"]}"/><path d="{S}" fill="{c["accent"]}"/>', (8, 8, 48, 48)


OPTIONS = [
    dict(name="Frame", mark=m_frame, ratio=1.5,
         words=[("Form", "sans", 640, 0, "ink"), ("Studio", "sans", 420, 0, "ink2")],
         idea="The F is a coordinate frame: top arm X, stem Y, and the joint, in datum mint, is the origin every part is built from."),
    dict(name="Caliper", mark=m_caliper, ratio=1.5,
         words=[("FORM", "sans", 640, 9, "ink"), ("STUDIO", "sans", 440, 9, "ink2")],
         idea="The F is a caliper: a beam, a fixed jaw and a sliding jaw in mint; FORM measures before it prints."),
    dict(name="Sketch to solid", mark=m_sketch, ratio=1.45,
         words=[("Form", "sans", 560, -1.5, "ink"), ("Studio", "sans", 560, -1.5, "ink")],
         idea="A mint sketch profile and the clay solid it becomes, offset: what a CAD kernel does, in one step."),
    dict(name="Section", mark=m_section, ratio=1.45,
         words=[("form", "sans", 620, -2, "ink"), ("studio", "sans", 620, -2, "ink2")],
         idea="A block cut on a section plane; the far piece lifts away and shows its cut face, the inside of the design."),
    dict(name="Datum target", mark=m_datum, ratio=1.7,
         words=[("FORM", "mono", 560, 6, "ink"), ("STUDIO", "mono", 400, 6, "ink2")],
         idea="The engineering datum target, set like a title block in Geist Mono: precise, technical, nothing decorative."),
    dict(name="Monogram", mark=m_monogram, ratio=1.4,
         words=[("Form", "sans", 680, -2.5, "ink"), ("Studio", "sans", 680, -2.5, "ink3")],
         idea="F and S built from the same orthogonal extrusions on one grid: part in clay, studio in mint."),
]


# ── composition ──────────────────────────────────────────────────────────────────────────────────────────────
def mark_group(opt, c, small=False):
    body, box = opt["mark"](c, small)
    return body, box


def svg_doc(w, h, body, vb=None, bg=None):
    vb = vb or f"0 0 {w:g} {h:g}"
    v = vb.split()
    bgr = f'<rect x="{v[0]}" y="{v[1]}" width="{v[2]}" height="{v[3]}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w:g}" height="{h:g}">'
            f"<title>Form Studio</title>{bgr}{body}</svg>\n")


def lockup(opt, c, bg=None, pad=0.0):
    paths, ww, cap = wordmark(opt["words"])
    body, (bx, by, bw, bh) = mark_group(opt, c)
    mh = cap * opt["ratio"]
    s = mh / bh
    mw = bw * s
    gap = mh * 0.42
    wy = (mh - cap) / 2
    W, H = math.ceil(mw + gap + ww), math.ceil(mh)
    tint = {"ink": c["ink"], "ink2": c["ink2"], "ink3": c.get("ink3", c["ink2"])}
    words = "".join(f'<path d="{d}" fill="{tint[r]}"/>' for d, r in paths)
    inner = (f'<g transform="scale({s:.5f}) translate({-bx:g} {-by:g})">{body}</g>'
             f'<g transform="translate({mw + gap:.1f} {wy:.1f})">{words}</g>')
    if pad:
        P = pad * H
        return svg_doc(W + 2 * P, H + 2 * P, f'<g transform="translate({P:.1f} {P:.1f})">{inner}</g>', bg=bg)
    return svg_doc(W, H, inner, bg=bg)


def mark_svg(opt, c, px=1024, small=False, pad=0.12):
    body, (bx, by, bw, bh) = mark_group(opt, c, small)
    side = max(bw, bh) * (1 + 2 * pad)
    cx, cy = bx + bw / 2, by + bh / 2
    return svg_doc(px, px, body, vb=f"{cx - side / 2:g} {cy - side / 2:g} {side:g} {side:g}")


def squircle(cx, cy, half, n=5.0, steps=360):
    pts = []
    for k in range(steps):
        t = 2 * math.pi * k / steps
        co, si = math.cos(t), math.sin(t)
        pts.append(f"{cx + half * math.copysign(abs(co) ** (2 / n), co):.2f} "
                   f"{cy + half * math.copysign(abs(si) ** (2 / n), si):.2f}")
    return "M" + "L".join(pts) + "Z"


def icon_svg(opt, small=False):
    C, half = 512, 412
    body = squircle(C, C, half)
    mb, (bx, by, bw, bh) = mark_group(opt, DARK, small)
    s = 400 / max(bw, bh * 0.95)
    fx, fy = C - (bx + bw / 2) * s, C - (by + bh / 2) * s
    soft = "" if small else f'<path d="{squircle(C, C + 12, half)}" fill="#000" fill-opacity="0.38" filter="url(#drop)"/>'
    lift = "" if small else (f'<g transform="translate(0 {10 / s:.3f})" filter="url(#lift)" opacity="0.55">'
                             f'{mark_group(opt, {"part": "#000", "accent": "#000", "ink": "#000", "ink2": "#000", "line": "#000"}, small)[0]}</g>')
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
</defs>{soft}
<path d="{body}" fill="url(#body)"/><path d="{body}" fill="url(#lamp)"/>
<g transform="translate({fx:.1f} {fy:.1f}) scale({s:.4f})">{lift}{mb}</g>
<path d="{squircle(C, C, half - 1.5)}" fill="none" stroke="url(#rim)" stroke-width="3"/>
</svg>
"""


# ── rendering ────────────────────────────────────────────────────────────────────────────────────────────────
def render(svg, w, h=None):
    h = h or w
    r = QSvgRenderer(QByteArray(svg.encode()))
    assert r.isValid()
    im = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(Qt.GlobalColor.transparent)
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, w, h))
    p.end()
    return im


def ratio(svg):
    vb = [float(v) for v in svg.split('viewBox="')[1].split('"')[0].split()]
    return vb[3] / vb[2]


class Sheet:
    def __init__(self, w, h, bg="#0a0c0e"):
        self.im = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        self.im.fill(QColor(bg))
        self.p = QPainter(self.im)
        for hint in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.TextAntialiasing,
                     QPainter.RenderHint.SmoothPixmapTransform):
            self.p.setRenderHint(hint)

    def text(self, x, y, s, px, w=420, color=INK, fam="sans", width=None):
        f = _font(fam, w, 0)
        f.setPixelSize(px)
        self.p.setFont(f)
        self.p.setPen(QColor(color))
        if width:
            self.p.drawText(QRectF(x, y, width, px * 4), Qt.TextFlag.TextWordWrap, s)
        else:
            self.p.drawText(round(x), round(y), s)

    def box(self, x, y, w, h, c, r=14):
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(QColor(c))
        self.p.drawRoundedRect(QRectF(x, y, w, h), r, r)

    def svg_fit(self, svg, x, y, w, h=None, align="center"):
        """draw an SVG into a box, keeping its aspect, rendered at 2× then drawn down for crisp edges"""
        a = ratio(svg)
        dw = w if h is None or w * a <= h else h / a
        dh = dw * a
        ox = x + (w - dw) / 2 if align == "center" else x
        oy = y + ((h - dh) / 2 if h else 0)
        self.p.drawImage(QRectF(ox, oy, dw, dh), render(svg, round(dw * 2), round(dh * 2)))
        return ox, oy, dw, dh

    def pixels(self, svg, px, x, y, zoom=1):
        im = render(svg, px)
        if zoom > 1:
            im = im.scaled(px * zoom, px * zoom, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        self.p.drawImage(x, y, im)

    def save(self, path):
        self.p.end()
        assert self.im.save(str(path))


def sheet(n, opt, files):
    S = Sheet(1600, 1000)
    S.text(48, 74, f"{n}", 34, 640, DATUM)
    S.text(92, 74, opt["name"], 34, 620)
    S.text(48, 104, opt["idea"], 17, 420, INK2)
    # lockup, large
    S.box(48, 136, 960, 330, PLATE)
    S.svg_fit(files["lockup"], 108, 136, 840, 330)
    # mark at 512
    S.box(1040, 136, 512, 512, PLATE)
    S.p.drawImage(1040, 136, render(files["mark"], 512))
    S.text(1052, 668, "512 px", 13, 420, INK3)
    # sizes at 1x: 64, 32, 16, then 32 and 16 enlarged 4x to show their pixels
    S.box(48, 492, 470, 250, PLATE)
    x = 80
    for px in (64, 32, 16):
        S.pixels(files["mark"] if px >= 64 else files["mark32"], px, x, 560 + (64 - px) // 2)
        S.text(x, 668, f"{px}", 13, 420, INK3)
        x += px + 40
    S.pixels(files["mark32"], 32, 290, 520, 4)
    S.pixels(files["mark32"], 16, 432, 552, 4)
    S.text(290, 668, "32 and 16, pixels ×4", 13, 420, INK3)
    # app icon
    S.box(538, 492, 470, 250, PLATE)
    S.p.drawImage(QRectF(570, 504, 226, 226), render(files["icon"], 452))
    S.p.drawImage(820, 584, render(files["icon"], 64))
    S.p.drawImage(904, 600, render(files["icon32"], 32))
    S.p.drawImage(956, 608, render(files["icon32"], 16))
    S.text(820, 668, "app icon 64 · 32 · 16", 13, 420, INK3)
    # on white
    S.box(48, 768, 960, 186, "#ffffff")
    S.svg_fit(files["light"], 168, 768, 720, 186)
    # one line, under the mark
    S.box(1040, 692, 512, 262, PLATE)
    S.svg_fit(files["lockup"], 1080, 692, 432, 262)
    S.save(HERE / f"option-{n}.png")


def overview(all_files):
    W, H = 2400, 1360
    S = Sheet(W, H, "#08090b")
    S.text(56, 76, "Form Studio · six directions", 30, 620)
    S.text(56, 110, "Lockup, app icon, and the mark at 32 and 16 px. Pick one; the full sheet for each is option-N.png.",
           17, 420, INK2)
    cw, ch = 760, 580
    for i, (opt, f) in enumerate(all_files):
        col, row = i % 3, i // 3
        x, y = 56 + col * (cw + 24), 150 + row * (ch + 24)
        S.box(x, y, cw, ch, PLATE)
        S.text(x + 28, y + 52, f"{i + 1}", 26, 640, DATUM)
        S.text(x + 62, y + 52, opt["name"], 26, 620)
        S.svg_fit(f["lockup"], x + 60, y + 90, cw - 120, 150)
        S.p.drawImage(QRectF(x + 40, y + 270, 270, 270), render(f["icon"], 540))
        S.p.drawImage(x + 360, y + 330, render(f["mark32"], 32))
        S.p.drawImage(x + 420, y + 338, render(f["mark32"], 16))
        S.pixels(f["mark32"], 16, x + 470, y + 300, 6)
        S.box(x + 360, y + 420, cw - 400, 120, "#ffffff", 10)
        S.svg_fit(f["light"], x + 390, y + 420, cw - 460, 120)
    S.save(HERE / "overview.png")


def main():
    QGuiApplication(sys.argv[:1])
    done = []
    for n, opt in enumerate(OPTIONS, 1):
        files = {
            "lockup": lockup(opt, DARK, bg=PLATE, pad=0.6),
            "light": lockup(opt, LIGHT, bg="#ffffff", pad=0.6),
            "mark": mark_svg(opt, DARK),
            "mark32": mark_svg(opt, DARK, px=32, small=True, pad=0.06),
            "icon": icon_svg(opt),
            "icon32": icon_svg(opt, small=True),
        }
        (HERE / f"option-{n}.svg").write_text(files["lockup"])
        (HERE / f"option-{n}-light.svg").write_text(files["light"])
        (HERE / f"option-{n}-mark.svg").write_text(files["mark"])
        (HERE / f"option-{n}-mark-32.svg").write_text(files["mark32"])
        (HERE / f"option-{n}-icon.svg").write_text(files["icon"])
        sheet(n, opt, files)
        done.append((opt, files))
        print(f"option-{n}: {opt['name']}")
    overview(done)
    print("overview.png")


if __name__ == "__main__":
    main()
