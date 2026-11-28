"""The sheet scene graph: what a drawing is, before any renderer sees it.

A sheet is a tree of plain dicts (JSON as it stands), in sheet millimetres with the origin at the lower left and y
up. Every renderer (SVG, PDF and PNG by Qt, DXF by ezdxf, the direction-I sheet pane) draws the same tree:

    {"kind": "sheet", "version": 1, "size": [420, 297], "name": "A3", "theme": {...}, "children": [group, ...]}

Groups carry what a thing *is*; primitives carry how it looks:

    group      {"kind": "group", "id", "role", "meta": {...}, "bbox": [x0, y0, x1, y1], "children": [...]}
               roles: border, title, view, section, detail, dimension, gdt, datum, surface, note, table
    line       {"kind": "line", "a": [x, y], "b": [x, y], "layer"}
    polyline   {"kind": "polyline", "pts": [[x, y], ...], "closed": bool, "layer"}
    circle     {"kind": "circle", "c": [x, y], "r", "layer", "fill": bool}
    arc        {"kind": "arc", "c": [x, y], "r", "a0", "a1" (degrees, counter-clockwise), "layer"}
    polygon    {"kind": "polygon", "pts": [...], "layer"}           (a filled area: arrowheads, hatch boundaries)
    text       {"kind": "text", "at": [x, y], "s", "h" (cap height mm), "anchor": "start|middle|end",
                "valign": "baseline|middle|top", "rot" (degrees), "layer"}

Layers name the line type (ISO 128-2): visible, hidden, center, dimension, hatch, section, frame, thin, text, gdt.
A theme maps layers to colours: "night" is the direction-I sheet (dark paper, cyan dimensions), "paper" is white.
A dimension group's meta says which parameter it is (param, feature, value, binding), so the UI can make the
dimension editable and the check can light the feature on the part.
"""
from __future__ import annotations

import math

VERSION = 1

THEMES = {
    "night": {"paper": "#10141a", "frame": "#5c6b7a", "visible": "#e8edf2", "hidden": "#7d8a98", "center": "#7d8a98",
              "section": "#e8edf2", "hatch": "#5c6b7a", "dimension": "#39c6e6", "text": "#e8edf2", "thin": "#5c6b7a",
              "gdt": "#39c6e6", "title": "#e8edf2", "accent": "#39c6e6"},
    "paper": {"paper": "#ffffff", "frame": "#000000", "visible": "#000000", "hidden": "#000000", "center": "#000000",
              "section": "#000000", "hatch": "#000000", "dimension": "#000000", "text": "#000000", "thin": "#000000",
              "gdt": "#000000", "title": "#000000", "accent": "#000000"},
}


def r(x: float) -> float:
    return round(float(x), 3)


def P(p) -> list:
    return [r(p[0]), r(p[1])]


def line(a, b, layer="visible") -> dict:
    return {"kind": "line", "a": P(a), "b": P(b), "layer": layer}


def polyline(pts, layer="visible", closed=False) -> dict:
    return {"kind": "polyline", "pts": [P(p) for p in pts], "closed": bool(closed), "layer": layer}


def circle(c, rad, layer="visible", fill=False) -> dict:
    return {"kind": "circle", "c": P(c), "r": r(rad), "layer": layer, "fill": bool(fill)}


def arc(c, rad, a0, a1, layer="visible") -> dict:
    return {"kind": "arc", "c": P(c), "r": r(rad), "a0": r(a0), "a1": r(a1), "layer": layer}


def polygon(pts, layer="dimension") -> dict:
    return {"kind": "polygon", "pts": [P(p) for p in pts], "layer": layer}


def text(at, s, h=3.5, anchor="middle", valign="baseline", rot=0.0, layer="text") -> dict:
    return {"kind": "text", "at": P(at), "s": str(s), "h": r(h), "anchor": anchor, "valign": valign, "rot": r(rot),
            "layer": layer}


def group(role, children, gid="", meta=None) -> dict:
    g = {"kind": "group", "id": gid, "role": role, "meta": meta or {}, "children": children}
    g["bbox"] = bbox(g)
    return g


# Text extents: the renderers use real fonts; layout uses this width model of the same font (DejaVu Sans / the
# bundled ISO 3098 style) so a box measured here holds the rendered string. Width per character, in cap heights.
_NARROW = set("il.,:;|!'()[]1 ")
_WIDE = set("MWmw@%Ø⌀")


def text_width(s: str, h: float) -> float:
    w = 0.0
    for ch in s:
        w += 0.42 if ch in _NARROW else 1.05 if ch in _WIDE else 0.78
    return w * h * 1.06              # a little over the font: a box measured here always holds the string


def text_box(t: dict, pad: float = 0.0) -> list:
    """The axis-aligned box of a text primitive (rotation by multiples of 90 degrees)."""
    w, h = text_width(t["s"], t["h"]), t["h"]
    x, y = t["at"]
    x0 = {"start": 0.0, "middle": -w / 2, "end": -w}[t.get("anchor", "middle")]
    y0 = {"baseline": -0.25 * h, "middle": -0.6 * h, "top": -1.25 * h}[t.get("valign", "baseline")]
    box = [x0, y0, x0 + w, y0 + 1.25 * h]
    rot = round(t.get("rot", 0.0)) % 360
    if rot == 90:
        box = [-box[3], box[0], -box[1], box[2]]
    elif rot == 270:
        box = [box[1], -box[2], box[3], -box[0]]
    elif rot == 180:
        box = [-box[2], -box[3], -box[0], -box[1]]
    return [x + box[0] - pad, y + box[1] - pad, x + box[2] + pad, y + box[3] + pad]


def bbox(node) -> list | None:
    k = node["kind"]
    if k == "line":
        xs, ys = (node["a"][0], node["b"][0]), (node["a"][1], node["b"][1])
        return [min(xs), min(ys), max(xs), max(ys)]
    if k in ("polyline", "polygon"):
        if not node["pts"]:
            return None
        xs, ys = [p[0] for p in node["pts"]], [p[1] for p in node["pts"]]
        return [min(xs), min(ys), max(xs), max(ys)]
    if k in ("circle", "arc"):
        c, rad = node["c"], node["r"]
        return [c[0] - rad, c[1] - rad, c[0] + rad, c[1] + rad]
    if k == "text":
        return text_box(node)
    if k in ("group", "sheet"):
        out = None
        for ch in node["children"]:
            b = ch.get("bbox") if ch["kind"] == "group" else bbox(ch)
            if b is None:
                continue
            out = list(b) if out is None else [min(out[0], b[0]), min(out[1], b[1]), max(out[2], b[2]), max(out[3], b[3])]
        return out
    return None


def overlap(a, b, gap: float = 0.0) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def walk(node, fn, depth=0, parent=None):
    fn(node, depth, parent)
    for ch in node.get("children", ()):
        walk(ch, fn, depth + 1, node)


def groups(sheet, role=None) -> list:
    out = []
    walk(sheet, lambda n, d, p: out.append(n) if n["kind"] == "group" and (role is None or n["role"] == role) else None)
    return out


def arrow(tip, toward, size=2.5, layer="dimension") -> dict:
    """A filled arrowhead (ISO 129: closed, 15 degree half angle) with its tip at `tip`, pointing away from `toward`."""
    dx, dy = tip[0] - toward[0], tip[1] - toward[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    w = size * math.tan(math.radians(15))
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    return polygon([tip, (bx - uy * w, by + ux * w), (bx + uy * w, by - ux * w)], layer)


def stats(sheet) -> dict:
    n = {"groups": 0, "primitives": 0}

    def f(node, d, p):
        n["groups" if node["kind"] == "group" else "primitives"] += node["kind"] != "sheet"
    walk(sheet, f)
    return n
