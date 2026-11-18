"""Selections on a part: points, edges, faces and free-form regions, analysed on the solid and kept as annotations.

A selection is a list of items, each picked on the part as printed (design millimetres, the frame the recipe builds in):

    {"kind": "point",  "at": [x, y, z]}                     a point on the surface
    {"kind": "edge",   "at": [x, y, z]}                     the B-rep edge nearest to that point
    {"kind": "face",   "at": [x, y, z]}                     the B-rep face under that point
    {"kind": "region", "points": [[x, y, z], ...], "radius": r}   the surface within r mm of a painted stroke or a lasso

What comes back is computed on the kernel's solid (evidence class ``computed``): face type, area, normal and tilt to the
bed in the print orientation, local wall thickness along the inward normal, the gap in front of the surface, principal
curvature radii, height above the bed, edge length, radius and the angle between the faces that meet there; for a
region its area, how much of it faces down steeply enough to need support, the features it touches and the thinnest
wall sampled inside it. The region's triangles come back too, so the viewer can draw exactly what was analysed.

An annotation is a selection with a name, a note and the revision it was made on, kept in the project file
(``project.json`` → ``annotations``). Its points are where they were on that revision: when the head moves on, the
annotation stays listed with its revision and can be analysed again on the new geometry.

The kernel side (``op_select``) runs in the worker only; everything else is plain Python and importable anywhere.
"""
from __future__ import annotations

import base64
import math
import re
import time
import uuid

import numpy as np

KINDS = ("point", "edge", "face", "region")
MAX_ITEMS = 24
MAX_REGION_POINTS = 1500
OVERHANG_DEG = 45.0            # a surface facing down more steeply than this from vertical needs support
LIMIT_TRIS = 60000             # region triangles sent back for drawing


# ── validation (any process) ────────────────────────────────────────────────

def _pt(v, what: str) -> list:
    try:
        p = [float(x) for x in v]
    except (TypeError, ValueError):
        raise ValueError(f"{what} is three numbers: x, y, z in millimetres.")
    if len(p) != 3 or not all(math.isfinite(x) for x in p):
        raise ValueError(f"{what} is three numbers: x, y, z in millimetres.")
    return p


def clean_items(items) -> list:
    """Check and normalise a selection. Raises ValueError with a sentence that says what is wrong."""
    if not isinstance(items, list) or not items:
        raise ValueError("A selection needs at least one item: a point, an edge, a face or a region.")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"A selection holds at most {MAX_ITEMS} items.")
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"Item {i + 1} is not an object.")
        kind = it.get("kind", "point")
        if kind not in KINDS:
            raise ValueError(f"Item {i + 1}: kind is one of {', '.join(KINDS)}.")
        c = {"kind": kind, "part": str(it.get("part") or "")[:40]}
        if kind == "region":
            pts = it.get("points") or []
            if not isinstance(pts, list) or not pts:
                raise ValueError(f"Item {i + 1}: a region needs the points of its stroke or lasso.")
            c["points"] = [_pt(q, f"Item {i + 1}, point {k + 1}") for k, q in enumerate(pts[:MAX_REGION_POINTS])]
            try:
                r = float(it.get("radius", 2.0))
            except (TypeError, ValueError):
                raise ValueError(f"Item {i + 1}: radius is a number of millimetres.")
            c["radius"] = min(50.0, max(0.2, r))
            c["mode"] = "lasso" if it.get("mode") == "lasso" else "brush"
        else:
            c["at"] = _pt(it.get("at"), f"Item {i + 1}")
        out.append(c)
    return out


# ── kernel side ─────────────────────────────────────────────────────────────

def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _r(x, d=3):
    return None if x is None else round(float(x), d)


class _Ctx:
    """Everything one analysis needs from the built model, computed once."""

    def __init__(self, model, orientation: str):
        from . import analysis, kernel
        self.model = model
        self.mesh = bool(getattr(model["recipe"], "mesh", False))
        self.R = analysis.orientation_matrix(orientation)
        P, T = kernel._mesh_arrays(model)
        self.P, self.T = P, T
        self.zmin = float((P @ self.R.T)[:, 2].min()) if len(P) else 0.0
        self.face_of_tri = np.concatenate([np.full(len(f["T"]), i) for i, f in enumerate(model["faces"])]) if model["faces"] else np.zeros(0, int)
        n, area, cen = analysis.tri_normals(P, T)
        self.n, self.area, self.cen = n, area, cen
        self._inters = None
        self._solid_of = None
        self._edge_faces = None

    # which solid (part as printed) a face belongs to, numbered like assembly.get numbers them
    def solid_index(self, fi: int):
        if self._solid_of is None:
            from . import assembly
            self._solid_of = {}
            try:
                solids = assembly._ordered_solids(self.model["shape"])
            except Exception:
                solids = []
            for k, s in enumerate(solids):
                for f in s.faces():
                    self._solid_of[hash(f)] = k
            self._nsolids = len(solids)
        if self.mesh or self._nsolids <= 1:
            return None
        return self._solid_of.get(hash(self.model["faces"][fi]["face"]))

    def inter(self, face):
        if self._inters is None:
            from . import analysis
            self._inters = analysis.wall_intersectors(self.model)
        return self._inters(face)

    def height(self, p) -> float:
        return float((self.R @ np.asarray(p, dtype=np.float64))[2] - self.zmin)

    def tilt(self, n):
        up = float(np.clip((self.R @ np.asarray(n, dtype=np.float64))[2], -1, 1))
        deg = math.degrees(math.acos(up))
        if deg < 0.5:
            words = "faces up, parallel to the bed"
        elif deg > 179.5:
            words = "faces down, parallel to the bed"
        elif abs(deg - 90) < 0.5:
            words = "vertical wall"
        else:
            words = f"leans {'up' if deg < 90 else 'down'}, {abs(90 - deg):.1f}° from vertical"
        over = deg > 90 + OVERHANG_DEG
        return round(deg, 2), words, over

    def nearest(self, p):
        """(distance, face index, point on the surface, triangle index within that face) for the surface nearest p."""
        from . import analysis
        best = None
        for i, x in enumerate(self.model["faces"]):
            lo, hi = x["P"].min(axis=0), x["P"].max(axis=0)
            if best is not None and (np.any(p < lo - best[0]) or np.any(p > hi + best[0])):
                continue
            A, B, C = x["P"][x["T"][:, 0]], x["P"][x["T"][:, 1]], x["P"][x["T"][:, 2]]
            pts, d = analysis.closest_on_triangles(p, A, B, C)
            k = int(np.argmin(d))
            if best is None or d[k] < best[0]:
                best = (float(d[k]), i, pts[k], k)
        if best is None:
            raise ValueError("The design has no surface.")
        return best

    def normal(self, fi, tk, on):
        x = self.model["faces"][fi]
        if not self.mesh:
            try:
                from build123d import Vector
                v = x["face"].normal_at(Vector(*on))
                return np.array([v.X, v.Y, v.Z])
            except Exception:
                pass
        from . import analysis
        return analysis.tri_normals(x["P"], x["T"])[0][tk]

    def thickness(self, fi, on, n):
        """Wall thickness along the inward normal, and the gap in front of the surface (to the next face of the same part)."""
        if self.mesh:
            return None, None, None
        from . import analysis
        face = self.model["faces"][fi]["face"]
        inter = self.inter(face)
        w = analysis.wall_hit(inter, on, n)
        g = analysis.wall_hit(inter, on, n, outward=True)
        return (w[0] if w else None), (list(w[1]) if w else None), (g[0] if g else None)

    def curvature(self, fi, on):
        """Principal curvature radii at a point (mm); None for a direction that is flat."""
        if self.mesh:
            return None
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.BRepLProp import BRepLProp_SLProps
            from OCP.BRep import BRep_Tool
            from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
            from OCP.gp import gp_Pnt
            face = self.model["faces"][fi]["face"].wrapped
            proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*on), BRep_Tool.Surface_s(face))
            if proj.NbPoints() == 0:
                return None
            u, v = proj.LowerDistanceParameters()
            props = BRepLProp_SLProps(BRepAdaptor_Surface(face), u, v, 2, 1e-6)
            if not props.IsCurvatureDefined():
                return None
            k = sorted([abs(props.MinCurvature()), abs(props.MaxCurvature())])
            rad = [None if c < 1e-6 else round(1.0 / c, 3) for c in k]
            return {"min_radius_mm": rad[1], "max_radius_mm": rad[0],
                    "kind": "flat" if all(r is None for r in rad) else "curved in one direction" if rad[0] is None else "curved in two directions"}
        except Exception:
            return None

    def edge_faces(self, edge) -> list:
        """The faces of the solid that share this edge."""
        if self._edge_faces is None:
            self._edge_faces = {}
            for f in self.model["shape"].faces():
                for e in f.edges():
                    self._edge_faces.setdefault(hash(e), []).append(f)
        return self._edge_faces.get(hash(edge), [])


def _common(ctx, p):
    dist, fi, on, tk = ctx.nearest(np.asarray(p, dtype=np.float64))
    x = ctx.model["faces"][fi]
    n = ctx.normal(fi, tk, on)
    deg, words, over = ctx.tilt(n)
    out = {"on": [_r(t, 4) for t in on], "off_surface_mm": _r(dist, 4), "feature": x["feature"], "normal": [_r(t, 5) for t in n],
           "tilt_deg": deg, "tilt": words, "overhang": over, "height_above_bed_mm": _r(ctx.height(on), 3)}
    s = ctx.solid_index(fi)
    if s is not None:
        out["solid"] = s
    return out, fi, on, n


def _face_info(ctx, fi):
    x = ctx.model["faces"][fi]
    if ctx.mesh:
        return {"type": "mesh triangles", "area_mm2": _r(x["area"], 3), "method": "computed from the mesh"}
    f = x["face"]
    kind = f.geom_type.name
    bb = f.bounding_box()
    c = f.center()
    zs = (x["P"] @ ctx.R.T)[:, 2] - ctx.zmin
    info = {"type": kind.lower(), "area_mm2": _r(f.area, 3), "centre": [_r(c.X, 4), _r(c.Y, 4), _r(c.Z, 4)],
            "bbox": [[_r(bb.min.X), _r(bb.min.Y), _r(bb.min.Z)], [_r(bb.max.X), _r(bb.max.Y), _r(bb.max.Z)]],
            "height_range_mm": [_r(zs.min()), _r(zs.max())], "edges": len(f.edges()), "method": "exact (CAD solid)"}
    if kind in ("CYLINDER", "SPHERE", "CONE", "TORUS"):
        try:
            r = float(f.radius)
            info.update({"radius_mm": _r(r, 4), "diameter_mm": _r(2 * r, 4)})
        except Exception:
            pass
    return info


def _point(ctx, it):
    out, fi, on, n = _common(ctx, it["at"])
    w, opp, gap = ctx.thickness(fi, on, n)
    out.update({"wall_thickness_mm": _r(w, 3), "wall_opposite": [_r(t, 4) for t in opp] if opp else None,
                "gap_in_front_mm": _r(gap, 3), "curvature": ctx.curvature(fi, on), "face": _face_info(ctx, fi)})
    return out


def _face(ctx, it):
    out, fi, on, n = _common(ctx, it["at"])
    info = _face_info(ctx, fi)
    out["face"] = info
    w, opp, gap = ctx.thickness(fi, on, n)
    out.update({"wall_thickness_mm": _r(w, 3), "gap_in_front_mm": _r(gap, 3), "curvature": ctx.curvature(fi, on)})
    # the face's triangles, for drawing the selection exactly
    x = ctx.model["faces"][fi]
    out["mesh"] = {"positions": _b64(x["P"].astype(np.float32)), "indices": _b64(x["T"].astype(np.uint32))}
    return out


def _edge(ctx, it):
    out, fi, on, n = _common(ctx, it["at"])
    if ctx.mesh:
        out["edge"] = None
        out["note"] = "A mesh design has no CAD edges; select a face or a region instead."
        return out
    from build123d import Vector
    face = ctx.model["faces"][fi]["face"]
    best = None
    for e in face.edges():
        try:
            d = float(e.distance_to(Vector(*on)))
        except Exception:
            continue
        if best is None or d < best[0]:
            best = (d, e)
    if best is None:
        out["edge"] = None
        return out
    d, e = best
    a, b, m = e.position_at(0), e.position_at(1), e.position_at(0.5)
    kind = e.geom_type.name
    info = {"type": kind.lower(), "length_mm": _r(e.length, 4), "distance_mm": _r(d, 4),
            "start": [_r(a.X, 4), _r(a.Y, 4), _r(a.Z, 4)], "end": [_r(b.X, 4), _r(b.Y, 4), _r(b.Z, 4)],
            "midpoint": [_r(m.X, 4), _r(m.Y, 4), _r(m.Z, 4)],
            "height_range_mm": [_r(min(ctx.height((a.X, a.Y, a.Z)), ctx.height((b.X, b.Y, b.Z)))),
                                _r(max(ctx.height((a.X, a.Y, a.Z)), ctx.height((b.X, b.Y, b.Z))))]}
    if kind == "CIRCLE":
        try:
            r = float(e.radius)
            c = e.arc_center
            info.update({"radius_mm": _r(r, 4), "diameter_mm": _r(2 * r, 4), "centre": [_r(c.X, 4), _r(c.Y, 4), _r(c.Z, 4)],
                         "full_circle": bool(abs(e.length - 2 * math.pi * r) < 1e-6 * max(1.0, r))})
        except Exception:
            pass
    # the angle between the two faces that meet at this edge, at its midpoint
    try:
        fs = ctx.edge_faces(e)
        if len(fs) == 2:
            n1, n2 = (np.array([v.X, v.Y, v.Z]) for v in (f.normal_at(m) for f in fs))
            ang = math.degrees(math.acos(float(np.clip(n1 @ n2, -1, 1))))
            info["faces_angle_deg"] = _r(180.0 - ang, 2)      # 90 = a square corner, 180 = tangent (smooth)
            info["smooth"] = bool(ang < 1.0)
    except Exception:
        pass
    # draw it: a polyline
    k = 2 if kind == "LINE" else max(8, min(96, int(e.length / 0.8)))
    pts = [e.position_at(i / (k - 1)) for i in range(k)]
    segs = []
    for p, q in zip(pts, pts[1:]):
        segs += [p.X, p.Y, p.Z, q.X, q.Y, q.Z]
    info["segments"] = _b64(np.array(segs, dtype=np.float32))
    out["edge"] = info
    return out


def _region(ctx, it):
    """The surface within `radius` of the stroke's points. Large triangles are split first, so the area is the area
    painted, not the area of every triangle the stroke touched."""
    from . import analysis
    pts = np.asarray(it["points"], dtype=np.float64)
    r = float(it["radius"])
    P, T = ctx.P, ctx.T
    A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    lo, hi = np.minimum(np.minimum(A, B), C), np.maximum(np.maximum(A, B), C)
    cand = np.zeros(len(T), dtype=bool)
    plo, phi = pts.min(axis=0) - r, pts.max(axis=0) + r
    near = np.flatnonzero(np.all(hi >= plo, axis=1) & np.all(lo <= phi, axis=1))
    pn = np.zeros((len(pts), 3))                          # the surface normal under each point of the stroke
    for i, q in enumerate(pts):
        m = near[np.all(lo[near] <= q + r, axis=1) & np.all(hi[near] >= q - r, axis=1)]
        if len(m):
            _, d = analysis.closest_on_triangles(q, A[m], B[m], C[m])
            cand[m[d <= r]] = True
            pn[i] = ctx.n[m[int(np.argmin(d))]]
    ci = np.flatnonzero(cand)
    if not len(ci):
        return {"area_mm2": 0.0, "triangles": 0, "note": "The stroke did not touch the surface."}
    used, inv = np.unique(T[ci].reshape(-1), return_inverse=True)
    h = max(0.25, r / 3.0)
    Pr, Tr, parent = analysis.refine(P[used], inv.reshape(-1, 3), h, max_passes=18)
    cen = (Pr[Tr[:, 0]] + Pr[Tr[:, 1]] + Pr[Tr[:, 2]]) / 3
    # a piece is in when a stroke point is within r and the piece faces the same way as the surface under that point:
    # the brush paints the side it is on, never the far side of a thin wall
    pnr = ctx.n[ci[parent]]
    keep = np.zeros(len(Tr), dtype=bool)
    for k in range(0, len(pts), 64):                     # chunks keep the distance matrix small
        d = np.linalg.norm(cen[:, None, :] - pts[None, k:k + 64, :], axis=2)
        same = (pnr @ pn[k:k + 64].T) > 0.05
        keep |= ((d <= r) & same).any(axis=1)
    sub = np.flatnonzero(keep)
    if not len(sub):
        return {"area_mm2": 0.0, "triangles": 0, "note": "The stroke did not touch the surface."}
    src = ci[parent[sub]]                                 # the model triangle each piece came from
    _n, a, _c = analysis.tri_normals(Pr, Tr[sub])
    idx = src
    area = float(a.sum())
    n = ctx.n[src]
    up = (n @ ctx.R.T)[:, 2]
    over = up < -math.cos(math.radians(90 - OVERHANG_DEG))          # facing down past 45° from vertical
    flat_up = up > 0.999
    mean_n = (n * a[:, None]).sum(axis=0)
    mn = float(np.linalg.norm(mean_n))
    mean_n = mean_n / mn if mn > 1e-9 else np.array([0.0, 0.0, 1.0])
    deg, words, _o = ctx.tilt(mean_n)
    feats = {}
    for f, ar in zip(ctx.face_of_tri[idx], a):
        name = ctx.model["faces"][int(f)]["feature"]
        feats[name] = feats.get(name, 0.0) + float(ar)
    heights = (cen[sub] @ ctx.R.T)[:, 2] - ctx.zmin
    # thickness sampled at up to 40 places spread over the region
    thick = []
    if not ctx.mesh:
        step = max(1, len(sub) // 40)
        for j in range(0, len(sub), step)[:40]:
            t = int(src[j])
            fi = int(ctx.face_of_tri[t])
            w, _, _ = ctx.thickness(fi, cen[sub[j]], ctx.n[t])
            if w is not None:
                thick.append(w)
    V = Pr[Tr[sub]].reshape(-1, 3)
    lo, hi = V.min(axis=0), V.max(axis=0)
    out = {"area_mm2": _r(area, 3), "triangles": int(len(sub)), "faces": int(len(set(ctx.face_of_tri[idx].tolist()))),
           "features": [{"feature": k, "area_mm2": _r(v, 2)} for k, v in sorted(feats.items(), key=lambda kv: -kv[1])],
           "mean_normal": [_r(t, 5) for t in mean_n], "mean_tilt_deg": deg, "mean_tilt": words,
           "overhang_share": _r(float(a[over].sum()) / area if area else 0.0, 4), "overhang_area_mm2": _r(float(a[over].sum()), 2),
           "flat_up_share": _r(float(a[flat_up].sum()) / area if area else 0.0, 4),
           "height_range_mm": [_r(heights.min()), _r(heights.max())],
           "bbox": [[_r(t) for t in lo], [_r(t) for t in hi]],
           "centroid": [_r(t, 4) for t in (cen[sub] * a[:, None]).sum(axis=0) / max(area, 1e-12)],
           "radius_mm": _r(r, 3), "mode": it.get("mode", "brush"), "points": int(len(pts))}
    if thick:
        out["wall_thickness_mm"] = {"min": _r(min(thick)), "median": _r(float(np.median(thick))), "max": _r(max(thick)), "samples": len(thick)}
    Ts = Tr[sub[:LIMIT_TRIS]]
    used, inv = np.unique(Ts.reshape(-1), return_inverse=True)
    out["mesh"] = {"positions": _b64(Pr[used].astype(np.float32)), "indices": _b64(inv.reshape(-1, 3).astype(np.uint32))}
    return out


def op_select(key, recipe_id, values, items, orientation="as_modelled", tol=0.05):
    """Analyse a selection on the built solid (worker only)."""
    from . import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    ctx = _Ctx(model, orientation)
    out = []
    for it in items:
        fn = {"point": _point, "face": _face, "edge": _edge, "region": _region}[it["kind"]]
        res = fn(ctx, it)
        res["kind"] = it["kind"]
        if it.get("part"):
            res["part"] = it["part"]
        if it["kind"] == "region":
            res["source"] = {"points": it["points"][:400], "radius": it["radius"], "mode": it.get("mode", "brush")}
        else:
            res["at"] = it["at"]
        out.append(res)
    return {"items": out, "summary": summary(out), "evidence": "computed", "orientation": orientation,
            "tessellation_mm": model.get("tol", tol), "mesh_design": ctx.mesh,
            "frame": "design millimetres, each part as printed (build frame); heights and tilts are in the print orientation"}


def summary(items: list) -> dict:
    """Totals over a selection's items: area of faces and regions, extent, the thinnest wall, and the distance when it is two points."""
    area = sum((x.get("face") or {}).get("area_mm2") or 0 for x in items if x["kind"] == "face")
    area += sum(x.get("area_mm2") or 0 for x in items if x["kind"] == "region")
    walls = [x.get("wall_thickness_mm") for x in items if isinstance(x.get("wall_thickness_mm"), (int, float))]
    walls += [x["wall_thickness_mm"]["min"] for x in items if isinstance(x.get("wall_thickness_mm"), dict)]
    feats = []
    for x in items:
        for f in ([x["feature"]] if x.get("feature") else []) + [f["feature"] for f in x.get("features", [])]:
            if f not in feats:
                feats.append(f)
    out = {"items": len(items), "area_mm2": _r(area, 3), "features": feats, "thinnest_wall_mm": _r(min(walls), 3) if walls else None,
           "overhang": any(x.get("overhang") for x in items) or any((x.get("overhang_share") or 0) > 0.05 for x in items)}
    pts = [x["on"] for x in items if x["kind"] in ("point", "edge", "face") and x.get("on")]
    if len(pts) == 2:
        d = np.subtract(pts[1], pts[0])
        out["distance_mm"] = _r(float(np.linalg.norm(d)), 4)
        out["delta_mm"] = [_r(t, 4) for t in d]
        if items[0].get("part") != items[1].get("part"):
            out["distance_note"] = "Between two parts, measured with both as printed (print layout), not assembled."
    return out


KERNEL_OPS = {"select": op_select}


# ── engine side: analyse, describe, keep ────────────────────────────────────

def analyze(st, p: dict, items, rev: int | None = None) -> dict:
    """Analyse a selection on a revision (head by default). Nothing is saved."""
    from .studio import StudioError
    try:
        items = clean_items(items)
    except ValueError as e:
        raise StudioError(str(e), "Pick points on the part as printed: x, y, z in design millimetres.")
    r = st.rev(p, rev)
    out = st._k("select", timeout=180, key=st.keys(p, r["n"])["geometry"], recipe_id=st.rid(p, r["n"]), values=r["values"],
                items=items, orientation=p["orientation"], p=p)
    out.update({"rev": r["n"], "project": p["id"]})
    out["text"] = describe(out, labels=_feature_labels(st, p))
    return out


def _feature_labels(st, p) -> dict:
    try:
        return {f.id: f.label for f in st.recipe(p).features}
    except Exception:
        return {}


def _mm(x, d=2):
    return "–" if x is None else f"{x:.{d}f} mm"


def describe(res: dict, labels: dict | None = None, name: str = "", note: str = "") -> str:
    """The selection in words and numbers, for a person or an agent: one line per item, then totals."""
    labels = labels or {}
    feat = lambda f: f"{labels.get(f, f)} ({f})" if f else "–"
    xyz = lambda p: "(" + ", ".join(f"{t:.2f}" for t in p) + ")" if p else "–"
    lines = []
    if name:
        lines.append(f"Selection “{name}” on r{res.get('rev', 0):02d}" + (f": {note}" if note else ""))
    for i, x in enumerate(res["items"], 1):
        part = f", part {x['part']}" if x.get("part") else (f", body {x['solid'] + 1}" if x.get("solid") is not None else "")
        if x["kind"] == "region":
            w = x.get("wall_thickness_mm")
            lines.append(f"{i}. Region ({x.get('mode', 'brush')}, {x.get('points', 0)} points, radius {x.get('radius_mm', 0):g} mm{part}): "
                         f"area {x.get('area_mm2', 0):.1f} mm² over {x.get('faces', 0)} face{'' if x.get('faces') == 1 else 's'}; mean normal {x.get('mean_tilt_deg', 0):.1f}° from up "
                         f"({x.get('mean_tilt', '')}); {100 * (x.get('overhang_share') or 0):.0f}% faces down past {OVERHANG_DEG:g}°; "
                         f"height above bed {x['height_range_mm'][0]:.2f}–{x['height_range_mm'][1]:.2f} mm" if x.get("height_range_mm") else
                         f"{i}. Region: {x.get('note', 'empty')}")
            if x.get("features"):
                lines[-1] += "; features " + ", ".join(f"{feat(f['feature'])} {f['area_mm2']:.1f} mm²" for f in x["features"][:6])
            if isinstance(w, dict):
                lines[-1] += f"; wall thickness min {w['min']:.2f} / median {w['median']:.2f} mm ({w['samples']} samples)"
            continue
        f = x.get("face") or {}
        head = {"point": "Point", "face": "Face", "edge": "Edge"}[x["kind"]]
        s = f"{i}. {head} at {xyz(x.get('on'))}{part} on {feat(x.get('feature'))}: "
        if x["kind"] == "edge" and x.get("edge"):
            e = x["edge"]
            s += f"{e['type']} edge, length {_mm(e['length_mm'])}"
            if e.get("diameter_mm"):
                s += f", Ø {_mm(e['diameter_mm'], 3)}"
            if e.get("faces_angle_deg") is not None:
                s += f", faces meet at {e['faces_angle_deg']:.1f}°"
            s += f", height above bed {e['height_range_mm'][0]:.2f}–{e['height_range_mm'][1]:.2f} mm"
        else:
            s += f"{f.get('type', '?')} face, area {f.get('area_mm2', 0):.2f} mm²"
            if f.get("diameter_mm"):
                s += f", Ø {_mm(f['diameter_mm'], 3)}"
            s += f"; normal {x.get('tilt_deg', 0):.1f}° from up ({x.get('tilt', '')})"
            if x.get("overhang"):
                s += ", an overhang"
            s += f"; wall thickness {_mm(x.get('wall_thickness_mm'))}"
            if x.get("gap_in_front_mm") is not None:
                s += f"; gap in front {_mm(x['gap_in_front_mm'])}"
            c = x.get("curvature")
            if c and c.get("kind") != "flat":
                s += f"; curvature radii {_mm(c.get('max_radius_mm'))} / {_mm(c.get('min_radius_mm'))}"
            s += f"; height above bed {_mm(x.get('height_above_bed_mm'))}"
        lines.append(s)
    sm = res.get("summary") or {}
    tot = []
    if sm.get("area_mm2"):
        tot.append(f"selected area {sm['area_mm2']:.1f} mm²")
    if sm.get("thinnest_wall_mm") is not None:
        tot.append(f"thinnest wall {sm['thinnest_wall_mm']:.2f} mm")
    if sm.get("distance_mm") is not None:
        tot.append(f"distance between the two {sm['distance_mm']:.2f} mm")
    if tot:
        lines.append("Totals: " + ", ".join(tot) + ".")
    lines.append(f"Computed on the CAD solid of r{res.get('rev', 0):02d} (evidence: computed). Points are design millimetres with each part as printed; heights and tilts are for the print orientation ({res.get('orientation', 'as_modelled')}).")
    return "\n".join(lines)


def _strip(res: dict) -> dict:
    """What is kept in the project file: the numbers, not the drawing meshes (they are recomputed on demand)."""
    items = []
    for x in res["items"]:
        y = {k: v for k, v in x.items() if k != "mesh"}
        if isinstance(y.get("edge"), dict):
            y["edge"] = {k: v for k, v in y["edge"].items() if k != "segments"}
        items.append(y)
    return {"items": items, "summary": res.get("summary"), "evidence": res.get("evidence"), "tessellation_mm": res.get("tessellation_mm")}


def _clean_text(s, n) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def listing(st, pid: str) -> list:
    p = st.load(pid)
    return p.get("annotations") or []


def add(st, pid: str, items, name: str = "", note: str = "", rev: int | None = None, by: str = "you") -> dict:
    """Analyse a selection and keep it with the revision it was made on."""
    from .studio import StudioError
    p = st.load(pid)
    res = analyze(st, p, items, rev)
    with st.lock(pid):
        p = st.load(pid)
        anns = p.setdefault("annotations", [])
        if len(anns) >= 200:
            raise StudioError("This design keeps at most 200 annotations.", "Delete the ones you no longer need.")
        n = len(anns) + 1
        a = {"id": "a" + uuid.uuid4().hex[:8], "name": _clean_text(name, 80) or f"Selection {n}", "note": _clean_text(note, 2000),
             "rev": res["rev"], "ts": time.time(), "by": by, "items": [dict(it) for it in clean_items(items)], "analysis": _strip(res)}
        a["text"] = describe(res, _feature_labels(st, p), a["name"], a["note"])
        anns.append(a)
        st.save(p)
    st.activity(pid, "annotation", f"Annotation “{a['name']}” on r{a['rev']:02d}.", by=by)
    return a


def update(st, pid: str, aid: str, name=None, note=None) -> dict:
    from .studio import StudioError
    with st.lock(pid):
        p = st.load(pid)
        a = next((x for x in p.get("annotations") or [] if x["id"] == aid), None)
        if a is None:
            raise StudioError("Unknown annotation.", status=404)
        if name is not None:
            a["name"] = _clean_text(name, 80) or a["name"]
        if note is not None:
            a["note"] = _clean_text(note, 2000)
        if a.get("analysis"):
            a["text"] = describe({**a["analysis"], "rev": a["rev"]}, _feature_labels(st, p), a["name"], a["note"])
        st.save(p)
    return a


def delete(st, pid: str, aid: str) -> dict:
    from .studio import StudioError
    with st.lock(pid):
        p = st.load(pid)
        anns = p.get("annotations") or []
        keep = [x for x in anns if x["id"] != aid]
        if len(keep) == len(anns):
            raise StudioError("Unknown annotation.", status=404)
        p["annotations"] = keep
        st.save(p)
    return {"deleted": aid}


def reanalyze(st, pid: str, aid: str, rev: int | None = None) -> dict:
    """The annotation's selection, analysed again (on the head by default): what it says on the current geometry."""
    from .studio import StudioError
    p = st.load(pid)
    a = next((x for x in p.get("annotations") or [] if x["id"] == aid), None)
    if a is None:
        raise StudioError("Unknown annotation.", status=404)
    res = analyze(st, p, a["items"], rev)
    res["text"] = describe(res, _feature_labels(st, p), a["name"], a["note"])
    res["annotation"] = a["id"]
    return res
