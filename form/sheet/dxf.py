"""DXF out and in, with ezdxf (MIT): flat patterns and cut profiles written on named layers, any DXF read back into
the entities of form/sheet/geom2d.py with each layer's intent.

Layers written:

    CUT        the outline and every hole, as closed contours (lines, arcs, circles; polylines only where an
               edge is neither, such as a hole crossing a bend)
    BEND_UP    bend centre lines that bend toward the viewer (the flat seen from its top, the side its +Z faces)
    BEND_DOWN  bend centre lines that bend away
    ETCH       marks to etch, never cut: the part label as outlines, the footprints of formed features
    NOTES      one note per bend (direction, angle, inside radius, K-factor, allowance) as TEXT: notes are for
               people and are not cut. A shop that cuts every layer must drop NOTES first; the cut-file check
               flags text on any cut or etch layer.

The units are millimetres ($INSUNITS 4, $MEASUREMENT 1).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import geom2d

LAYERS = {"CUT": 7, "BEND_UP": 3, "BEND_DOWN": 1, "ETCH": 5, "NOTES": 8}
INTENT_TOKENS = (
    ("bend", ("BEND", "FOLD")),
    ("etch", ("ETCH", "ENGRAVE", "MARK", "SCRIBE")),
    ("ignore", ("DIM", "NOTE", "TEXT", "TITLE", "BORDER", "FRAME", "REF", "CENTER", "CENTRE", "HIDDEN",
                "DEFPOINTS", "CONSTRUCTION", "ANNO", "VIEWPORT")),
    ("cut", ("CUT", "OUTLINE", "PROFILE", "CONTOUR", "OUTER", "INNER", "THRU", "LASER")),
)
UNITS = {0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 13: "µm"}
TO_MM = {"in": 25.4, "ft": 304.8, "mm": 1.0, "cm": 10.0, "m": 1000.0, "µm": 0.001}


def intent(layer: str) -> tuple[str, bool]:
    """(cut | bend | etch | ignore, known?) for a layer name. A layer named nothing we know is cut, as shops cut
    every line they are sent, and is reported as assumed."""
    name = (layer or "0").upper()
    for kind, toks in INTENT_TOKENS:
        if any(tok in name for tok in toks):
            return kind, True
    if name == "0":
        return "cut", True
    return "cut", False


def write(path, entities: list, bends: list | None = None, etch: list | None = None, title: str = "") -> str:
    """Write cut entities (geom2d form), bend lines and etch marks to a DXF in mm."""
    import ezdxf
    from ezdxf import units
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    for name, color in LAYERS.items():
        if name not in doc.layers:
            lay = doc.layers.add(name, color=color)
            if name.startswith("BEND") and "DASHED" in doc.linetypes:
                lay.dxf.linetype = "DASHED"
    msp = doc.modelspace()
    for e in entities:
        _add(msp, e, "CUT")
    placed: list = []
    for b in bends or []:
        lay = "BEND_UP" if b.get("direction") == "up" else "BEND_DOWN"
        (x0, y0), (x1, y1) = b["line"]
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": lay})
        note = bend_note(b)
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        if ang > 90 or ang < -90:
            ang += 180
        h = max(1.0, min(3.5, float(b.get("length", 20)) / 25))
        f = place_along(b["line"], 0.6 * h * len(note), h, placed)
        mid = (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
        txt = msp.add_text(note, dxfattribs={"layer": "NOTES", "height": h, "rotation": ang})
        txt.set_placement(mid, align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    for e in etch or []:
        _add(msp, e, "ETCH")
    if title:
        doc.header["$PROJECTNAME"] = title[:200]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(path))
    return str(path)


def place_along(line, w: float, h: float, placed: list) -> float:
    """Where along a bend line (a fraction) a note of width w and height h, written along the line, overlaps no
    note already placed (their boxes in `placed`, which this extends); the middle when nothing is free."""
    A, B = np.asarray(line, float)
    d = B - A
    L = float(np.linalg.norm(d)) or 1.0
    u = d / L
    nrm = np.array([-u[1], u[0]])
    for f in (0.5, 0.3, 0.7, 0.15, 0.85, 0.4, 0.6):
        c = A + d * f + nrm * (h / 2)
        corners = np.array([c + u * sx * w / 2 + nrm * sy * h / 2 for sx in (-1, 1) for sy in (-1, 1)])
        lo, hi = corners.min(axis=0), corners.max(axis=0)
        if not any(lo[0] < q[1][0] and q[0][0] < hi[0] and lo[1] < q[1][1] and q[0][1] < hi[1] for q in placed):
            placed.append((lo, hi))
            return f
    return 0.5


def bend_note(b: dict) -> str:
    return (f"{'UP' if b.get('direction') == 'up' else 'DOWN'} {b['angle']:.1f}° R{b['r']:.3g} "
            f"K{b['K']:.3g} BA{b['allowance']:.3f}")


def _add(msp, e: dict, layer: str) -> None:
    a = {"layer": e.get("layer") or layer}
    t = e["t"]
    if t == "line":
        msp.add_line(tuple(e["a"]), tuple(e["b"]), dxfattribs=a)
    elif t == "arc":
        msp.add_arc(tuple(e["c"]), float(e["r"]), float(e["a0"]), float(e["a1"]), dxfattribs=a)
    elif t == "circle":
        msp.add_circle(tuple(e["c"]), float(e["r"]), dxfattribs=a)
    else:
        msp.add_lwpolyline([tuple(p) for p in e["pts"]], close=bool(e.get("closed")), dxfattribs=a)


# ---- reading ------------------------------------------------------------------------------------------------

def read(path, units: str | None = None) -> dict:
    """Every drawable entity of a DXF as geom2d entities in mm with its layer and the layer's intent; texts,
    blocks exploded, and what could not be read.

    {"entities": [...], "texts": [{"layer", "text", "at"}], "units": "mm" | ..., "units_source": "$INSUNITS" |
     "given" | "assumed", "scale": to mm, "layers": {name: {"intent", "known", "count"}}, "skipped": {type: n}}"""
    import ezdxf
    try:
        doc = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as e:
        raise ValueError(f"Cannot read {Path(path).name} as DXF: {e}") from e
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    found = UNITS.get(code, f"code {code}")
    if units:
        u, src = units, "given"
    elif found in TO_MM:
        u, src = found, "$INSUNITS"
    else:
        u, src = "mm", "assumed"
    k = TO_MM.get(u, 1.0)
    out = {"entities": [], "texts": [], "units": u, "units_found": found, "units_source": src, "scale": k,
           "layers": {}, "skipped": {}, "inserts": 0}

    def note_layer(name):
        it, known = intent(name)
        L = out["layers"].setdefault(name, {"intent": it, "known": known, "count": 0})
        L["count"] += 1
        return it

    def walk(entities, depth=0):
        for e in entities:
            kind = e.dxftype()
            layer = e.dxf.get("layer", "0")
            if kind == "INSERT":
                out["inserts"] += 1
                if depth < 8:
                    walk(list(e.virtual_entities()), depth + 1)
                continue
            if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                note_layer(layer)
                txt = e.plain_text() if kind == "MTEXT" else e.dxf.get("text", "")
                ins = e.dxf.get("insert", (0, 0, 0))
                out["texts"].append({"layer": layer, "intent": intent(layer)[0], "text": str(txt)[:200],
                                     "at": [float(ins[0]) * k, float(ins[1]) * k], "type": kind})
                continue
            if kind in ("LWPOLYLINE", "POLYLINE"):
                if kind == "POLYLINE" and (e.is_polygon_mesh or e.is_poly_face_mesh):
                    out["skipped"][kind] = out["skipped"].get(kind, 0) + 1
                    continue
                parts = list(e.virtual_entities())
                closed = bool(e.closed if kind == "LWPOLYLINE" else e.is_closed)
                for sub in parts:
                    ent = _entity(sub, k)
                    if ent:
                        ent["layer"] = layer
                        ent["from"] = kind + (" closed" if closed else "")
                        note_layer(layer)
                        out["entities"].append(ent)
                continue
            ent = _entity(e, k)
            if ent is None:
                out["skipped"][kind] = out["skipped"].get(kind, 0) + 1
                continue
            ent["layer"] = layer
            note_layer(layer)
            out["entities"].append(ent)
    walk(list(doc.modelspace()))
    for e in out["entities"]:
        e["intent"] = out["layers"][e["layer"]]["intent"]
    return out


def _entity(e, k: float) -> dict | None:
    kind = e.dxftype()
    ext = e.dxf.get("extrusion", (0, 0, 1)) if e.dxf.hasattr("extrusion") else (0, 0, 1)
    flip = float(ext[2]) < 0
    if kind == "LINE":
        s, t = e.dxf.start, e.dxf.end
        return {"t": "line", "a": [s[0] * k, s[1] * k], "b": [t[0] * k, t[1] * k], "handle": e.dxf.get("handle")}
    if kind in ("ARC", "CIRCLE"):
        c = e.dxf.center
        cx, cy = float(c[0]), float(c[1])
        r = float(e.dxf.radius) * k
        if flip:
            cx = -cx
        if kind == "CIRCLE":
            return {"t": "circle", "c": [cx * k, cy * k], "r": r, "handle": e.dxf.get("handle")}
        a0, a1 = float(e.dxf.start_angle), float(e.dxf.end_angle)
        if flip:
            a0, a1 = 180.0 - a1, 180.0 - a0
        return {"t": "arc", "c": [cx * k, cy * k], "r": r, "a0": a0 % 360, "a1": a1 % 360, "handle": e.dxf.get("handle")}
    if kind in ("SPLINE", "ELLIPSE"):
        try:
            pts = np.array([(p[0], p[1]) for p in e.flattening(0.005 / max(k, 1e-9))], float) * k
        except Exception:                                # noqa: BLE001 - a broken curve is reported as skipped
            return None
        if len(pts) < 2:
            return None
        closed = bool(np.hypot(*(pts[0] - pts[-1])) < 1e-9)
        return {"t": "poly", "pts": (pts[:-1] if closed else pts).tolist(), "closed": closed, "handle": e.dxf.get("handle")}
    return None


def loops_of(entities: list, tol: float = 1e-3):
    """Closed loops and open chains of entities (geom2d.chain), nested."""
    loops, opens = geom2d.chain(entities, tol)
    geom2d.nest(loops)
    return loops, opens
