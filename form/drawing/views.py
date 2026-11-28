"""Views by OCCT hidden-line removal, sections and measurements: the kernel side of a drawing (worker process only).

A view is the solid projected along one direction by HLRBRep_Algo (exact, on the B-rep): visible sharp edges and
silhouettes are wide lines, visible tangent edges are narrow (ISO 128-2; they are left out of the hidden half), hidden
edges are dashed, and a hidden edge that lies under a visible one is dropped. Coordinates are the projection plane's,
in model millimetres: x along the view's right, y along its up.

    project(shape, "front")  -> {"edges": [{"layer", "kind": "line"|"circle"|"arc"|"poly", ...}], "box": [...]}
    section(shape, origin, normal, up) -> the cut half's view plus its cut faces as loops for hatching

Also: measure(shape) lists what a dimension can be made of (extents, plane levels, cylinders) from the B-rep.
"""
from __future__ import annotations

import math

import numpy as np

# view name -> (direction toward the viewer, the view's right). Up = direction x right. Front looks along +Y.
VIEWS = {
    "front": ((0, -1, 0), (1, 0, 0)),
    "back": ((0, 1, 0), (-1, 0, 0)),
    "top": ((0, 0, 1), (1, 0, 0)),
    "bottom": ((0, 0, -1), (1, 0, 0)),
    "right": ((1, 0, 0), (0, 1, 0)),
    "left": ((-1, 0, 0), (0, -1, 0)),
    "iso": ((1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3)), (1 / math.sqrt(2), 1 / math.sqrt(2), 0)),
}


def basis(view) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(toward viewer, right, up) unit vectors of a named view or a (direction, right) pair."""
    d, x = VIEWS[view] if isinstance(view, str) else view
    d, x = np.asarray(d, float), np.asarray(x, float)
    d /= np.linalg.norm(d)
    x = x - d * float(x @ d)
    x /= np.linalg.norm(x)
    return d, x, np.cross(d, x)


def to2d(p, view) -> tuple[float, float]:
    _, x, y = basis(view)
    p = np.asarray(p, float)
    return float(p @ x), float(p @ y)


def _edges_of(compound):
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    if compound is None or compound.IsNull():
        return []
    out, ex = [], TopExp_Explorer(compound, TopAbs_EDGE)
    while ex.More():
        out.append(TopoDS.Edge(ex.Current()))
        ex.Next()
    return out


def _curve(e, defl: float) -> dict | None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    c = BRepAdaptor_Curve(e)
    t0, t1 = c.FirstParameter(), c.LastParameter()
    typ = c.GetType()
    if typ == GeomAbs_Line:
        a, b = c.Value(t0), c.Value(t1)
        if math.hypot(a.X() - b.X(), a.Y() - b.Y()) < 1e-6:
            return None
        return {"kind": "line", "a": [a.X(), a.Y()], "b": [b.X(), b.Y()]}
    if typ == GeomAbs_Circle:
        circ = c.Circle()
        ctr, rad = circ.Location(), circ.Radius()
        ax = circ.Axis().Direction()
        if abs(abs(ax.Z()) - 1) < 1e-6:                # a circle seen face on (in the projection plane)
            if abs(t1 - t0 - 2 * math.pi) < 1e-6:
                return {"kind": "circle", "c": [ctr.X(), ctr.Y()], "r": rad}
            a, b = c.Value(t0), c.Value(t1)
            a0 = math.degrees(math.atan2(a.Y() - ctr.Y(), a.X() - ctr.X()))
            a1 = math.degrees(math.atan2(b.Y() - ctr.Y(), b.X() - ctr.X()))
            if ax.Z() < 0:
                a0, a1 = a1, a0
            return {"kind": "arc", "c": [ctr.X(), ctr.Y()], "r": rad, "a0": a0, "a1": a1}
    d = GCPnts_QuasiUniformDeflection(c, defl, t0, t1)
    if not d.IsDone() or d.NbPoints() < 2:
        return None
    pts = [[d.Value(i).X(), d.Value(i).Y()] for i in range(1, d.NbPoints() + 1)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if max(xs) - min(xs) < 1e-6 and max(ys) - min(ys) < 1e-6:
        return None
    if max(xs) - min(xs) < 1e-6 or max(ys) - min(ys) < 1e-6 or _collinear(pts):
        return {"kind": "line", "a": pts[0], "b": pts[-1]} if _monotone(pts) else {"kind": "poly", "pts": pts}
    return {"kind": "poly", "pts": pts}


def _collinear(pts, tol=1e-5) -> bool:
    a, b = np.asarray(pts[0]), np.asarray(pts[-1])
    v = b - a
    n = np.linalg.norm(v)
    if n < 1e-9:
        return False
    P = np.asarray(pts) - a
    return float(np.max(np.abs(P[:, 0] * v[1] - P[:, 1] * v[0]) / n)) < tol


def _monotone(pts) -> bool:
    a, b = np.asarray(pts[0]), np.asarray(pts[-1])
    v = b - a
    t = (np.asarray(pts) - a) @ v
    return bool(np.all(np.diff(t) >= -1e-9))


def _samples(e: dict, n: int = 9) -> np.ndarray:
    if e["kind"] == "line":
        a, b = np.asarray(e["a"]), np.asarray(e["b"])
        return a + (b - a) * np.linspace(0, 1, n)[:, None]
    if e["kind"] in ("circle", "arc"):
        a0, a1 = (0.0, 360.0) if e["kind"] == "circle" else (e["a0"], e["a1"] if e["a1"] > e["a0"] else e["a1"] + 360)
        t = np.radians(np.linspace(a0, a1, n))
        return np.c_[e["c"][0] + e["r"] * np.cos(t), e["c"][1] + e["r"] * np.sin(t)]
    return np.asarray(e["pts"])


def _seg_dist(P: np.ndarray, segs: np.ndarray) -> np.ndarray:
    """Distance of each point in P to the nearest segment in segs (N x 4)."""
    if not len(segs):
        return np.full(len(P), np.inf)
    A, B = segs[:, :2], segs[:, 2:]
    AB = B - A
    L2 = np.maximum((AB ** 2).sum(1), 1e-12)
    t = np.clip(((P[:, None, :] - A[None]) * AB[None]).sum(2) / L2[None], 0, 1)
    Q = A[None] + t[..., None] * AB[None]
    return np.sqrt(((P[:, None, :] - Q) ** 2).sum(2)).min(1)


def _segments(edges) -> np.ndarray:
    out = []
    for e in edges:
        s = _samples(e, 33 if e["kind"] != "line" else 2)
        out += [[*s[i], *s[i + 1]] for i in range(len(s) - 1)]
    return np.asarray(out, float).reshape(-1, 4)


def project(shape, view, hidden: bool = True, defl: float | None = None) -> dict:
    """The solid seen along `view` (a name in VIEWS or a (direction, right) pair), by exact hidden-line removal."""
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    d, x, _ = basis(view)
    w = getattr(shape, "wrapped", shape)
    algo = HLRBRep_Algo()
    algo.Add(w)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*d), gp_Dir(*x))))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)
    if defl is None:
        bb = _bbox(w)
        defl = max(1e-3, 1e-3 * max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]))
    groups = {"visible": [h.VCompound(), h.OutLineVCompound()], "thin": [h.Rg1LineVCompound()]}
    if hidden:
        groups["hidden"] = [h.HCompound(), h.OutLineHCompound()]
    edges = []
    for layer, comps in groups.items():
        for comp in comps:
            for e in _edges_of(comp):
                c = _curve(e, defl)
                if c is not None:
                    c["layer"] = layer
                    edges.append(c)
    vis = [e for e in edges if e["layer"] != "hidden"]
    vseg = _segments(vis)
    tol = max(1e-3, defl * 2)
    keep = []
    for e in edges:                       # a hidden edge under a visible one is not drawn (ISO 128-2)
        if e["layer"] == "hidden" and np.all(_seg_dist(_samples(e), vseg) < tol):
            continue
        keep.append(e)
    keep = _dedupe(keep, tol)
    return {"view": view if isinstance(view, str) else "custom", "edges": [_round(e) for e in keep],
            "box": _box2d(keep)}


def _dedupe(edges, tol):
    out, seen = [], set()
    for e in edges:
        s = _samples(e, 3)
        k = (e["layer"], e["kind"], tuple(np.round(np.sort(s, axis=0).ravel() / tol).astype(int)))
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def _round(e: dict) -> dict:
    f = lambda v: round(float(v), 4)  # noqa: E731
    o = {"kind": e["kind"], "layer": e["layer"]}
    if e["kind"] == "line":
        o.update(a=[f(e["a"][0]), f(e["a"][1])], b=[f(e["b"][0]), f(e["b"][1])])
    elif e["kind"] in ("circle", "arc"):
        o.update(c=[f(e["c"][0]), f(e["c"][1])], r=f(e["r"]))
        if e["kind"] == "arc":
            o.update(a0=f(e["a0"]), a1=f(e["a1"]))
    else:
        o["pts"] = [[f(p[0]), f(p[1])] for p in e["pts"]]
    return o


def _box2d(edges) -> list:
    if not edges:
        return [0, 0, 0, 0]
    P = np.vstack([_samples(e, 17) for e in edges])
    return [float(P[:, 0].min()), float(P[:, 1].min()), float(P[:, 0].max()), float(P[:, 1].max())]


def _bbox(w) -> list:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.Add_s(w, b, True)
    lo, hi = b.CornerMin(), b.CornerMax()
    return [lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()]


# ── sections ───────────────────────────────────────────────────────────────

def section(shape, origin, normal, right, hatch_layer: str = "hatch") -> dict:
    """A full section: the part on the viewer's side of the plane (through origin, normal toward the viewer) is
    taken away, the rest is projected along the normal (hidden edges left out, ISO 128-50), and the faces lying in
    the cutting plane come back as loops for hatching."""
    from build123d import Plane, Solid, Vector
    w = getattr(shape, "wrapped", shape)
    from build123d import Shape
    solid = Shape.cast(w) if not hasattr(shape, "split") else shape
    o, n = Vector(*origin), Vector(*normal).normalized()
    bb = _bbox(w)
    big = 4 * max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2], 1.0)
    pl = Plane(origin=o, z_dir=n, x_dir=Vector(*right))
    from build123d import Box, Pos
    keep_side = pl * Pos(0, 0, -big / 2) * Box(big, big, big)       # the half behind the plane
    cut = solid & keep_side
    if isinstance(cut, list):
        cut = cut[0]
    view = (tuple(n), tuple(right))
    v = project(cut, view, hidden=False)
    loops = []
    for f in cut.faces():
        try:
            fn = f.normal_at()
            c = f.center()
        except Exception:     # noqa: BLE001  (a face with no normal is not in the plane)
            continue
        if f.geom_type.name != "PLANE" or abs(fn.dot(n) - 1) > 1e-6 or abs((c - o).dot(n)) > 1e-6:
            continue
        for wire in [f.outer_wire(), *f.inner_wires()]:
            pts = [to2d(tuple(p), view) for p in _wire_points(wire)]
            loops.append([[round(a, 4), round(b, 4)] for a, b in pts])
    v["cut_loops"] = loops
    v["plane"] = {"origin": list(origin), "normal": list(normal), "right": list(right)}
    Solid  # noqa: B018 (kept importable for type checkers)
    return v


def _wire_points(wire, n_per_edge: int = 24) -> list:
    """The wire's points in connection order (BRepTools_WireExplorer keeps each edge's orientation)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_REVERSED
    pts = []
    ex = BRepTools_WireExplorer(getattr(wire, "wrapped", wire))
    while ex.More():
        e = ex.Current()
        c = BRepAdaptor_Curve(e)
        t0, t1 = c.FirstParameter(), c.LastParameter()
        k = 2 if c.GetType() == GeomAbs_Line else n_per_edge
        ts = [t0 + (t1 - t0) * i / (k - 1) for i in range(k)]
        if e.Orientation() == TopAbs_REVERSED:
            ts.reverse()
        for t in ts[:-1]:
            p = c.Value(t)
            pts.append((p.X(), p.Y(), p.Z()))
        ex.Next()
    return pts


# ── what can be dimensioned ────────────────────────────────────────────────

AXES = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}


def measure(shape, face_features=None) -> dict:
    """Sizes the B-rep holds: the bounding box, axis-normal plane levels and cylinders (full ones are holes or
    bosses, partial ones are fillets and rounds), each with the faces and features it comes from."""
    from build123d import GeomType
    faces = list(shape.faces())
    feats = list(face_features or [None] * len(faces))
    bb = shape.bounding_box()
    planes, cyls, cones = [], [], []
    for i, f in enumerate(faces):
        gt = f.geom_type
        if gt == GeomType.PLANE:
            n = f.normal_at()
            for ax, u in AXES.items():
                if abs(abs(float(np.dot((n.X, n.Y, n.Z), u))) - 1) < 1e-6:
                    c = f.center()
                    b = f.bounding_box()
                    planes.append({"face": i, "axis": ax, "at": round(float(np.dot((c.X, c.Y, c.Z), u)), 5),
                                   "sense": 1 if float(np.dot((n.X, n.Y, n.Z), u)) > 0 else -1, "area": round(f.area, 4),
                                   "feature": feats[i], "box": [round(b.min.X, 4), round(b.min.Y, 4), round(b.min.Z, 4),
                                                                round(b.max.X, 4), round(b.max.Y, 4), round(b.max.Z, 4)]})
        elif gt == GeomType.CYLINDER:
            try:
                ad = _cyl(f)
            except Exception:     # noqa: BLE001
                continue
            ad.update(face=i, feature=feats[i])
            cyls.append(ad)
        elif gt == GeomType.CONE:                 # chamfers and countersinks: where a detail view may be needed
            b = f.bounding_box()
            cones.append({"face": i, "feature": feats[i], "area": round(f.area, 4),
                          "box": [round(b.min.X, 4), round(b.min.Y, 4), round(b.min.Z, 4), round(b.max.X, 4),
                                  round(b.max.Y, 4), round(b.max.Z, 4)]})
    return {"bbox": [round(v, 5) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)],
            "planes": planes, "cylinders": cyls, "cones": cones, "faces": len(faces),
            "volume": round(float(shape.volume), 4)}


def _cyl(f) -> dict:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    s = BRepAdaptor_Surface(f.wrapped)
    cy = s.Cylinder()
    ax = cy.Axis()
    d, loc = ax.Direction(), ax.Location()
    u0, u1 = s.FirstUParameter(), s.LastUParameter()
    v0, v1 = s.FirstVParameter(), s.LastVParameter()
    span = math.degrees(u1 - u0)
    dv = np.array([d.X(), d.Y(), d.Z()])
    c = np.array([loc.X(), loc.Y(), loc.Z()])
    # a hole's face normal points to the axis; a boss's points away from it
    p = f.center()
    nrm = f.normal_at(p)
    radial = np.array([p.X, p.Y, p.Z]) - c
    radial -= dv * float(radial @ dv)
    inner = float(np.dot(radial, (nrm.X, nrm.Y, nrm.Z))) < 0
    axis = next((k for k, u in AXES.items() if abs(abs(float(dv @ u)) - 1) < 1e-6), None)
    if axis is not None:
        dv = AXES[axis]
    lo = c + dv * min(v0, v1)
    hi = c + dv * max(v0, v1)
    b = f.bounding_box()
    along = (float(np.dot((b.min.X, b.min.Y, b.min.Z), dv)), float(np.dot((b.max.X, b.max.Y, b.max.Z), dv)))
    c0 = c - dv * float(c @ dv)                        # the axis's point nearest the origin plane
    return {"r": round(cy.Radius(), 5), "axis": axis, "dir": [round(float(x), 6) for x in dv],
            "at": [round(float(x), 5) for x in c0], "span_deg": round(span, 3), "full": span > 359.0,
            "inner": inner, "along": [round(min(along), 5), round(max(along), 5)],
            "ends": [[round(float(x), 4) for x in lo], [round(float(x), 4) for x in hi]], "area": round(f.area, 4)}
