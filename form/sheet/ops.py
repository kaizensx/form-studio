"""Sheet-metal work that needs the kernel (worker process only): the unfold of a design, the flat profile of a
planar part with optional kerf compensation, and text turned into outlines.

Kernel ops (form/kernel.py OPS):
    sheet_unfold   key, recipe_id, values, k (the bend table choice), label -> the flat pattern (form/sheet/unfold.py)
    sheet_profile  key, recipe_id, values, kerf, label                 -> the cut profile of a flat part
"""
from __future__ import annotations

import math

import numpy as np

from . import geom2d, tables, unfold


def kfactor_fn(k: dict | None):
    """A K-factor function (r, t, angle) for the unfold from the options: {"k": value} (specified), or {"method":
    "table" | "din6935", "material": id, "forming": "air" | "bottoming" | "coining"}."""
    k = dict(k or {})

    def fn(r, t, angle):
        return tables.kfactor(r, t, k.get("material"), k.get("method"), k.get("forming") or "air", k.get("k"))
    return fn


def _v(p):
    return unfold._v(p)


def edges_to_entities(edges, to2d) -> list:
    """build123d edges of a planar wire, mapped by to2d (3D points -> 2D), as geom2d entities."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    out = []
    for e in edges:
        kind = unfold._edge_kind(e)
        if kind == "line":
            P = to2d(np.array([_v(e.position_at(0)), _v(e.position_at(1))]))
            out.append({"t": "line", "a": P[0].tolist(), "b": P[1].tolist()})
            continue
        P = to2d(np.array([_v(e.position_at(t)) for t in np.linspace(0, 1, 65)]))
        if kind == "circle":
            circ = BRepAdaptor_Curve(e.wrapped).Circle()
            c = to2d(_v(circ.Location())[None])[0]
            r = float(circ.Radius())
            if float(np.hypot(*(P[0] - P[-1]))) < 1e-7:
                out.append({"t": "circle", "c": c.tolist(), "r": r})
                continue
            ang = np.degrees(np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0]))
            a0, a1, am = ang[0], ang[-1], ang[len(ang) // 2]
            if (am - a0) % 360 > (a1 - a0) % 360:
                a0, a1 = a1, a0
            out.append({"t": "arc", "c": c.tolist(), "r": r, "a0": float(a0 % 360), "a1": float(a1 % 360)})
            continue
        closed = float(np.hypot(*(P[0] - P[-1]))) < 1e-7
        out.append({"t": "poly", "pts": (P[:-1] if closed else P).tolist(), "closed": closed})
    return out


def text_outlines(text: str, height: float, at, angle: float = 0.0) -> list:
    """Text as closed outlines (no TEXT entities), its letters `height` mm high, centred at `at` in the flat."""
    from build123d import Text
    sk = Text(text, font_size=height)
    ents = []
    R = np.array([[math.cos(math.radians(angle)), -math.sin(math.radians(angle))],
                  [math.sin(math.radians(angle)), math.cos(math.radians(angle))]])
    bb = sk.bounding_box()
    c = np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2])
    shift = np.asarray(at, float)
    for f in sk.faces():
        for w in [f.outer_wire(), *f.inner_wires()]:
            ents += edges_to_entities(list(w.edges()), lambda P: (P[:, :2] - c) @ R.T + shift)
    for e in ents:
        e["layer"] = "ETCH"
    return ents


def _label(res: dict, label: str | None, label_at=None, height: float | None = None) -> list:
    if not label:
        return []
    text = str(label)[:40]
    size = res.get("size_mm") or [50, 50]
    h = float(height or max(2.0, min(8.0, min(size) / 10)))
    if label_at:
        return text_outlines(text, h, label_at)
    # the clearest place inside the outline: farthest from every contour and bend line
    ents = res.get("entities") or []
    loops, _o = geom2d.chain(ents, 1e-3)
    geom2d.nest(loops)
    outer = [lp for lp in loops if lp["depth"] == 0]
    if not outer:
        return []
    O = max(outer, key=lambda lp: abs(lp["area"]))
    holes = [lp for lp in loops if lp["depth"] == 1]
    lines = [lp["pts"] for lp in loops] + [np.asarray(b["line"], float) for b in res.get("bends") or []]
    lo, hi = O["pts"].min(axis=0), O["pts"].max(axis=0)
    best, at = -1.0, None
    n = 24
    for gx in np.linspace(lo[0], hi[0], n)[1:-1]:
        for gy in np.linspace(lo[1], hi[1], n)[1:-1]:
            p = np.array([gx, gy])
            if not geom2d.inside(p, O["pts"]) or any(geom2d.inside(p, hl["pts"]) for hl in holes):
                continue
            # clearance across the text's width counts most: test the point and two to each side
            w = 0.31 * h * len(text)
            probes = [p + np.array([dx, 0.0]) for dx in (-w, -w / 2, 0.0, w / 2, w)]
            d = min(geom2d.seg_dist(np.array([q]), L)[0] for q in probes for L in lines)
            if d > best:
                best, at = d, p
    if at is None:
        return []
    h = min(h, max(1.0, 0.8 * best))
    return text_outlines(text, h, at.tolist())


def op_sheet_unfold(key, recipe_id, values, k=None, label=None, label_at=None, tol=0.05):
    from .. import kernel
    model = kernel._get(key, recipe_id, values, tol)
    if getattr(model.get("recipe"), "mesh", False):
        return {"ok": False, "reasons": [{"why": "A mesh design has no exact solid to unfold."}], "mesh": True}
    res = unfold.unfold(model["shape"], kfactor_fn(k))
    res["etch"] = _label(res, label, label_at) if res.get("entities") else []
    return res


def profile(shape, kerf: float = 0.0) -> dict:
    """The cut profile of a flat part: a prism through its largest flat face. With kerf, every contour is offset
    half the kerf away from the material (the outline out, the holes in), as a cutter's path."""
    from build123d import Kind, Plane, offset
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    faces = list(shape.faces())
    planes = [f for f in faces if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Plane]
    if not planes:
        return {"ok": False, "reasons": [{"why": "No flat face: not a flat part."}]}
    F = max(planes, key=lambda f: f.area)
    n = _v(F.normal_at(F.center()))
    p0 = _v(F.center())
    reasons = []
    depths = set()
    for f in faces:
        s = BRepAdaptor_Surface(f.wrapped)
        kind = s.GetType()
        if kind == GeomAbs_Plane:
            nf = _v(f.normal_at(f.center()))
            c = float(abs(nf @ n))
            if c > 1 - 1e-7:
                depths.add(round(float((p0 - _v(f.center())) @ n), 6))
            elif c > 1e-7:
                reasons.append({"face": faces.index(f), "why": "A flat face neither parallel nor square to the sheet "
                                                               "(a chamfer or a bevel): a 2D cut cannot make it."})
        elif kind == GeomAbs_Cylinder:
            ax = _v(s.Cylinder().Axis().Direction())
            if abs(abs(float(ax @ n)) - 1) > 1e-7:
                reasons.append({"face": faces.index(f), "why": "A curved face that is not square to the sheet (a "
                                                               "fillet on an edge of the sheet): a 2D cut cannot make it."})
        else:
            reasons.append({"face": faces.index(f), "why": "A curved face of a kind a 2D cut cannot make."})
    ts = sorted(d for d in depths if d > 1e-6)
    t = ts[-1] if ts else 0.0
    if len(ts) > 1:
        reasons.append({"why": f"Flat faces at depths {', '.join(f'{d:g}' for d in ts[:-1])} mm as well as the far "
                               f"side at {t:g} mm: steps or pockets, not one cut through."})
    vol = float(shape.volume)
    if t > 0 and abs(vol - F.area * t) / vol > 1e-4 and not reasons:
        reasons.append({"why": f"Volume {vol:.3f} mm³ is not the face's area × {t:g} mm: the far side differs."})
    ex = None
    for e in F.outer_wire().edges():
        if unfold._edge_kind(e) == "line":
            d = _v(e.position_at(1)) - _v(e.position_at(0))
            if ex is None or np.linalg.norm(d) > np.linalg.norm(ex):
                ex = d
    if ex is None:
        ex = np.cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1, 0])
    ex = ex - (ex @ n) * n
    ex /= np.linalg.norm(ex)
    pl = Plane(origin=tuple(p0), x_dir=tuple(ex), z_dir=tuple(n))
    local = pl.to_local_coords(F)
    loc_face = local if hasattr(local, "outer_wire") else local.faces()[0]
    exact = edges_to_entities([e for w in [loc_face.outer_wire(), *loc_face.inner_wires()] for e in w.edges()],
                              lambda P: P[:, :2])
    path = []
    if kerf and kerf > 0:
        off = offset(loc_face, amount=kerf / 2, kind=Kind.ARC)
        of = off.faces()[0]
        path = edges_to_entities([e for w in [of.outer_wire(), *of.inner_wires()] for e in w.edges()],
                                 lambda P: P[:, :2])
    lo, _hi = geom2d.bbox(exact + path)
    for e in exact + path:
        unfold._shift(e, -lo)
    loops, opens = geom2d.chain(exact, 1e-4)
    geom2d.nest(loops)
    outer = [lp for lp in loops if lp["depth"] == 0]
    size = None
    if outer:
        mn, mx = geom2d.bbox([exact[k] for lp in outer for k, _ in lp["items"]])
        size = [round(float(mx[0] - mn[0]), 6), round(float(mx[1] - mn[1]), 6)]
    return {"ok": not reasons and not opens, "reasons": reasons, "t": t, "entities": path or exact,
            "exact": exact, "kerf_mm": float(kerf or 0.0), "compensated": bool(path),
            "frame": {"origin": (p0 + ex * lo[0] + np.cross(n, ex) * lo[1]).tolist(), "x": ex.tolist(),
                      "y": np.cross(n, ex).tolist(), "z": n.tolist()},
            "area_mm2": round(sum((1 if lp["depth"] % 2 == 0 else -1) * abs(geom2d.exact_area(lp, exact)) for lp in loops), 6),
            "size_mm": size, "contours": len(loops), "holes": sum(lp["depth"] % 2 == 1 for lp in loops)}


def op_sheet_profile(key, recipe_id, values, kerf=0.0, label=None, label_at=None, tol=0.05):
    from .. import kernel
    model = kernel._get(key, recipe_id, values, tol)
    if getattr(model.get("recipe"), "mesh", False):
        return {"ok": False, "reasons": [{"why": "A mesh design has no exact solid."}], "mesh": True}
    res = profile(model["shape"], float(kerf or 0.0))
    res["etch"] = _label(res, label, label_at) if res.get("entities") else []
    return res


KERNEL_OPS = {"sheet_unfold": op_sheet_unfold, "sheet_profile": op_sheet_profile}
