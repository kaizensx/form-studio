"""Unfold a constant-thickness solid of flat faces and cylindrical bends into its flat pattern (kernel worker only).

How it works, on the exact B-rep:

1. **The skin.** The largest flat face is the base. From it, faces are walked across tangent edges only (the
   normals of the two faces agree along the edge): that set is one side of the sheet, its skin. Sharp edges lead
   to the sheet's cut edges (its thickness faces) and are not crossed.
2. **The thickness.** t is the nearest face parallel to the base and facing away from it. Every flat face of the
   skin must have a face at t behind it, and every bend a coaxial cylinder at its radius ± t; the solid's volume
   must equal the skin's area times t (bends at their mid radius) to 1e-4. Otherwise the part is not one
   constant-thickness sheet, and the report says which faces and why.
3. **Bends.** A cylinder of the skin is a bend: its axis, its angle θ (the angular extent of the face), its
   direction (up when the skin is its inside, so the flange turns toward the skin's outward normal) and its
   inside radius r (the skin's radius, or the partner's when the skin is outside). The K-factor of each bend comes
   from the bend table with its source (form/sheet/tables.py); the zone is laid flat θ·(r + K·t) wide.
4. **Laying flat.** Breadth-first from the base, each flat face gets a rigid motion into the base's plane: the
   motion of the face before the bend, after turning back by θ about the bend's axis and moving on by the zone's
   width. A point of a bend's cylinder lands at its angle × (r + K·t) from the bend's start line.
5. **Edges.** Every edge of the skin that is not crossed (a cut edge) is mapped: a line stays a line, a circle on
   a flat face stays an arc or circle, a circle round a bend's axis becomes a line, anything else a polyline. The
   cut edges are chained into closed loops: the outline and the holes. The bend's start and end lines are mapped
   too, and its centre line goes on the bend layer with its angle, radius, direction and K-factor.
6. **Verification.** Every vertex of the skin's tessellation, and the matching point t behind it, is laid flat
   and then folded back by form/sheet/fold.py from the flat pattern's own numbers (bend lines, angles, radii,
   K-factors); the largest distance between where each point started and where it lands is reported against the
   stated tolerance (0.01 mm).

What cannot be unfolded, and is reported with the face and the reason: a face that is neither flat nor a
cylinder on the skin (a louvre, an emboss, a cone, a spline), a cylinder tangent to the sheet with no partner at
the thickness (an edge round, not a bend), faces not reached from the base, and a solid whose volume does not
match one sheet of thickness t.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import fold as foldmod
from . import geom2d

TOL_FOLD = 0.01          # mm: the fold-back must land every sample within this of where it started
ANG = 1e-6


def _v(p) -> np.ndarray:
    if hasattr(p, "X"):
        x = p.X
        if callable(x):                        # an OCP gp_Pnt / gp_Dir
            return np.array([p.X(), p.Y(), p.Z()], dtype=float)
        return np.array([x, p.Y, p.Z], dtype=float)
    return np.asarray(p, float)


def _rot(a: np.ndarray, ang: float) -> np.ndarray:
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)


def _h(R=None, t=None) -> np.ndarray:
    M = np.eye(4)
    if R is not None:
        M[:3, :3] = R
    if t is not None:
        M[:3, 3] = t
    return M


def _rot_about(c: np.ndarray, a: np.ndarray, ang: float) -> np.ndarray:
    R = _rot(a, ang)
    return _h(None, c) @ _h(R) @ _h(None, -c)


def _apply(M: np.ndarray, P: np.ndarray) -> np.ndarray:
    P = np.atleast_2d(P)
    return P @ M[:3, :3].T + M[:3, 3]


class _Topo:
    def __init__(self, shape):
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopExp import TopExp, TopExp_Explorer
        from OCP.TopoDS import TopoDS
        try:
            from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as EdgeFaceMap
        except ImportError:                               # newer OCP names the template instance
            from OCP.collections import \
                IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap
        from build123d import Edge, Face
        to_edge = getattr(TopoDS, "Edge", None) or TopoDS.Edge_s
        to_face = getattr(TopoDS, "Face", None) or TopoDS.Face_s
        self.shape = shape
        self.faces = list(shape.faces())
        index = {f: i for i, f in enumerate(self.faces)}
        em = EdgeFaceMap()
        TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, em)
        self.edges = []
        self.edge_faces = []
        for j in range(em.Extent()):
            self.edges.append(Edge(to_edge(em.FindKey(j + 1))))
            fs = []
            for f in em.FindFromIndex(j + 1):
                k = index.get(Face(to_face(f)), -1)
                if k >= 0 and k not in fs:
                    fs.append(k)
            self.edge_faces.append(fs)
        self.face_edges = []
        for f in self.faces:
            ex = TopExp_Explorer(f.wrapped, TopAbs_EDGE)
            es = []
            while ex.More():
                j = em.FindIndex(ex.Current()) - 1
                if j >= 0 and j not in es:
                    es.append(j)
                ex.Next()
            self.face_edges.append(es)
        self.info = [self._face_info(f) for f in self.faces]

    @staticmethod
    def _face_info(f) -> dict:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepTools import BRepTools
        from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
        s = BRepAdaptor_Surface(f.wrapped)
        kind = s.GetType()
        area = float(f.area)
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
        samples = np.array([_v(s.Value(u, v)) for u in np.linspace(umin, umax, 7) for v in np.linspace(vmin, vmax, 3)])
        if kind == GeomAbs_Plane:
            c = _v(f.center())
            n = _v(f.normal_at(f.center()))
            return {"kind": "plane", "n": n / np.linalg.norm(n), "p": c, "area": area, "samples": samples}
        if kind == GeomAbs_Cylinder:
            cy = s.Cylinder()
            ax = cy.Axis()
            loc, z = _v(ax.Location()), _v(ax.Direction())
            R = float(cy.Radius())
            pm = _v(s.Value((umin + umax) / 2, (vmin + vmax) / 2))
            nm = _v(f.normal_at(f.center()))       # outward of the solid
            foot = loc + ((pm - loc) @ z) * z
            concave = float((foot - pm) @ nm) > 0     # the outward normal points at the axis
            return {"kind": "cylinder", "loc": loc, "z": z, "R": R, "concave": concave, "area": area,
                    "samples": samples, "u": (umin, umax)}
        names = {0: "plane", 1: "cylinder", 2: "cone", 3: "sphere", 4: "torus", 5: "Bezier surface",
                 6: "B-spline surface", 7: "surface of revolution", 8: "extruded surface", 9: "offset surface"}
        return {"kind": names.get(int(kind), "other surface"), "area": area, "samples": samples,
                "p": _v(f.center())}

    def tangent(self, j: int, a: int, b: int) -> bool:
        e = self.edges[j]
        p = e.position_at(0.5)
        na = _v(self.faces[a].normal_at(p))
        nb = _v(self.faces[b].normal_at(p))
        return float(na @ nb) > 1 - 1e-6


def _edge_points(e, n: int = 33) -> np.ndarray:
    return np.array([_v(e.position_at(t)) for t in np.linspace(0.0, 1.0, n)])


def _edge_kind(e) -> str:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    k = BRepAdaptor_Curve(e.wrapped).GetType()
    return "line" if k == GeomAbs_Line else ("circle" if k == GeomAbs_Circle else "curve")


class _Bend:
    """One skin cylinder, entered from a frame M (world -> flat) at its entry edge."""

    def __init__(self, fi: int, info: dict, M: np.ndarray, entry_pts: np.ndarray, t: float, r_in: float, K: dict):
        self.fi = fi
        self.loc, z, self.R_s = info["loc"], info["z"], info["R"]
        self.M = M
        q = entry_pts[len(entry_pts) // 2]
        self.e0 = (q - self.loc) - ((q - self.loc) @ z) * z
        self.e0 /= np.linalg.norm(self.e0)
        self.a = z
        phis = self.phi(info["samples"])
        if np.any((phis < -1e-6) & (phis > -math.pi / 2)):
            self.a = -z
            phis = self.phi(info["samples"])
        self.theta = float(np.max(phis))
        self.d = np.cross(self.a, self.e0)
        self.s = 1 if info["concave"] else -1
        self.r = r_in
        self.t = t
        self.K = K
        self.R_n = r_in + K["K"] * t
        self.w = self.theta * self.R_n
        self.before = None
        self.after: list = []
        self.M_after = M @ _h(None, self.w * self.d) @ _rot_about(self.loc, self.a, -self.theta)

    def phi(self, P: np.ndarray) -> np.ndarray:
        rel = np.atleast_2d(P) - self.loc
        rad = rel - np.outer(rel @ self.a, self.a)
        y = np.cross(self.e0, rad) @ self.a
        x = rad @ self.e0
        ph = np.arctan2(y, x)
        return np.where(ph < -math.pi / 2, ph + 2 * math.pi, ph)

    def to_flat(self, P: np.ndarray) -> np.ndarray:
        P = np.atleast_2d(P)
        ph = self.phi(P)
        rel = P - self.loc
        along = rel @ self.a
        x0 = self.loc + np.outer(along, self.a) + self.R_s * self.e0[None, :]
        return _apply(self.M, x0 + (ph * self.R_n)[:, None] * self.d[None, :])


def unfold(shape, kfactor, tol_fold: float = TOL_FOLD, max_samples: int = 6000) -> dict:
    """The flat pattern of a solid. kfactor(r, t, angle_deg) -> {"K", "method", "source", "evidence", ...}.

    Returns {"ok", "reasons" (why it cannot be unfolded), "t", "entities" (cut edges, flat frame, mm), "loops",
    "bends", "frame" (flat -> world), "verify" (the fold-back), "faces" (what each face is), "area_mm2", ...}."""
    t0 = time.perf_counter()
    T = _Topo(shape)
    info = T.info
    reasons: list = []
    planes = [i for i, f in enumerate(info) if f["kind"] == "plane"]
    if not planes:
        return {"ok": False, "reasons": [{"why": "The solid has no flat face to start from: it is not sheet metal."}]}
    base = max(planes, key=lambda i: info[i]["area"])
    n0, p0 = info[base]["n"], info[base]["p"]
    # ---- thickness: the nearest face parallel to the base, facing away from it, behind it
    cands = []
    for i in planes:
        if float(info[i]["n"] @ n0) < -1 + 1e-6:
            dist = float((p0 - info[i]["p"]) @ n0)
            if dist > 1e-6:
                cands.append(dist)
    if not cands:
        return {"ok": False, "reasons": [{"face": base, "why": "No face behind the base faces the other way: no "
                                          "thickness, so not one sheet."}]}
    t = min(cands)

    # ---- walk the skin
    frames: dict = {}               # plane face -> M (world -> flat 3D)
    bendof: dict = {}               # cylinder face -> _Bend
    path: dict = {base: []}         # face -> bend ids from the base (bend id = its cylinder's face index)
    ez = n0
    longest = None
    for j in T.face_edges[base]:
        e = T.edges[j]
        if _edge_kind(e) == "line" and (longest is None or e.length > T.edges[longest].length):
            longest = j
    if longest is not None:
        ex = _v(T.edges[longest].position_at(1)) - _v(T.edges[longest].position_at(0))
        ex -= (ex @ ez) * ez
        ex /= np.linalg.norm(ex)
    else:
        ex = np.cross(ez, [1, 0, 0]) if abs(ez[0]) < 0.9 else np.cross(ez, [0, 1, 0])
        ex /= np.linalg.norm(ex)
    ey = np.cross(ez, ex)
    B = np.eye(4)
    B[:3, :3] = np.array([ex, ey, ez])
    B[:3, 3] = -np.array([ex, ey, ez]) @ p0
    frames[base] = B
    queue = [base]
    seen = {base}
    tangent_edges: set = set()
    k_rows = {}
    while queue:
        f = queue.pop(0)
        for j in T.face_edges[f]:
            fs = T.edge_faces[j]
            if len(fs) != 2:
                continue
            g = fs[1] if fs[0] == f else fs[0]
            if g == f or not T.tangent(j, f, g):
                continue
            tangent_edges.add(j)
            if g in seen:
                continue
            gi = info[g]
            if gi["kind"] not in ("plane", "cylinder"):
                reasons.append({"face": g, "kind": gi["kind"], "at": gi["p"].round(4).tolist(),
                                "why": f"A {gi['kind']} on the sheet's skin is not developable here (a formed "
                                       "feature such as a louvre or an emboss): it cannot be laid flat."})
                seen.add(g)
                continue
            # the frame we arrive with
            if f in frames:
                M_in = frames[f]
            else:
                bf = bendof[f]
                pe = _edge_points(T.edges[j], 5)
                if float(np.max(np.abs(bf.phi(pe) - bf.theta))) < 1e-5:
                    M_in = bf.M_after
                elif gi["kind"] == "cylinder" and _coaxial(info[f], gi):
                    M_in = None          # the same bend split along its axis: same frame
                else:
                    continue             # its entry edge: g is where we came from
            if gi["kind"] == "plane":
                if M_in is None:
                    continue
                frames[g] = M_in
                path[g] = list(path[f])
                if f in bendof and f not in frames:
                    bendof[f].after.append(g)
            else:
                if M_in is None:
                    bendof[g] = bendof[f]
                    path[g] = list(path[f])
                else:
                    r_in, why = _inside_radius(info, g, t)
                    if why:
                        reasons.append({"face": g, "kind": "cylinder", "at": _v(T.faces[g].center()).round(4).tolist(),
                                        "why": why})
                        seen.add(g)
                        continue
                    pe = _edge_points(T.edges[j], 5)
                    probe = _Bend(g, gi, M_in, pe, t, r_in, {"K": 0.0})
                    K = kfactor(r_in, t, math.degrees(probe.theta))
                    bendof[g] = _Bend(g, gi, M_in, pe, t, r_in, K)
                    bendof[g].before = f
                    k_rows[g] = K
                    path[g] = list(path[f]) + [g]
            seen.add(g)
            queue.append(g)

    skin = sorted(seen - {r["face"] for r in reasons if "face" in r})
    # ---- what every face is
    partners = set()
    for i in skin:
        fi = info[i]
        if fi["kind"] == "plane":
            hit = [k for k in planes if float(info[k]["n"] @ fi["n"]) < -1 + 1e-6
                   and abs(float((fi["p"] - info[k]["p"]) @ fi["n"]) - t) < 1e-4]
            if not hit:
                reasons.append({"face": i, "kind": "plane", "at": fi["p"].round(4).tolist(),
                                "why": f"No face {t:g} mm behind this flat face: the thickness is not constant."})
            partners.update(hit)
        else:
            for k, fk in enumerate(info):
                if fk["kind"] == "cylinder" and k != i and _coaxial(fi, fk) and abs(abs(fk["R"] - fi["R"]) - t) < 1e-4:
                    partners.add(k)
    roles = {}
    for i, fi in enumerate(info):
        if i in skin:
            roles[i] = "bend" if fi["kind"] == "cylinder" else "flat"
        elif i in partners:
            roles[i] = "other side"
        else:
            roles[i] = "edge"
    # an edge face (the sheet's cut edge) meets the sheet square: along at least one of its edges it touches a face
    # of either skin at a right angle. Anything else is not sheet metal.
    sheet_faces = set(skin) | partners
    for i, fi in enumerate(info):
        if roles[i] != "edge" or any(r.get("face") == i for r in reasons):
            continue
        ok = False
        for j in T.face_edges[i]:
            for g in T.edge_faces[j]:
                if g in sheet_faces and g != i:
                    pm = T.edges[j].position_at(0.5)
                    if abs(float(_v(T.faces[i].normal_at(pm)) @ _v(T.faces[g].normal_at(pm)))) < 1e-4:
                        ok = True
                        break
            if ok:
                break
        if not ok:
            round_ = fi["kind"] == "cylinder" and any(g in sheet_faces and g != i and T.tangent(j, i, g)
                                                      for j in T.face_edges[i] for g in T.edge_faces[j])
            why = (f"A cylinder of radius {fi['R']:g} mm tangent to the sheet with no partner {t:g} mm from it: an "
                   "edge round, not a bend." if round_ else
                   f"A {fi['kind']} that is neither on the sheet nor square to it (a formed feature such as a louvre, "
                   "a chamfer, or a second body).")
            reasons.append({"face": i, "kind": fi["kind"], "at": _v(T.faces[i].center()).round(4).tolist(), "why": why})
    vol = float(shape.volume)
    exp = 0.0
    for i in skin:
        fi = info[i]
        if fi["kind"] == "plane":
            exp += fi["area"] * t
        else:
            b = bendof[i]
            exp += fi["area"] * t * (b.r + t / 2) / fi["R"]
    vol_err = abs(vol - exp) / max(vol, 1e-9)
    if vol_err > 1e-4 and not reasons:
        reasons.append({"why": f"The solid's volume {vol:.3f} mm³ is not its skin's area × t ({exp:.3f} mm³, "
                               f"{vol_err * 100:.3f} % apart): it is not one sheet of constant thickness."})

    # ---- map the cut edges
    def to_flat(face: int, P: np.ndarray) -> np.ndarray:
        if face in frames:
            return _apply(frames[face], P)
        return bendof[face].to_flat(P)

    ents = []
    for i in skin:
        for j in T.face_edges[i]:
            if j in tangent_edges:
                continue
            fs = T.edge_faces[j]
            if len(fs) == 2 and fs[0] == fs[1]:
                continue
            e = T.edges[j]
            kind = _edge_kind(e)
            if kind == "line":
                P = to_flat(i, np.array([_v(e.position_at(0)), _v(e.position_at(1))]))
                ents.append({"t": "line", "a": P[0, :2].tolist(), "b": P[1, :2].tolist(), "face": i, "z": float(np.abs(P[:, 2]).max())})
                continue
            P = to_flat(i, _edge_points(e, 65))
            zerr = float(np.abs(P[:, 2]).max())
            Q = P[:, :2]
            if kind == "circle" and i in frames:
                from OCP.BRepAdaptor import BRepAdaptor_Curve
                circ = BRepAdaptor_Curve(e.wrapped).Circle()
                c = to_flat(i, _v(circ.Location())[None])[0, :2]
                r = float(circ.Radius())
                if float(np.hypot(*(Q[0] - Q[-1]))) < 1e-7:
                    ents.append({"t": "circle", "c": c.tolist(), "r": r, "face": i, "z": zerr})
                    continue
                ang = np.degrees(np.arctan2(Q[:, 1] - c[1], Q[:, 0] - c[0]))
                a0, a1, am = ang[0], ang[-1], ang[len(ang) // 2]
                if (am - a0) % 360 > (a1 - a0) % 360:
                    a0, a1 = a1, a0
                ents.append({"t": "arc", "c": c.tolist(), "r": r, "a0": float(a0 % 360), "a1": float(a1 % 360),
                             "face": i, "z": zerr})
                continue
            d = Q[-1] - Q[0]
            L = float(np.hypot(*d))
            if L > 1e-9:
                nrm = np.array([-d[1], d[0]]) / L
                if float(np.max(np.abs((Q - Q[0]) @ nrm))) < 1e-6:
                    ents.append({"t": "line", "a": Q[0].tolist(), "b": Q[-1].tolist(), "face": i, "z": zerr})
                    continue
            closed = float(np.hypot(*(Q[0] - Q[-1]))) < 1e-7
            ents.append({"t": "poly", "pts": (Q[:-1] if closed else Q).tolist(), "closed": closed, "face": i, "z": zerr})

    # ---- bends: start, end and centre lines in the flat
    bends = []
    done = set()
    for g, b in bendof.items():
        if id(b) in done:
            continue
        done.add(id(b))
        faces = [k for k, bb in bendof.items() if bb is b]
        pts = np.vstack([_edge_points(T.edges[j], 2) for k in faces for j in T.face_edges[k]])
        along = (pts - b.loc) @ b.a
        lo, hi = float(along.min()), float(along.max())
        A3 = b.loc + lo * b.a + b.R_s * b.e0
        B3 = b.loc + hi * b.a + b.R_s * b.e0
        S = _apply(b.M, np.array([A3, B3]))[:, :2]
        u = (S[1] - S[0]) / max(np.linalg.norm(S[1] - S[0]), 1e-12)
        d2 = _apply(b.M, (A3 + b.d)[None])[0, :2] - S[0]
        d2 = d2 - (d2 @ u) * u
        d2 /= np.linalg.norm(d2)
        E = S + b.w * d2
        C = S + b.w / 2 * d2
        bends.append({"id": g, "faces": faces, "angle": math.degrees(b.theta), "direction": "up" if b.s > 0 else "down",
                      "s": b.s, "r": b.r, "t": t, "K": b.K["K"], "k_source": b.K, "R_s": b.R_s, "R_n": b.R_n, "w": b.w,
                      "allowance": b.w, "length": hi - lo, "q": S[0].tolist(), "u": u.tolist(), "d": d2.tolist(),
                      "start": S.tolist(), "end": E.tolist(), "line": C.tolist(), "path": path[g][:-1],
                      "before": b.before, "after": sorted(set(b.after)),
                      "axis": {"point": b.loc.round(6).tolist(), "dir": b.a.round(9).tolist()}})
    bend_by_id = {b["id"]: b for b in bends}

    # ---- the frame: shift so the flat starts at (0, 0)
    if ents:
        lo, _hi = geom2d.bbox(ents)
    else:
        lo = np.zeros(2)
    shift = -lo
    for e in ents:
        _shift(e, shift)
    for b in bends:
        for k in ("q",):
            b[k] = (np.asarray(b[k]) + shift).tolist()
        for k in ("start", "end", "line"):
            b[k] = (np.asarray(b[k]) + shift).tolist()
    frame = {"origin": (p0 - ex * shift[0] - ey * shift[1]).tolist(), "x": ex.tolist(), "y": ey.tolist(),
             "z": ez.tolist()}
    loops, opens = geom2d.chain(ents, tol=1e-3)
    geom2d.nest(loops)

    # ---- verify: lay flat, fold back from the flat pattern's numbers, compare
    verify = _verify(T, skin, frames, bendof, bend_by_id, path, shift, frame, t, tol_fold, max_samples)
    flat_samples = verify.pop("_flat")
    out = {"ok": not reasons and not opens and verify["max_mm"] <= tol_fold, "reasons": reasons, "t": t,
           "base_face": base, "entities": ents, "bends": bends, "frame": frame,
           "loops": [{"area": round(abs(geom2d.exact_area(lp, ents)), 6), "depth": lp["depth"],
                      "items": [k for k, _r in lp["items"]], "n": len(lp["items"])} for lp in loops],
           "open_ends": [o["ends"] for o in opens], "verify": verify,
           "regions": {str(i): {"path": list(path[i]), "zone": (bendof[i].fi if i in bendof else None),
                                "samples": flat_samples.get(str(i), [])} for i in skin},
           "faces": [{"face": i, "kind": info[i]["kind"], "role": roles[i]} for i in range(len(info))],
           "volume_mm3": round(vol, 6), "volume_expected_mm3": round(exp, 6), "volume_rel_err": vol_err,
           "seconds": round(time.perf_counter() - t0, 3)}
    if opens:
        reasons.append({"why": f"{len(opens)} cut edge chain(s) of the flat do not close."})
        out["ok"] = False
    outer = [lp for lp in loops if lp["depth"] == 0]
    holes = [lp for lp in loops if lp["depth"] == 1]
    if outer:
        o = max(outer, key=lambda lp: abs(lp["area"]))
        a = abs(geom2d.exact_area(o, ents)) - sum(abs(geom2d.exact_area(h, ents)) for h in holes if h["parent"] == loops.index(o))
        out["area_mm2"] = round(a, 6)
        out["outline_mm"] = round(sum(geom2d.length(ents[k]) for k, _ in o["items"]), 6)
        mn, mx = geom2d.bbox([ents[k] for k, _ in o["items"]])
        out["size_mm"] = [round(float(mx[0] - mn[0]), 6), round(float(mx[1] - mn[1]), 6)]
        out["outer_loops"] = len(outer)
        # the flat must not cross itself (two flanges laid on the same place)
        X = geom2d.crossings(o["pts"])
        for lp in loops:
            if lp is not o:
                X += geom2d.crossings(o["pts"], lp["pts"])
        out["flat_crossings"] = X[:20]
        if X or len(outer) > 1:
            out["ok"] = False
            reasons.append({"why": "The flat pattern overlaps itself: two parts of the sheet land on the same "
                                   "place when laid flat." if X else
                                   f"The flat pattern falls in {len(outer)} pieces."})
    return out


def _shift(e: dict, s: np.ndarray) -> None:
    if e["t"] == "line":
        e["a"] = (np.asarray(e["a"]) + s).tolist()
        e["b"] = (np.asarray(e["b"]) + s).tolist()
    elif e["t"] in ("arc", "circle"):
        e["c"] = (np.asarray(e["c"]) + s).tolist()
    else:
        e["pts"] = (np.asarray(e["pts"]) + s).tolist()


def _coaxial(a: dict, b: dict) -> bool:
    if abs(abs(float(a["z"] @ b["z"])) - 1) > 1e-9:
        return False
    rel = b["loc"] - a["loc"]
    return float(np.linalg.norm(rel - (rel @ a["z"]) * a["z"])) < 1e-6


def _inside_radius(info: list, g: int, t: float) -> tuple[float, str]:
    gi = info[g]
    want = gi["R"] + t if gi["concave"] else gi["R"] - t
    for k, fk in enumerate(info):
        if fk["kind"] == "cylinder" and k != g and _coaxial(gi, fk) and abs(fk["R"] - want) < 1e-4:
            return (gi["R"] if gi["concave"] else want), ""
    if not gi["concave"] and abs(gi["R"] - t) < 1e-4:
        return 0.0, ""          # a sharp inside corner: inside radius 0
    return 0.0, (f"A cylinder of radius {gi['R']:g} mm tangent to the sheet with no partner {t:g} mm "
                 f"{'outside' if gi['concave'] else 'inside'} it: an edge round, not a bend.")


def _verify(T, skin, frames, bendof, bends, path, shift, frame, t, tol, max_samples) -> dict:
    """Lay every tessellation vertex of the skin flat, fold it back from the flat pattern, and measure."""
    worst, n, where = 0.0, 0, None
    flat_samples: dict = {}
    per = max(8, max_samples // max(len(skin), 1))
    for i in skin:
        f = T.faces[i]
        try:
            verts, _tris = f.tessellate(0.05, 0.3)
        except Exception:                  # noqa: BLE001 - a face that does not mesh is checked by its samples
            verts = []
        P = np.array([_v(v) for v in verts]) if len(verts) else T.info[i]["samples"]
        if len(P) > per:
            P = P[np.linspace(0, len(P) - 1, per).astype(int)]
        N = np.array([_v(f.normal_at(f.center()))] * len(P)) if T.info[i]["kind"] == "plane" else \
            np.array([_v(f.normal_at(_vec(p))) for p in P])
        for z, Pw in ((0.0, P), (-t, P - t * N)):
            if i in frames:
                F = _apply(frames[i], Pw)
            else:
                F = bendof[i].to_flat(P)
                F[:, 2] = z
            F[:, :2] += shift
            if z == 0.0:
                flat_samples[str(i)] = np.round(F[:: max(1, len(F) // 160), :2], 6).tolist()
            zone = bendof[i].fi if i in bendof else None
            p = path[i]
            W = foldmod.to_world(foldmod.fold(F[:, :2], F[:, 2] if i in frames else z, p, zone, bends), frame)
            d = np.linalg.norm(W - Pw, axis=1)
            k = int(np.argmax(d))
            if d[k] > worst:
                worst, where = float(d[k]), {"face": i, "at": Pw[k].round(4).tolist()}
            n += len(P)
    return {"max_mm": worst, "samples": n, "tolerance_mm": tol, "worst": where, "_flat": flat_samples,
            "method": "every skin vertex and the point t behind it, laid flat and folded back from the flat "
                      "pattern's bend lines, angles, radii and K-factors (form/sheet/fold.py)",
            "pass": worst <= tol}


def _vec(p):
    from build123d import Vector
    return Vector(*[float(x) for x in p])
