"""Compose a sheet: views placed by the projection method, the scale chosen for the sheet, dimensions placed so
that nothing overlaps, annotations, the border and the ISO 7200 title block. Pure Python (no OCCT): it reads what
the kernel measured and projected.

    sc = compose(raw, plan, annotations, title, sheet="A3", projection="first", theme="night")

Placement is a layout algorithm, not offsets:

- Linear dimensions of a view side are interval-packed into tiers (shortest nearest the part, ISO 129-1): a
  dimension takes the lowest tier where its line and its text clear every dimension already there, and where its
  extension lines do not cut through a nearer dimension's text. Text that does not fit between the arrows goes
  outside, on the side with room. Baseline dimensions nest; chain dimensions share a tier end to end.
- Leaders (diameters seen as circles, radii) and annotation frames search angles and distances for the first spot
  where the text box clears every text, frame, view and the title block.
- The scale is the largest ISO 5455 scale at which the arranged views, with their dimensions, fit the drawing area.
- overlaps(sheet) checks the result: every text and frame box against every other, the views and the title block.
"""
from __future__ import annotations

import math

import numpy as np

from . import gdt as G
from . import scene as S
from . import standards as STD
from . import views as V

GAP = 1.0          # extension line gap from the part (mm on the sheet)
OVER = 2.0         # extension line past the dimension line
TIER0 = 9.0        # first dimension line from the view
TIER = 8.0         # between dimension lines
TH = STD.TEXT_H["dimension"]
CIRCLE_VIEW = {"z": "top", "y": "front", "x": "right"}


def fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _axis_vec(ax):
    return V.AXES[ax]


# ── a view on the sheet ────────────────────────────────────────────────────

class View:
    def __init__(self, name, raw, scale, label="", kind="view"):
        self.name, self.raw, self.s, self.label, self.kind = name, raw, scale, label, kind
        self.origin = np.zeros(2)
        self.dims, self.notes = [], []

    @property
    def geom_box(self):            # in local sheet mm (origin = projected model origin)
        b = self.raw["box"]
        return [b[0] * self.s, b[1] * self.s, b[2] * self.s, b[3] * self.s]

    def p(self, xy):               # local model 2D -> sheet
        return (self.origin[0] + xy[0] * self.s, self.origin[1] + xy[1] * self.s)

    def at3(self, p3):
        return self.p(V.to2d(p3, self.basis_view()))

    def basis_view(self):
        if self.kind == "detail":
            return self.host.basis_view()
        if self.kind == "section":
            pl = self.raw["plane"]
            return (tuple(pl["normal"]), tuple(pl["right"]))
        return self.name

    def edges(self) -> list:
        out = []
        for e in self.raw["edges"]:
            layer = e["layer"]
            if e["kind"] == "line":
                out.append(S.line(self.p(e["a"]), self.p(e["b"]), layer))
            elif e["kind"] == "circle":
                out.append(S.circle(self.p(e["c"]), e["r"] * self.s, layer))
            elif e["kind"] == "arc":
                out.append(S.arc(self.p(e["c"]), e["r"] * self.s, e["a0"], e["a1"], layer))
            else:
                out.append(S.polyline([self.p(q) for q in e["pts"]], layer))
        return out

    def box(self):
        b = self.geom_box
        return [b[0] + self.origin[0], b[1] + self.origin[1], b[2] + self.origin[0], b[3] + self.origin[1]]


def _dir2(view: View, ax: str):
    """Which sheet direction a model axis runs in this view: ("h" | "v", sign) or None when along the view."""
    d, x, y = V.basis(view.basis_view())
    u = _axis_vec(ax)
    if abs(float(u @ x)) > 0.99:
        return "h", float(np.sign(u @ x))
    if abs(float(u @ y)) > 0.99:
        return "v", float(np.sign(u @ y))
    return None


# ── dimensions ─────────────────────────────────────────────────────────────

class Dim:
    """One dimension in one view: two sheet points on the part and an orientation, or a leader."""

    def __init__(self, spec, view, orient, p0=None, p1=None, text="", side=None):
        self.spec, self.view, self.orient, self.p0, self.p1, self.text, self.side = spec, view, orient, p0, p1, text, side
        self.tier = None
        self.nodes, self.text_boxes, self.line_boxes = [], [], []

    @property
    def span(self):
        k = 0 if self.orient == "h" else 1
        a, b = sorted((self.p0[k], self.p1[k]))
        return a, b


def label(spec: dict, fits: dict) -> str:
    v = spec["value"]
    if spec["kind"] == "diameter":
        t = f"Ø{fmt(v)}"
        if spec.get("count", 1) > 1:
            t = f"{spec['count']}× {t}"
    elif spec["kind"] == "radius":
        t = f"R{fmt(v)}"
        if spec.get("count", 1) > 1:
            t = f"{spec['count']}× {t}"
    else:
        t = fmt(v)
    f = fits.get(spec["id"]) or (fits.get(spec.get("param")) if spec.get("param") else None)
    if f:
        t += f" {f['class']} ({_dev(f['upper_um'])}/{_dev(f['lower_um'])})"
    return t


def _dev(um) -> str:
    if um == 0:
        return "0"
    return f"{um / 1000:+.3f}".rstrip("0")


def _place_linear(dims: list[Dim], vbox, occupied_texts: list):
    """Interval packing of one side's linear dimensions into tiers (see the module docstring)."""
    side = dims[0].side
    horiz = side in ("bottom", "top")
    sign = -1 if side in ("bottom", "left") else 1
    edge = (vbox[1] if side == "bottom" else vbox[3]) if horiz else (vbox[0] if side == "left" else vbox[2])
    dims.sort(key=lambda d: (d.span[1] - d.span[0], d.span[0]))
    # every extension line of this side is known before any is placed: a text never sits on one
    ext = sorted({round(x, 3) for d in dims for x in d.span})
    tiers: list[list] = []                 # per tier: [(lo, hi, text_lo, text_hi, where)]

    def clear(t0, t1):
        return not any(t0 - 0.6 < x < t1 + 0.6 for x in ext)

    for d in dims:
        lo, hi = d.span
        tw = S.text_width(d.text, TH)
        options = []
        if tw + 7.0 <= hi - lo:
            for f in (0.5, 0.35, 0.65, 0.25, 0.75, 0.15, 0.85):
                tc = lo + (hi - lo) * f
                if tc - tw / 2 >= lo + 3.0 and tc + tw / 2 <= hi - 3.0 and clear(tc - tw / 2, tc + tw / 2):
                    options.append((lo, hi, tc, "in"))
                    break
        for k in range(0, 6):
            tc = hi + 2.5 + tw / 2 + 4.0 * k
            if clear(tc - tw / 2, tc + tw / 2):
                options.append((lo, tc + tw / 2 + 1.0, tc, "after"))
                break
        for k in range(0, 6):
            tc = lo - 2.5 - tw / 2 - 4.0 * k
            if clear(tc - tw / 2, tc + tw / 2):
                options.append((tc - tw / 2 - 1.0, hi, tc, "before"))
                break
        if not options:
            options = [(lo, hi + tw + 4.0, hi + 2.5 + tw / 2, "after")]
        placed = False
        for strict in (True, False):
            for t in range(0, 40):
                for (a, b, tc, where) in options:
                    ok = t >= len(tiers) or all(b + 1.0 <= x0 or a >= x1 + 1.0 or
                                                ((abs(a - x1) < 1e-6 or abs(b - x0) < 1e-6) and where == "in" and w2 == "in")
                                                for (x0, x1, _t0, _t1, w2) in tiers[t])
                    if ok and strict:     # extension lines of this one must not cut nearer texts
                        for tt in range(min(t, len(tiers))):
                            for (_x0, _x1, t0, t1, _w) in tiers[tt]:
                                if t0 - 0.5 < lo < t1 + 0.5 or t0 - 0.5 < hi < t1 + 0.5:
                                    ok = False
                    if ok:
                        while len(tiers) <= t:
                            tiers.append([])
                        tiers[t].append((a, b, tc - tw / 2, tc + tw / 2, where))
                        d.tier, d.text_center, d.where = t, tc, where
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        off = edge + sign * (TIER0 + TIER * d.tier)
        d.line_at = off
        _draw_linear(d, horiz, sign)


def _draw_linear(d: Dim, horiz: bool, sign: float):
    lay = "dimension"
    off = d.line_at
    nodes = []
    if horiz:
        for p in (d.p0, d.p1):
            y0 = p[1] + sign * GAP
            nodes.append(S.line((p[0], y0), (p[0], off + sign * OVER), lay))
        a, b = d.span
        nodes.append(S.line((a, off), (b, off), lay))
        if d.where == "in":
            nodes += [S.arrow((a, off), (b, off)), S.arrow((b, off), (a, off))]
        else:   # arrows outside pointing in, line extended under the text
            nodes += [S.arrow((a, off), (a - 5, off)), S.arrow((b, off), (b + 5, off))]
            ext = (b, d.text_center + S.text_width(d.text, TH) / 2) if d.where == "after" else \
                (d.text_center - S.text_width(d.text, TH) / 2, a)
            nodes.append(S.line((min(ext[0], a - 4) if d.where == "before" else b, off),
                                (ext[1] if d.where == "after" else a, off), lay))
        t = S.text((d.text_center, off + 1.0), d.text, TH, "middle", "baseline", 0, lay)
        d.line_boxes.append([a, off - 0.3, b, off + 0.3])
    else:
        for p in (d.p0, d.p1):
            x0 = p[0] + sign * GAP
            nodes.append(S.line((x0, p[1]), (off + sign * OVER, p[1]), lay))
        a, b = d.span
        nodes.append(S.line((off, a), (off, b), lay))
        if d.where == "in":
            nodes += [S.arrow((off, a), (off, b)), S.arrow((off, b), (off, a))]
        else:
            nodes += [S.arrow((off, a), (off, a - 5)), S.arrow((off, b), (off, b + 5))]
            if d.where == "after":
                nodes.append(S.line((off, b), (off, d.text_center + S.text_width(d.text, TH) / 2), lay))
            else:
                nodes.append(S.line((off, d.text_center - S.text_width(d.text, TH) / 2), (off, a), lay))
        t = S.text((off - 1.0, d.text_center), d.text, TH, "middle", "baseline", 90, lay)
        d.line_boxes.append([off - 0.3, a, off + 0.3, b])
    nodes.append(t)
    d.text_boxes.append(S.text_box(t, 0.4))
    d.nodes = nodes


def seg_hits(p, q, box, pad=0.0) -> bool:
    """Does the segment p-q pass through the box (Liang-Barsky clipping)?"""
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
            continue
        t = qq / pp
        if pp < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def free_spot(w, h, anchor, occupied, region, start=8.0, step=3.0, avoid=()) -> tuple | None:
    """The nearest place for a w x h box (lower-left corner returned) around `anchor` that clears `occupied`
    boxes, stays inside `region` and keeps out of `avoid` (view boxes)."""
    for k in range(0, 60):
        rad = start + step * k
        n = 16 + 4 * k
        for i in range(n):
            ang = 2 * math.pi * i / n + math.pi / 4
            cx, cy = anchor[0] + rad * math.cos(ang), anchor[1] + rad * math.sin(ang)
            box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
            if box[0] < region[0] or box[1] < region[1] or box[2] > region[2] or box[3] > region[3]:
                continue
            if any(S.overlap(box, o, 0.8) for o in occupied) or any(S.overlap(box, a, 0.8) for a in avoid):
                continue
            return box[0], box[1]
    return None


def _leader(d: Dim, center, rad, occupied, region, avoid, texts=None, angles=None):
    """A diameter or radius leader: from the circle along a radial line, a short shoulder, the text beside it."""
    tw = S.text_width(d.text, TH)
    best = None
    for ang in angles or (45, 135, 315, 225, 30, 150, 330, 210, 60, 120, 300, 240):
        a = math.radians(ang)
        ux, uy = math.cos(a), math.sin(a)
        own = next((v for v in avoid if v[0] - 1e-6 <= center[0] <= v[2] + 1e-6 and v[1] - 1e-6 <= center[1] <= v[3] + 1e-6), None)
        t_exit = 0.0
        if own is not None:                       # how far along this ray the view's box ends
            tx = ((own[2] - center[0]) / ux if ux > 1e-9 else (own[0] - center[0]) / ux if ux < -1e-9 else 1e9)
            ty = ((own[3] - center[1]) / uy if uy > 1e-9 else (own[1] - center[1]) / uy if uy < -1e-9 else 1e9)
            t_exit = max(0.0, min(tx, ty) - rad)
        for L in [x for x in (6, 10, 14) if x > t_exit] + [t_exit + k for k in (4, 7, 10, 14, 19, 25, 32)]:
            ex, ey = center[0] + ux * (rad + L), center[1] + uy * (rad + L)
            right = ux >= 0
            sx = ex + (4 if right else -4)
            tb = [sx, ey + 0.6, sx + tw, ey + 0.6 + TH * 1.25] if right else [sx - tw, ey + 0.6, sx, ey + 0.6 + TH * 1.25]
            if tb[0] < region[0] or tb[2] > region[2] or tb[1] < region[1] or tb[3] > region[3]:
                continue
            if any(S.overlap(tb, o, 0.6) for o in occupied) or any(S.overlap(tb, v, 0.6) for v in avoid):
                continue
            tip0 = (center[0] + ux * rad, center[1] + uy * rad)
            tx_only = occupied if texts is None else texts      # a leader may cross a dimension line, never a text
            if any(seg_hits(tip0, (ex, ey), o, 0.4) for o in tx_only) or \
                    any(seg_hits((ex, ey), (sx + (tw if right else -tw), ey), o, 0.4) for o in tx_only):
                continue
            best = (ux, uy, ex, ey, sx, right, tb)
            break
        if best:
            break
    if best is None:
        return False
    ux, uy, ex, ey, sx, right, tb = best
    tip = (center[0] + ux * rad, center[1] + uy * rad)
    nodes = [S.line(tip, (ex, ey), "dimension"), S.line((ex, ey), (sx + (tw if right else -tw), ey), "dimension"),
             S.arrow(tip, (ex, ey))]
    t = S.text(((sx + tw / 2) if right else (sx - tw / 2), ey + 1.0), d.text, TH, "middle", "baseline", 0, "dimension")
    nodes.append(t)
    d.nodes = nodes
    d.text_boxes = [S.text_box(t, 0.4)]
    d.line_boxes = [[min(tip[0], ex), min(tip[1], ey), max(tip[0], ex), max(tip[1], ey)]]
    return True


# ── assembling the dimensions of the views ─────────────────────────────────

def _project_box3(view: View, box3) -> list:
    pts = [view.at3((x, y, z)) for x in (box3[0], box3[3]) for y in (box3[1], box3[4]) for z in (box3[2], box3[5])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _linear_dim(spec, view: View, fits, sides) -> Dim | None:
    od = _dir2(view, spec["axis"])
    if od is None:
        return None
    orient, sgn = od
    u = _axis_vec(spec["axis"])
    vb = view.box()
    side = sides[orient]
    pts = []
    for at in (spec["from"], spec["to"]):
        q = view.at3(tuple(u * at))
        k = 0 if orient == "h" else 1
        coord = q[k]
        # where the extension line starts: the part's edge on that level, nearest the dimension side
        if spec["kind"] in ("location", "pitch") and spec.get("of"):
            other = None
            for c in spec.get("_cyls", []):
                cq = view.at3(tuple(c["at"]))
                if abs(cq[k] - coord) < 1e-6 * max(1, abs(coord)) + 1e-4:
                    other = cq[1 - k]
            if other is None:
                other = vb[1] if side == "bottom" else vb[3] if side == "top" else vb[0] if side == "left" else vb[2]
        else:
            other = vb[1] if side == "bottom" else vb[3] if side == "top" else vb[0] if side == "left" else vb[2]
            for pl in spec.get("planes") or []:
                if abs(pl["at"] - at) < 1e-4:
                    pb = _project_box3(view, pl["box"])
                    other = (pb[1] if side == "bottom" else pb[3] if side == "top" else pb[0] if side == "left" else pb[2])
        pts.append((coord, other) if orient == "h" else (other, coord))
    if abs(pts[0][0 if orient == "h" else 1] - pts[1][0 if orient == "h" else 1]) < 0.3:
        return None
    return Dim(spec, view, orient, pts[0], pts[1], label(spec, fits), side)


def _boss_dim(spec, view: View, fits, sides) -> Dim | None:
    """A cylinder seen from the side: its diameter measured across, perpendicular to the axis."""
    od = _dir2(view, spec["axis"])
    if od is None:
        return None
    orient = "v" if od[0] == "h" else "h"
    c = spec["cyls"][0]
    a = np.asarray(c["at"], float)
    d, x, y = V.basis(view.basis_view())
    perp = x if orient == "h" else y
    r = spec["value"] / 2
    mid = a + _axis_vec(spec["axis"]) * (sum(c["along"]) / 2)
    p0, p1 = view.at3(tuple(mid - perp * r)), view.at3(tuple(mid + perp * r))
    vb = view.box()
    side = sides[orient]
    if orient == "h":
        e = vb[1] if side == "bottom" else vb[3]
        p0, p1 = (p0[0], e), (p1[0], e)
    else:
        e = vb[0] if side == "left" else vb[2]
        p0, p1 = (e, p0[1]), (e, p1[1])
    return Dim(spec, view, orient, p0, p1, label(spec, fits), side)


def _center_marks(view: View, cands) -> list:
    out = []
    for c in cands:
        if c["kind"] != "diameter":
            continue
        for cy in c["cyls"]:
            od = _dir2(view, c["axis"])
            r = c["value"] / 2 * view.s
            if od is None:                               # seen as a circle: two crossing centre lines
                ctr = view.at3(tuple(cy["at"]))
                e = r + 2.0
                out += [S.line((ctr[0] - e, ctr[1]), (ctr[0] + e, ctr[1]), "center"),
                        S.line((ctr[0], ctr[1] - e), (ctr[0], ctr[1] + e), "center")]
            elif view.kind != "iso":                     # seen from the side: the axis
                a = np.asarray(cy["at"], float)
                u = _axis_vec(c["axis"])
                p0, p1 = view.at3(tuple(a + u * (cy["along"][0]))), view.at3(tuple(a + u * (cy["along"][1])))
                L = math.dist(p0, p1) or 1.0
                ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
                out.append(S.line((p0[0] - ux * 2, p0[1] - uy * 2), (p1[0] + ux * 2, p1[1] + uy * 2), "center"))
    return out


def hatch(loops: list, spacing: float = 2.5, angle: float = 45.0) -> list:
    """45 degree hatching inside the loops (even-odd, so holes stay clear), as line primitives."""
    if not loops:
        return []
    a = math.radians(angle)
    u = np.array([math.cos(a), math.sin(a)])
    nrm = np.array([-u[1], u[0]])
    segs = []
    for L in loops:
        P = np.asarray(L, float)
        for i in range(len(P)):
            segs.append((P[i], P[(i + 1) % len(P)]))
    allp = np.vstack([np.asarray(L, float) for L in loops])
    proj = allp @ nrm
    out = []
    k = math.floor(proj.min() / spacing) + 1
    while k * spacing < proj.max():
        c = k * spacing
        ts = []
        for p, q in segs:
            dp, dq = float(p @ nrm) - c, float(q @ nrm) - c
            if (dp > 0) != (dq > 0):
                t = dp / (dp - dq)
                x = p + (q - p) * t
                ts.append(float(x @ u))
        ts.sort()
        for i in range(0, len(ts) - 1, 2):
            p0 = u * ts[i] + nrm * c
            p1 = u * ts[i + 1] + nrm * c
            out.append(S.line(tuple(p0), tuple(p1), "hatch"))
        k += 1
    return out


# ── the projection symbol and the title block ─────────────────────────────

def projection_symbol(at, method: str, h: float = 10.0) -> list:
    """ISO 5456-2: a truncated cone in two views; in first angle the end view is on the right of the side view."""
    x, y = at
    w = h * 1.2
    side = [(x, y - h * 0.25), (x + w, y - h * 0.5), (x + w, y + h * 0.5), (x, y + h * 0.25)]
    ev = (x + w + h * 0.9, y) if method == "first" else (x - h * 0.9, y)
    out = [S.polyline(side, "visible", closed=True), S.circle(ev, h * 0.5, "visible"), S.circle(ev, h * 0.25, "visible"),
           S.line((x - 1, y), (x + w + 1, y), "center"), S.line((ev[0] - h * 0.6, ev[1]), (ev[0] + h * 0.6, ev[1]), "center"),
           S.line((ev[0], ev[1] - h * 0.6), (ev[0], ev[1] + h * 0.6), "center")]
    return out


def title_block(frame, fields: dict, method: str) -> dict:
    """ISO 7200 title block, 180 mm wide at the lower right of the frame. Empty fields stay empty: nothing invented."""
    W, H = 180.0, 44.0
    x0, y0 = frame[2] - W, frame[1]
    kids = [S.polyline([(x0, y0), (x0 + W, y0), (x0 + W, y0 + H), (x0, y0 + H)], "frame", closed=True)]
    rows = [(0, 11, [("title", 110, 5.0), ("number", 70, 3.5)]),
            (11, 11, [("material", 55, 2.5), ("mass", 35, 2.5), ("tolerance", 40, 2.5), ("revision", 25, 2.5),
                      ("sheet", 25, 2.5)]),
            (22, 11, [("owner", 55, 2.5), ("creator", 35, 2.5), ("approved", 40, 2.5), ("date", 50, 2.5)]),
            (33, 11, [("type", 55, 2.5), ("scale", 25, 2.5), ("projection", 40, 2.5), ("release", 60, 2.5)])]
    names = dict(STD.TITLE_FIELDS)
    for top, hh, cells in rows:
        yb = y0 + H - top - hh
        kids.append(S.line((x0, yb), (x0 + W, yb), "frame"))
        cx = x0
        for key, w, th in cells:
            kids.append(S.line((cx, yb), (cx, yb + hh), "frame"))
            kids.append(S.text((cx + 1.2, yb + hh - 1.2), names[key], 1.8, "start", "top", layer="thin"))
            val = str(fields.get(key) or "")
            if key == "projection":
                kids += projection_symbol((cx + 9, yb + hh / 2 - 1), method, 5.0)
                val = f"{method} angle"
                kids.append(S.text((cx + w - 1.2, yb + 1.5), val, 2.0, "end", layer="title"))
            elif val:
                size = th
                while S.text_width(val, size) > w - 2.4 and size > 1.6:
                    size -= 0.2
                kids.append(S.text((cx + 1.2, yb + 1.6), val, size, "start", layer="title"))
            cx += w
    return S.group("title", kids, "title", {"fields": fields, "standard": "ISO 7200"})


def border(size, frame) -> dict:
    W, H = size
    kids = [S.polyline([(frame[0], frame[1]), (frame[2], frame[1]), (frame[2], frame[3]), (frame[0], frame[3])],
                       "frame", closed=True)]
    for (x, y, dx, dy) in ((W / 2, 0, 0, 1), (W / 2, H, 0, -1), (0, H / 2, 1, 0), (W, H / 2, -1, 0)):   # centring marks
        L = 10.0 if dx == 0 else 20.0 if x == 0 else 10.0
        kids.append(S.line((x, y), (x + dx * L, y + dy * L), "frame"))
    return S.group("border", kids, "border", {"standard": "ISO 5457"})


# ── compose ────────────────────────────────────────────────────────────────

def _frame(size, name):
    W, H = size
    f = STD.FRAME_ANSI if name.startswith("ANSI") else STD.FRAME_ISO
    return [f["left"], f["bottom"], W - f["right"], H - f["top"]]


def _sides(name, method):
    # dimension sides away from the neighbouring views
    right_of_front = method == "third"
    if name == "front":
        return {"h": "bottom" if method == "third" else "top", "v": "left" if right_of_front else "right"}
    if name == "top":
        return {"h": "top" if method == "third" else "bottom", "v": "left" if right_of_front else "right"}
    if name == "right":
        return {"h": "bottom" if method == "third" else "top", "v": "right" if right_of_front else "left"}
    return {"h": "bottom", "v": "right"}


def _view_dims(view: View, plan: list, fits, method, assigned: set) -> list[Dim]:
    out = []
    sides = _sides(view.name, method)
    for spec in plan:
        if spec["id"] in assigned:
            continue
        k = spec["kind"]
        d = None
        if k in ("linear",):
            pref = {"x": ("front", "top"), "y": ("top", "right"), "z": ("front", "right")}[spec["axis"]]
            if view.name == pref[0] or (view.name == pref[1] and spec.get("_try_second")):
                d = _linear_dim(spec, view, fits, sides)
        elif k in ("location", "pitch"):
            if view.name == CIRCLE_VIEW.get(spec.get("view_axis")):
                d = _linear_dim(spec, view, fits, sides)
        elif k == "diameter":
            if spec.get("inner") and view.name == CIRCLE_VIEW[spec["axis"]]:
                d = Dim(spec, view, "leader", text=label(spec, fits))
            elif not spec.get("inner") and view.name in ("front", "right") and _dir2(view, spec["axis"]):
                d = _boss_dim(spec, view, fits, sides)
        elif k == "radius" and view.name == CIRCLE_VIEW[spec["axis"]]:
            d = Dim(spec, view, "leader", text=label(spec, fits))
        if d is not None:
            if d.p0 is not None:             # endpoints in the view's own frame: placed again when the view moves
                d.lp0 = (d.p0[0] - view.origin[0], d.p0[1] - view.origin[1])
                d.lp1 = (d.p1[0] - view.origin[0], d.p1[1] - view.origin[1])
            out.append(d)
            assigned.add(spec["id"])
    return out


def _at_origin(v, ds):
    for d in ds:
        d.p0 = (d.lp0[0] + v.origin[0], d.lp0[1] + v.origin[1])
        d.p1 = (d.lp1[0] + v.origin[0], d.lp1[1] + v.origin[1])


def layout_dims(views: list[View], occupied: list, region, view_boxes=()) -> list[Dim]:
    alld = []
    for v in views:
        groups = {}
        for d in v.dims:
            if d.orient in ("h", "v"):
                groups.setdefault(d.side, []).append(d)
        for side, ds in groups.items():
            _at_origin(v, ds)
            _place_linear(ds, v.box(), occupied)
            for d in ds:
                occupied += d.text_boxes
        alld += v.dims
    boxes = [v.box() for v in views]
    for v in views:
        for d in v.dims:
            if d.orient != "leader":
                continue
            spec = d.spec
            c = spec["cyls"][0]
            ctr = v.at3(tuple(c["at"]))
            rad = (spec["value"] / 2 if spec["kind"] == "diameter" else spec["value"]) * v.s
            angles = None
            if spec["kind"] == "radius":      # a round: the leader leaves its arc outward, away from the part's middle
                vb = v.box()
                mid = ((vb[0] + vb[2]) / 2, (vb[1] + vb[3]) / 2)
                best = None
                for cy in spec["cyls"]:
                    q = v.at3(tuple(cy["at"]))
                    a0 = math.degrees(math.atan2(q[1] - mid[1], q[0] - mid[0]))
                    if best is None or abs(((a0 - 45) + 180) % 360 - 180) < abs(((best[1] - 45) + 180) % 360 - 180):
                        best = (q, a0)
                if best:
                    ctr, a0 = best
                    angles = [a0, a0 + 12, a0 - 12, a0 + 24, a0 - 24]
            lines = [b for dd in alld for b in dd.line_boxes]
            texts = [b for b in occupied if not any(b is vb for vb in view_boxes)]
            if not _leader(d, ctr, rad, texts + lines, region, boxes, texts, angles):
                d.nodes, d.failed = [], True
            occupied += d.text_boxes
    return alld


def compose(raw: dict, plan: list, annotations: dict, title: dict, sheet: str = "A3", projection: str = "first",
            theme: str = "night", details: list | None = None, cands=None) -> dict:
    if sheet not in STD.SHEETS:
        raise ValueError(f"sheet must be one of {', '.join(STD.SHEETS)}")
    if projection not in STD.PROJECTIONS:
        raise ValueError("projection must be first or third (ISO 5456-2)")
    size = STD.SHEETS[sheet]
    frame = _frame(size, sheet)
    tb = [frame[2] - 180.0, frame[1], frame[2], frame[1] + 44.0]
    fits = annotations.get("fits_by_dim", {})
    cyl_of = {c["id"]: c.get("cyls", []) for c in (cands or [])}
    for spec in plan:
        if spec.get("of"):
            spec["_cyls"] = cyl_of.get(spec["of"], [])
    if details is None:
        details = auto_details(raw)
    used = {x.get("id") for x in raw.get("sections", [])} | {a["letter"] for a in annotations.get("datum", [])}
    for dd in details:                 # view letters never repeat a section's or a datum's
        if dd["id"] in used:
            dd["id"] = next(c for c in G.LETTERS if c not in used)
        used.add(dd["id"])
    best = None
    for sc_ in STD.SCALES:
        s = sc_[0] / sc_[1]
        res = _arrange(raw, plan, fits, s, projection, frame, tb, details)
        if res is not None and res["fits"]:
            best = (sc_, res)
            break
        if best is None and res is not None:
            best = (sc_, res)
    sc_, res = best
    views, dims = res["views"], res["dims"]
    title = {**title, "scale": STD.scale_text(sc_), "projection": projection}
    children = [border(size, frame), title_block(frame, title, projection)]
    for v in views:
        kids = v.edges()
        if v.kind == "section":
            loops = [[v.p(q) for q in L] for L in v.raw.get("cut_loops", [])]
            kids += hatch(loops)
        if v.kind == "detail":
            c = v.p(v.c2)
            R_ = v.rr * v.s
            if v.host.kind == "section":                       # the hatching, cut to the detail's circle
                loops = [[v.p(q) for q in L] for L in v.host.raw.get("cut_loops", [])]
                for h in hatch(loops):
                    for (t0, t1) in _seg_in_circle(h["a"], h["b"], c, R_):
                        a, b = h["a"], h["b"]
                        kids.append(S.line((a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                                           (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1), "hatch"))
            kids.append(S.circle(c, R_, "thin"))
            hc = v.host.p(v.c2)
            hr = v.rr * v.host.s
            letter = v.name.split("_", 1)[1]
            mark = [S.circle(hc, hr, "thin"),
                    S.text((hc[0] + hr * 0.75 + 2.0, hc[1] + hr * 0.75 + 2.0), letter, STD.TEXT_H["dimension"], "start",
                           layer="text")]
            children.append(S.group("detail_mark", mark, f"detail_mark_{letter}", {"detail": letter, "view": v.host.name}))
        kids += _center_marks(v, cands or []) if v.kind not in ("iso", "detail") else []
        lab = v.label or {"front": "", "top": "", "right": "", "iso": ""}.get(v.name, "")
        if lab:
            b = v.box()
            kids.append(S.text(((b[0] + b[2]) / 2, b[3] + 4.0), lab, STD.TEXT_H["label"], "middle", layer="text"))
        children.append(S.group(v.kind if v.kind in ("section", "detail") else "view", kids, f"view_{v.name}",
                                {"view": v.name, "scale": v.s, "origin": [S.r(v.origin[0]), S.r(v.origin[1])],
                                 "basis": [list(map(float, b)) for b in V.basis(v.basis_view())]}))
    unplaced = []
    # cutting planes (ISO 128-40): a chain line through the view that shows the plane edge-on, thick at its ends,
    # arrows in the direction of viewing, the section's letter at each end
    for sv in [v for v in views if v.kind == "section"]:
        pl = sv.raw["plane"]
        host = next((v for v in views if v.kind == "view" and abs(float(np.dot(V.basis(v.basis_view())[0], pl["normal"]))) < 1e-6), None)
        if host is None:
            continue
        b = host.box()
        o = host.at3(tuple(pl["origin"]))
        nd = V.basis(host.basis_view())
        n2 = (float(np.dot(pl["normal"], nd[1])), float(np.dot(pl["normal"], nd[2])))
        t2 = (-n2[1], n2[0])
        half = abs(t2[0]) * (b[2] - b[0]) / 2 + abs(t2[1]) * (b[3] - b[1]) / 2
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        c_along = (o[0] - cx) * t2[0] + (o[1] - cy) * t2[1]
        base = (o[0] - t2[0] * c_along, o[1] - t2[1] * c_along)
        L = half + 3.0
        p0 = (base[0] - t2[0] * L, base[1] - t2[1] * L)
        p1 = (base[0] + t2[0] * L, base[1] + t2[1] * L)
        kids = [S.line(p0, p1, "center")]
        letter = sv.raw.get("id", "A")
        for q, sgn in ((p0, 1), (p1, -1)):
            e = (q[0] + t2[0] * sgn * 4, q[1] + t2[1] * sgn * 4)
            kids.append(S.line(q, e, "section"))
            head = (q[0] - n2[0] * 6, q[1] - n2[1] * 6)       # the arrow points away from the viewer, into the part
            kids += [S.line(q, head, "dimension"), S.arrow(head, q, 2.5)]
            kids.append(S.text((head[0] - n2[0] * 3.2, head[1] - n2[1] * 3.2), letter, STD.TEXT_H["dimension"],
                               "middle", "middle", layer="text"))
        children.append(S.group("cutting_plane", kids, f"cut_{letter}", {"section": letter, "view": host.name}))
    for d in dims:
        if getattr(d, "failed", False) or not d.nodes:
            unplaced.append(d.spec["id"])
            continue
        sp = d.spec
        meta = {"candidate": sp["id"], "kind": sp["kind"], "axis": sp.get("axis"), "value": sp["value"],
                "param": sp.get("param"), "binding": sp.get("binding"), "feature": (sp.get("features") or [None])[0],
                "features": sp.get("features", []), "faces": sp.get("faces", []), "view": d.view.name,
                "text": d.text, "mode": sp.get("mode")}
        if sp["id"] in fits or (sp.get("param") and sp["param"] in fits):
            meta["fit"] = fits.get(sp["id"]) or fits.get(sp["param"])
        children.append(S.group("dimension", d.nodes, f"dim_{sp['id']}", meta))
    occupied = [b for d in dims for b in d.text_boxes]
    occupied += [tb] + [S.text_box(c, 0.4) for g in children if g.get("role") in ("cutting_plane", "detail_mark")
                        for c in g["children"] if c["kind"] == "text"]
    vboxes = [v.box() for v in views]
    region = [frame[0] + 2, frame[1] + 2, frame[2] - 2, frame[3] - 2]
    lines = [b for d in dims for b in d.line_boxes]
    # datums, frames and surface symbols where a view shows their face edge-on
    for kind in ("datum", "gdt", "surface"):
        for a in annotations.get(kind, []):
            g = _annotate(a, kind, views, occupied + lines, region, vboxes)
            if g is None:
                unplaced.append(a.get("id") or a.get("letter"))
                continue
            children.append(g)
            occupied.append(g["bbox"])
    notes = annotations.get("notes") or []
    ny = tb[3] + 4.0
    for n in reversed(notes):
        t = S.text((tb[0], ny), n, STD.TEXT_H["note"], "start", layer="text")
        children.append(S.group("note", [t], f"note_{len(children)}", {"text": n}))
        ny += STD.TEXT_H["note"] * 1.8
    sheet_node = {"kind": "sheet", "version": S.VERSION, "name": sheet, "size": list(size), "frame": frame,
                  "title_box": tb, "projection": projection, "scale": list(sc_), "theme": theme,
                  "colors": S.THEMES[theme], "children": children, "fits_sheet": res["fits"], "unplaced": unplaced}
    return sheet_node


def _annotate(a, kind, views, occupied, region, vboxes):
    """Place a datum triangle, a feature control frame or a surface symbol on the face's edge in the first view
    that shows the face edge-on (a plane parallel to the view direction), with a leader."""
    hits = []                 # (view, foot, outward direction): every place the face shows, in view order
    for v in views:
        if v.kind in ("iso", "detail"):
            continue
        d, x, y = V.basis(v.basis_view())
        for f in a.get("_faces_geo", [])[:1]:
            if f["type"] == "plane":
                n = np.asarray(f["normal"], float)
                if abs(float(n @ d)) > 1e-6:
                    continue
                pb = _project_box3(v, f["box"])
                hits.append((v, ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2), (float(n @ x), float(n @ y))))
            elif f["type"] == "cylinder" and _dir2(v, f["axis"]) is not None:
                c = np.asarray(f["at"], float) + V.AXES[f["axis"]] * f["along"][1]
                ctr = v.at3(tuple(c))
                od = _dir2(v, f["axis"])
                for sg in (1.0, -1.0):
                    perp = (0.0, sg) if od[0] == "h" else (sg, 0.0)
                    hits.append((v, (ctr[0] + perp[0] * f["r"] * v.s, ctr[1] + perp[1] * f["r"] * v.s), perp))
            elif f["type"] == "cylinder":                      # seen as a circle: on the circle, radially out
                ctr = v.at3(tuple(f["at"]))
                for ang in (225, 315, 135, 45, 180, 0, 270, 90):
                    u = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
                    hits.append((v, (ctr[0] + u[0] * f["r"] * v.s, ctr[1] + u[1] * f["r"] * v.s), u))
    for v, foot, out in hits:
        if kind == "datum":
            for k in range(1, 12):
                g = G.datum_feature(a["letter"], foot, out, STD.TEXT_H["dimension"], f"datum_{a['letter']}",
                                    {"faces": a.get("faces"), "view": v.name, "letter": a["letter"]})
                g = _shift_until_free(g, foot, out, occupied, region, vboxes, k)
                if g is not None:
                    return g
            continue
        if kind == "gdt":
            g0 = G.frame(a, (0, 0), STD.TEXT_H["dimension"], f"gdt_{a.get('id', '')}", {"faces": a.get("faces"), "view": v.name})
        else:
            g0 = G.surface_symbol(a, (0, 0), STD.TEXT_H["dimension"], f"surface_{a.get('id', '')}",
                                  {"faces": a.get("faces"), "view": v.name})
        w, h = g0["bbox"][2] - g0["bbox"][0], g0["bbox"][3] - g0["bbox"][1]
        spot = free_spot(w, h, (foot[0] + out[0] * 14, foot[1] + out[1] * 14), occupied, region, 4.0, 3.0, vboxes)
        if spot is None:
            continue
        dx, dy = spot[0] - g0["bbox"][0], spot[1] - g0["bbox"][1]
        g = _translate(g0, dx, dy)
        b = g["bbox"]
        near = (min(max(foot[0], b[0]), b[2]), min(max(foot[1], b[1]), b[3]))
        lead = [S.line(near, foot, "gdt" if kind == "gdt" else "dimension"), S.arrow(foot, near, 2.5,
                                                                                   "gdt" if kind == "gdt" else "dimension")]
        g["children"] = lead + g["children"]
        g["bbox"] = S.bbox(g)
        g["meta"]["leader"] = [S.P(near), S.P(foot)]
        g["meta"]["box"] = b
        return g
    return None


def _shift_until_free(g, foot, out, occupied, region, vboxes, k):
    box = g["bbox"]
    tri_box = [foot[0] - 3, foot[1] - 3, foot[0] + 3, foot[1] + 3]
    # the boxed letter is the part that must be clear (the triangle sits on the part)
    letter = [c for c in g["children"] if c["kind"] == "polyline"][0]
    lb = S.bbox(letter)
    if k > 1:
        L = 4.0 * (k - 1)
        g = _translate(g, out[0] * L, out[1] * L)
        g["children"].append(S.line(foot, (foot[0] + out[0] * L, foot[1] + out[1] * L), "gdt"))
        lb = [lb[0] + out[0] * L, lb[1] + out[1] * L, lb[2] + out[0] * L, lb[3] + out[1] * L]
        g["bbox"] = S.bbox(g)
    if lb[0] < region[0] or lb[2] > region[2] or lb[1] < region[1] or lb[3] > region[3]:
        return None
    if any(S.overlap(lb, o, 0.8) for o in occupied) or any(S.overlap(lb, vb, 0.3) for vb in vboxes):
        return None
    g["meta"]["box"] = lb
    del box, tri_box
    return g


def _translate(node, dx, dy):
    import copy
    n = copy.deepcopy(node)

    def mv(e, d, p):
        for k in ("a", "b", "c", "at"):
            if k in e and isinstance(e[k], list):
                e[k] = [S.r(e[k][0] + dx), S.r(e[k][1] + dy)]
        if "pts" in e:
            e["pts"] = [[S.r(p[0] + dx), S.r(p[1] + dy)] for p in e["pts"]]
    S.walk(n, mv)

    def rb(e, d, p):
        if e["kind"] == "group":
            e["bbox"] = S.bbox(e)
    S.walk(n, rb)
    return n


def _arrange(raw, plan, fits, s, method, frame, tb, details):
    names = [n for n in ("front", "top", "right", "iso") if n in raw["views"]]
    views = {n: View(n, raw["views"][n], s, kind="iso" if n == "iso" else "view") for n in names}
    secs = [View(f"section_{x['id']}", x, s, f"{x['id']}–{x['id']}", "section") for x in raw.get("sections", [])]
    assigned: set = set()
    for n in ("front", "top", "right"):
        if n in views:
            views[n].dims = _view_dims(views[n], plan, fits, method, assigned)
    for spec in plan:                         # a linear size the first choice could not show: try the second view
        if spec["id"] not in assigned and spec["kind"] == "linear":
            spec["_try_second"] = True
    for n in ("front", "top", "right"):
        if n in views:
            views[n].dims += _view_dims(views[n], plan, fits, method, assigned)
    # margins each view needs for its dimensions (tiers) on each side, at this scale
    memo = {}

    def margins(v):
        """What the view's own dimensions take on each side: laid out once at the origin and measured."""
        if v.name in memo:
            return memo[v.name]
        m = {"left": 3.0, "right": 3.0, "top": 3.0, "bottom": 3.0}
        if v.label:
            m["top"] = 9.0
        groups = {}
        for d in v.dims:
            if d.orient in ("h", "v"):
                groups.setdefault(d.side, []).append(d)
        b = v.box()
        for side, ds in groups.items():
            _at_origin(v, ds)
            _place_linear(ds, b, [])
            for d in ds:
                for n in d.nodes:
                    nb = S.bbox(n)
                    m["left"] = max(m["left"], b[0] - nb[0] + 2)
                    m["bottom"] = max(m["bottom"], b[1] - nb[1] + 2)
                    m["right"] = max(m["right"], nb[2] - b[2] + 2)
                    m["top"] = max(m["top"], nb[3] - b[3] + 2)
        leaders = [d for d in v.dims if d.orient == "leader"]
        if leaders:
            w = max(S.text_width(d.text, TH) for d in leaders) + 10.0
            for k in m:
                m[k] = max(m[k], w if k in ("left", "right") else 16.0)
        memo[v.name] = m
        return m
    gap = 10.0
    # grid placement per ISO 5456-2: front, the top view in its column, the right view in its row
    F, T, R, I = (views.get(k) for k in ("front", "top", "right", "iso"))
    mF = margins(F)
    mT = margins(T) if T else None
    mR = margins(R) if R else None
    fb = F.geom_box
    tbx = T.geom_box if T else None
    rb = R.geom_box if R else None
    x0, y1 = frame[0] + 4, frame[3] - 4
    ox_rel = max(mF["left"] - fb[0], (mT["left"] - tbx[0]) if T else -1e9)           # column A: front and top
    colA_w = ox_rel + max(fb[2] + mF["right"], (tbx[2] + mT["right"]) if T else -1e9)
    oy_rel = max(mF["top"] + fb[3], (mR["top"] + rb[3]) if R else -1e9)               # row F: front and right
    rowF_h = oy_rel + max(mF["bottom"] - fb[1], (mR["bottom"] - rb[1]) if R else -1e9)
    colR_w = (mR["left"] - rb[0] + rb[2] + mR["right"]) if R else 0.0
    rowT_h = (mT["top"] + tbx[3] + mT["bottom"] - tbx[1]) if T else 0.0
    if method == "third":        # top above front, right view to the right of the front
        cA, cR = x0, x0 + colA_w + gap
        rT_top, rF_top = y1, y1 - rowT_h - gap
    else:                         # first angle: top view below the front, right view on its left
        cR, cA = x0, x0 + colR_w + gap
        rF_top, rT_top = y1, y1 - rowF_h - gap
    F.origin = np.array([cA + ox_rel, rF_top - oy_rel])
    if T:
        T.origin = np.array([F.origin[0], rT_top - mT["top"] - tbx[3]])
    if R:
        R.origin = np.array([cR + mR["left"] - rb[0], F.origin[1]])
    placed = [v for v in (F, T, R) if v]
    region = [frame[0] + 2, frame[1] + 2, frame[2] - 2, frame[3] - 2]

    def deco_of(v):
        m = margins(v)
        bb = v.box()
        return [bb[0] - m["left"], bb[1] - m["bottom"], bb[2] + m["right"], bb[3] + m["top"]]
    deco = [deco_of(v) for v in placed]
    # the isometric and the sections: the nearest free place to the empty grid cell, clear of everything placed
    cell = (cR + colR_w / 2, rT_top - rowT_h / 2) if method == "first" else (cR + colR_w / 2, rT_top - rowT_h / 2)
    dets = []
    for k, dd in enumerate(details):
        host = next((v for v in placed + secs if v.name == dd["host"]), None)
        if host is None or dd["size"] * s >= 2.0:          # big enough to read on the sheet: no detail needed
            continue
        sd = next((a / b for a, b in reversed(STD.SCALES) if a / b >= max(2 * s, 16.0 / dd["r"])), STD.SCALES[0][0])
        dv = View(f"detail_{dd['id']}", _clip_view(host.raw, dd["c2"], dd["r"]), sd,
                  f"{dd['id']} ({STD.scale_text(_ratio(sd))})", "detail")
        dv.host, dv.c2, dv.rr = host, dd["c2"], dd["r"]
        dets.append(dv)
    for v in ([I] if I else []) + secs + dets:
        v.dims = []
        gb = v.geom_box
        w, h = gb[2] - gb[0] + 8, gb[3] - gb[1] + 14
        spot = _find_place(w, h, cell, deco + [tb], region)
        if spot is None:
            return None
        v.origin = np.array([spot[0] + 4 - gb[0], spot[1] + 4 - gb[1]])
        placed.append(v)
        deco.append([spot[0], spot[1], spot[0] + w, spot[1] + h])
    ok = all(region[0] <= d[0] and d[2] <= region[2] and region[1] <= d[1] and d[3] <= region[3] for d in deco)
    ok = ok and not any(S.overlap(d, tb, 0.5) for d in deco)
    ok = ok and not any(S.overlap(deco[i], deco[j], 0.0) for i in range(len(deco)) for j in range(i + 1, len(deco)))
    if not ok:
        return None
    vbs = [v.box() for v in placed]
    occupied = [tb] + vbs
    dims = layout_dims([v for v in placed if v.dims], occupied, region, vbs)
    if any(getattr(d, "failed", False) for d in dims):
        return {"fits": False, "views": placed, "dims": dims}
    tbox = [b for d in dims for b in d.text_boxes]
    if any(S.overlap(tbox[i], tbox[j], -0.05) for i in range(len(tbox)) for j in range(i + 1, len(tbox))):
        return {"fits": False, "views": placed, "dims": dims}
    return {"fits": True, "views": placed, "dims": dims}


def _ratio(s: float) -> tuple:
    for a, b in STD.SCALES:
        if abs(a / b - s) < 1e-9:
            return (a, b)
    return (s, 1)


def _seg_in_circle(p, q, c, r) -> list:
    """Parameter intervals (t0, t1) of the segment p-q inside the circle."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    fx, fy = p[0] - c[0], p[1] - c[1]
    A = dx * dx + dy * dy
    if A < 1e-18:
        return []
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc <= 0:
        return []
    sq = math.sqrt(disc)
    t0, t1 = max(0.0, (-B - sq) / (2 * A)), min(1.0, (-B + sq) / (2 * A))
    return [(t0, t1)] if t1 > t0 else []


def _clip_view(raw: dict, c2, rr) -> dict:
    """The part of a view's edges inside a circle (a detail view's content), in the view's own coordinates."""
    edges = []
    for e in raw["edges"]:
        P = V._samples(e, 2 if e["kind"] == "line" else 64)
        run = []
        for a, b in zip(P[:-1], P[1:]):
            iv = _seg_in_circle(a, b, c2, rr)
            if not iv:
                if len(run) > 1:
                    edges.append({"kind": "poly", "pts": run, "layer": e["layer"]})
                run = []
                continue
            t0, t1 = iv[0]
            pa = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0]
            pb = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1]
            if not run or math.dist(run[-1], pa) > 1e-9:
                if len(run) > 1:
                    edges.append({"kind": "poly", "pts": run, "layer": e["layer"]})
                run = [pa]
            run.append(pb)
        if len(run) > 1:
            edges.append({"kind": "poly", "pts": run, "layer": e["layer"]})
    return {"edges": edges, "box": [c2[0] - rr, c2[1] - rr, c2[0] + rr, c2[1] + rr], "plane": raw.get("plane"),
            "cut_loops": raw.get("cut_loops", [])}


def auto_details(raw: dict) -> list:
    """Detail views for chamfers (cone faces): a circle around the smallest one, in the section when there is one."""
    m = raw["measure"]
    cones = sorted(m.get("cones") or [], key=lambda c: max(c["box"][5] - c["box"][2], 1e-6))
    if not cones:
        return []
    c = cones[0]
    size = min(max(c["box"][3] - c["box"][0], c["box"][4] - c["box"][1]), c["box"][5] - c["box"][2]) or 0.5
    sec = (raw.get("sections") or [None])[0]
    if sec is not None:
        pl = sec["plane"]
        host = f"section_{sec['id']}"
        view = (tuple(pl["normal"]), tuple(pl["right"]))
        right = np.asarray(pl["right"], float)
        b = np.asarray(c["box"], float)
        mid = (b[:3] + b[3:]) / 2
        p = mid + right * (float(right @ (b[3:] - b[:3])) / 2)       # where the cone meets the cutting plane
        p = p - np.asarray(pl["normal"]) * float(np.dot(p - np.asarray(pl["origin"]), pl["normal"]))
    else:
        host, view = "front", "front"
        b = np.asarray(c["box"], float)
        p = (b[:3] + b[3:]) / 2
    c2 = V.to2d(tuple(p), view)
    return [{"id": "B", "host": host, "c2": [c2[0], c2[1]], "r": max(2.5, 4 * size), "size": size,
             "face": c["face"], "feature": c["feature"]}]


def _find_place(w, h, prefer, occupied, region, step=3.0):
    """The free w x h box (lower-left corner) nearest to `prefer`, inside region, clear of occupied."""
    best, bd = None, 1e18
    y = region[1]
    while y + h <= region[3]:
        x = region[0]
        while x + w <= region[2]:
            box = [x, y, x + w, y + h]
            d = (x + w / 2 - prefer[0]) ** 2 + (y + h / 2 - prefer[1]) ** 2
            if d < bd and not any(S.overlap(box, o, 0.5) for o in occupied):
                best, bd = (x, y), d
            x += step
        y += step
    return best


# ── the check every sheet passes ───────────────────────────────────────────

def overlaps(sheet: dict) -> list:
    """Every pair of things that must not touch and do: dimension texts, frames, datum boxes, notes, the title
    block and the views' geometry. Empty on a good sheet."""
    items = []
    for g in S.groups(sheet):
        if g["role"] in ("dimension", "cutting_plane", "detail_mark"):
            for c in g["children"]:
                if c["kind"] == "text":
                    items.append((g["id"], "text", S.text_box(c)))
        elif g["role"] in ("gdt", "surface"):
            items.append((g["id"], g["role"], g["meta"].get("box") or g["bbox"]))
        elif g["role"] == "datum":
            items.append((g["id"], "datum", g["meta"].get("box") or g["bbox"]))
        elif g["role"] == "note":
            items.append((g["id"], "note", g["bbox"]))
    views = [(g["id"], "view", _geom_box(g)) for g in S.groups(sheet) if g["role"] in ("view", "section", "detail")]
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if S.overlap(items[i][2], items[j][2], -0.05):
                out.append((items[i][0], items[j][0]))
        for vid, _k, vb in views:
            if vb and S.overlap(items[i][2], vb, -0.05):
                out.append((items[i][0], vid))
        if S.overlap(items[i][2], sheet["title_box"], -0.05):
            out.append((items[i][0], "title"))
    return out


def _geom_box(g):
    out = None
    for c in g["children"]:
        if c["kind"] == "text" or c.get("layer") == "center":
            continue
        b = S.bbox(c)
        if b is None:
            continue
        out = list(b) if out is None else [min(out[0], b[0]), min(out[1], b[1]), max(out[2], b[2]), max(out[3], b[3])]
    return out
