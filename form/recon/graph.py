"""The Layer 1 solid as a graph of faces, and the features found on it. Kernel worker only (imports OCCT).

Faces are read from the B-rep (their surface type and axis, outward normal, area, angular span) and joined across
shared edges. Neighbouring faces on one surface (a hole split at its seam) are one logical face, a "group".

Features, each a set of faces that can be taken off the solid (BRepAlgoAPI_Defeaturing) and put back by an operation:

- hole: concave cylinders that go all the way round, on one axis, with the plane rings (counterbore floors) and cones
  (countersinks, drill points) between them; open at one or both ends;
- fillet: a cylinder, torus or sphere that meets two faces tangentially along its rails (constant radius);
- chamfer: a narrow plane or cone between two faces it meets at equal angles (equal distances).
"""
from __future__ import annotations

import math

import numpy as np

TANGENT_DEG = 3.0


def _np(p):
    return np.array([p.X(), p.Y(), p.Z()])


class Graph:
    def __init__(self, shape, tol: float):
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopExp import TopExp
        from OCP.collections import (IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EMap,
                                     IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as FMap)
        from OCP.TopoDS import TopoDS
        self.shape, self.tol = shape, tol
        fm = FMap()
        TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
        self.faces = [TopoDS.Face(fm.FindKey(i)) for i in range(1, fm.Extent() + 1)]
        em = EMap()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, em)
        self.edges = []                     # (edge, [face indices])
        self.nb = [dict() for _ in self.faces]          # face -> {neighbour: [edge index]}
        for i in range(1, em.Extent() + 1):
            e = TopoDS.Edge(em.FindKey(i))
            fs = []
            for f in em.FindFromIndex(i):
                k = fm.FindIndex(f) - 1
                if k not in fs:
                    fs.append(k)
            ei = len(self.edges)
            self.edges.append((e, fs))
            for a in fs:
                for b in fs:
                    if a != b:
                        self.nb[a].setdefault(b, []).append(ei)
        self.info = [self._face_info(f) for f in self.faces]
        bb = np.array([fi["center"] for fi in self.info])
        self.size = float(np.ptp(bb, axis=0).max()) if len(bb) > 1 else 1.0
        self._sas = {}
        self._emid = {}
        self._groups()

    # ---- per face ----------------------------------------------------------------------------------------------
    def _face_info(self, f):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepGProp import BRepGProp, BRepGProp_Face
        from OCP.BRepTools import BRepTools
        from OCP.GeomAbs import (GeomAbs_BSplineSurface, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere,
                                 GeomAbs_Torus)
        from OCP.GProp import GProp_GProps
        from OCP.gp import gp_Pnt, gp_Vec
        ad = BRepAdaptor_Surface(f, True)
        t = ad.GetType()
        d = {"kind": "other"}
        if t == GeomAbs_Plane:
            pl = ad.Plane()
            d = {"kind": "plane", "o": _np(pl.Location()), "a": _np(pl.Axis().Direction())}
        elif t == GeomAbs_Cylinder:
            c = ad.Cylinder()
            d = {"kind": "cylinder", "o": _np(c.Location()), "a": _np(c.Axis().Direction()), "r": c.Radius()}
        elif t == GeomAbs_Cone:
            c = ad.Cone()
            d = {"kind": "cone", "o": _np(c.Location()), "a": _np(c.Axis().Direction()), "r": c.RefRadius(),
                 "half_angle": c.SemiAngle(), "apex": _np(c.Apex())}
        elif t == GeomAbs_Sphere:
            c = ad.Sphere()
            d = {"kind": "sphere", "o": _np(c.Location()), "a": _np(c.Position().Direction()), "r": c.Radius()}
        elif t == GeomAbs_Torus:
            c = ad.Torus()
            d = {"kind": "torus", "o": _np(c.Location()), "a": _np(c.Axis().Direction()), "R": c.MajorRadius(),
                 "r": c.MinorRadius()}
        elif t == GeomAbs_BSplineSurface:
            d = {"kind": "bspline"}
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        d["uspan"] = u1 - u0
        P, N = gp_Pnt(), gp_Vec()
        BRepGProp_Face(f).Normal(0.5 * (u0 + u1), 0.5 * (v0 + v1), P, N)
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        d["area"] = g.Mass()
        d["center"] = _np(g.CentreOfMass())
        d["pt"], d["n"] = _np(P), _np(N) / max(N.Magnitude(), 1e-300)
        if d["kind"] in ("cylinder", "cone", "torus", "sphere"):
            d["convex"] = self._convex(d)
        return d

    @staticmethod
    def _convex(d):
        """Does the outward normal point away from the axis (a boss, a rounded outside edge) or towards it (a hole)?"""
        p, n = d["pt"], d["n"]
        if d["kind"] == "sphere":
            return float((p - d["o"]) @ n) > 0
        rel = p - d["o"]
        radial = rel - (rel @ d["a"]) * d["a"]
        if d["kind"] == "torus":
            rn = np.linalg.norm(radial)
            ring = d["o"] + d["a"] * (rel @ d["a"]) + (radial / rn if rn > 0 else radial) * d["R"]
            return float((p - ring) @ n) > 0
        return float(radial @ n) > 0

    def normal_at(self, i, p):
        """Outward normal of face i at (the projection of) point p."""
        from OCP.BRep import BRep_Tool
        from OCP.BRepGProp import BRepGProp_Face
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.gp import gp_Pnt, gp_Vec
        sas = self._sas.get(i)
        if sas is None:
            sas = self._sas[i] = ShapeAnalysis_Surface(BRep_Tool.Surface_s(self.faces[i]))
        uv = sas.ValueOfUV(gp_Pnt(*map(float, p)), 1e-7)
        P, N = gp_Pnt(), gp_Vec()
        BRepGProp_Face(self.faces[i]).Normal(uv.X(), uv.Y(), P, N)
        return _np(N) / max(N.Magnitude(), 1e-300)

    def edge_mid(self, ei):
        got = self._emid.get(ei)
        if got is None:
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            from OCP.GCPnts import GCPnts_AbscissaPoint
            from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
            c = BRepAdaptor_Curve(self.edges[ei][0])
            t0, t1 = c.FirstParameter(), c.LastParameter()
            kind = {GeomAbs_Line: "line", GeomAbs_Circle: "circle"}.get(c.GetType(), "other")
            extra = {}
            if kind == "circle":
                ci = c.Circle()
                extra = {"o": _np(ci.Location()), "a": _np(ci.Axis().Direction()), "r": ci.Radius()}
            got = {"mid": _np(c.Value(0.5 * (t0 + t1))), "p0": _np(c.Value(t0)), "p1": _np(c.Value(t1)), "kind": kind,
                   "length": GCPnts_AbscissaPoint.Length_s(c), **extra}
            self._emid[ei] = got
        return got

    def tangent(self, i, j) -> bool:
        """Do faces i and j meet smoothly along their shared edges (checked at each edge's middle)?"""
        for ei in self.nb[i].get(j, []):
            m = self.edge_mid(ei)["mid"]
            if float(self.normal_at(i, m) @ self.normal_at(j, m)) < math.cos(math.radians(TANGENT_DEG)):
                return False
        return bool(self.nb[i].get(j))

    def angle(self, i, j) -> float:
        ei = self.nb[i][j][0]
        m = self.edge_mid(ei)["mid"]
        return math.degrees(math.acos(max(-1.0, min(1.0, float(self.normal_at(i, m) @ self.normal_at(j, m))))))

    # ---- logical faces -----------------------------------------------------------------------------------------
    def same_surface(self, i, j) -> bool:
        a, b = self.info[i], self.info[j]
        if a["kind"] != b["kind"] or a["kind"] in ("other", "bspline"):
            return False
        eps = 1e-6 * max(self.size, 1.0)
        if a["kind"] == "plane":
            return abs(abs(a["a"] @ b["a"]) - 1) < 1e-9 and abs((b["o"] - a["o"]) @ a["a"]) < eps and a["a"] @ b["a"] > 0
        if abs(abs(a["a"] @ b["a"]) - 1) > 1e-9 or np.linalg.norm(np.cross(b["o"] - a["o"], a["a"])) > eps:
            if a["kind"] != "sphere":
                return False
        for k in ("r", "R", "half_angle"):
            if k in a and abs(a[k] - b[k]) > eps:
                return False
        if a["kind"] == "sphere" and np.linalg.norm(a["o"] - b["o"]) > eps:
            return False
        return a.get("convex") == b.get("convex")

    def _groups(self):
        n = len(self.faces)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i in range(n):
            for j in self.nb[i]:
                if j > i and self.same_surface(i, j):
                    parent[find(i)] = find(j)
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        self.groups = list(groups.values())
        self.group_of = [0] * n
        for gi, g in enumerate(self.groups):
            for i in g:
                self.group_of[i] = gi

    def ginfo(self, g):
        fs = self.groups[g]
        d = dict(self.info[fs[0]])
        d["area"] = sum(self.info[i]["area"] for i in fs)
        d["uspan"] = sum(self.info[i]["uspan"] for i in fs)
        d["faces"] = list(fs)
        return d

    def gnb(self, g):
        """Neighbouring groups of group g: {group: [edge indices]}."""
        out = {}
        for i in self.groups[g]:
            for j, es in self.nb[i].items():
                h = self.group_of[j]
                if h != g:
                    out.setdefault(h, []).extend(es)
        return out

    def gtangent(self, g, h) -> bool:
        return all(self.tangent(i, j) for i in self.groups[g] for j in self.nb[i] if self.group_of[j] == h)


# ---- features --------------------------------------------------------------------------------------------------------

def _coaxial(d, o, a, eps):
    if d["kind"] not in ("cylinder", "cone"):
        return False
    return abs(abs(d["a"] @ a) - 1) < 1e-7 and np.linalg.norm(np.cross(d["o"] - o, a)) < eps


def _ring(d):
    return d["uspan"] >= 2 * math.pi - 1e-3


def holes(G: Graph) -> list[dict]:
    eps = 1e-5 * max(G.size, 1.0)
    used = set()
    out = []
    for g0 in sorted(range(len(G.groups)), key=lambda g: -G.ginfo(g)["area"]):
        d0 = G.ginfo(g0)
        if g0 in used or d0["kind"] != "cylinder" or d0["convex"] or not _ring(d0):
            continue
        o, a = d0["o"], d0["a"] / np.linalg.norm(d0["a"])
        chain = {g0}
        changed = True
        bad = False
        while changed:
            changed = False
            for g in list(chain):
                for h in G.gnb(g):
                    if h in chain:
                        continue
                    dh = G.ginfo(h)
                    if dh["kind"] in ("cylinder", "cone") and _coaxial(dh, o, a, eps) and not dh["convex"]:
                        if dh["kind"] == "cylinder" and not _ring(dh):
                            bad = True
                        chain.add(h)
                        changed = True
                    elif dh["kind"] == "plane" and abs(abs(dh["a"] @ a) - 1) < 1e-7:
                        nbs = G.gnb(h)
                        if all(_coaxial(G.ginfo(k), o, a, eps) and not G.ginfo(k)["convex"] for k in nbs):
                            chain.add(h)
                            changed = True
        if bad:
            continue
        spec = _hole_spec(G, chain, o, a, eps)
        if spec is None:
            continue
        used |= chain
        out.append(spec)
    return _merge_collinear(out, eps)


def _merge_collinear(hs, eps):
    """Pieces of one straight hole that something else interrupts (a cross hole through a bore) are one hole."""
    out = []
    for h in hs:
        simple = h["through"] and len(h["steps"]) == 1 and h["steps"][0][0] == "cyl"
        for g in out:
            if not (simple and g["through"] and len(g["steps"]) == 1 and g["steps"][0][0] == "cyl"):
                continue
            if abs(g["steps"][0][1] - h["steps"][0][1]) > eps or abs(abs(g["dir"] @ h["dir"]) - 1) > 1e-7:
                continue
            if np.linalg.norm(np.cross(h["origin"] - g["origin"], g["dir"])) > eps:
                continue
            d = g["dir"]
            ends = [0.0, g["steps"][0][2]] + [float((h["origin"] - g["origin"]) @ d) + t * float(h["dir"] @ d) * h["steps"][0][2]
                                               for t in (0, 1)]
            lo, hi = min(ends), max(ends)
            g["origin"] = g["origin"] + lo * d
            g["steps"] = [("cyl", g["steps"][0][1], hi - lo)]
            g["faces"] = g["faces"] + h["faces"]
            g["groups"] = sorted(g["groups"] + h["groups"])
            g["area"] += h["area"]
            g["pieces"] = g.get("pieces", 1) + 1
            break
        else:
            out.append(h)
    return out


def _axial(G, g, o, a):
    """Axial range of a group's edges (their end and middle points) about (o, a)."""
    s = []
    for h, es in G.gnb(g).items():
        for ei in es:
            m = G.edge_mid(ei)
            s += [float((m[k] - o) @ a) for k in ("p0", "p1", "mid")]
    return (min(s), max(s)) if s else (0.0, 0.0)


def _hole_spec(G, chain, o, a, eps):
    """From the faces of a hole: where it enters, which way it goes and its steps."""
    segs = []                   # (s0, s1, kind, r0, r1)
    floors = []
    for g in chain:
        d = G.ginfo(g)
        s0, s1 = _axial(G, g, o, a)
        if d["kind"] == "cylinder":
            segs.append((s0, s1, "cyl", d["r"], d["r"]))
        elif d["kind"] == "cone":
            # radius at both ends, from the cone itself
            def rad(s):
                p = o + s * a
                ap = d["apex"]
                return abs(float((p - ap) @ (d["a"] / np.linalg.norm(d["a"])))) * math.tan(abs(d["half_angle"]))
            segs.append((s0, s1, "cone", rad(s0), rad(s1)))
        else:
            floors.append((float((d["o"] - o) @ a), g))
    if not segs:
        return None
    segs.sort()
    lo, hi = segs[0][0], segs[-1][1]
    # is each end open (the hole meets an outside face there) or closed (a floor or a drill point)?
    def closed_at(s):
        if any(abs(f - s) < max(eps, 1e-4) for f, g in floors):
            return "flat"
        for s0, s1, kind, r0, r1 in segs:
            if kind == "cone" and ((abs(s0 - s) < 1e-4 and r0 < 1e-3) or (abs(s1 - s) < 1e-4 and r1 < 1e-3)):
                return "point"
        return None
    c_lo, c_hi = closed_at(lo), closed_at(hi)
    if c_lo and c_hi:
        return None                                       # a closed void
    if c_lo:
        entry, sign = hi, -1.0
    elif c_hi:
        entry, sign = lo, 1.0
    else:
        r_lo = max(r for s0, s1, k, r0, r1 in segs if abs(s0 - lo) < 1e-4 for r in (r0, r1))
        r_hi = max(r for s0, s1, k, r0, r1 in segs if abs(s1 - hi) < 1e-4 for r in (r0, r1))
        entry, sign = (hi, -1.0) if r_hi > r_lo + 1e-6 else (lo, 1.0)
    d = a * sign
    steps = []
    for s0, s1, kind, r0, r1 in (segs if sign > 0 else list(reversed(segs))):
        L = s1 - s0
        if sign < 0:
            r0, r1 = r1, r0
        if L < 1e-6:
            continue
        steps.append(("cyl", 2 * r0, L) if kind == "cyl" else ("cone", 2 * r0, 2 * r1, L))
    tip = None
    if (c_lo or c_hi) == "point" and steps and steps[-1][0] == "cone":
        last = steps.pop()
        half = math.atan2(last[1] / 2, last[3])
        tip = 2 * math.degrees(half)
    faces = [f for g in chain for f in G.groups[g]]
    return {"kind": "hole", "origin": o + entry * a, "dir": d, "steps": steps, "through": not (c_lo or c_hi),
            "tip_angle": tip, "faces": faces, "groups": sorted(chain), "area": sum(G.info[f]["area"] for f in faces)}


def blends(G: Graph, skip: set) -> list[dict]:
    """Fillets: cylinders (not all the way round), tori and spheres that meet two or more faces tangentially."""
    out = []
    for g in range(len(G.groups)):
        if g in skip:
            continue
        d = G.ginfo(g)
        if d["kind"] not in ("cylinder", "torus", "sphere"):
            continue
        if d["kind"] == "cylinder" and _ring(d):
            continue
        if d["r"] > 0.3 * G.size:
            continue
        nbs = G.gnb(g)
        tang = [h for h in nbs if G.gtangent(g, h)]
        if len(tang) < 2:
            continue
        rails = [h for h in tang if G.ginfo(h)["kind"] not in ("cylinder", "torus", "sphere")
                 or abs(G.ginfo(h).get("r", -1) - d["r"]) > 1e-6]
        if d["kind"] != "sphere" and len(rails) < 2:
            continue
        faces = list(G.groups[g])
        out.append({"kind": "fillet", "r": d["r"], "convex": d["convex"], "surface": d["kind"], "groups": [g],
                    "rails": rails, "faces": faces, "area": d["area"]})
    return out


def chamfers(G: Graph, skip: set) -> list[dict]:
    """A narrow plane (or cone round an axis) between two faces it meets at equal angles."""
    out = []
    for g in range(len(G.groups)):
        if g in skip:
            continue
        d = G.ginfo(g)
        if d["kind"] not in ("plane", "cone"):
            continue
        nbs = G.gnb(g)
        if len(nbs) < 2:
            continue
        shared = sorted(((sum(G.edge_mid(e)["length"] for e in es), h) for h, es in nbs.items()), reverse=True)
        (L1, h1), (L2, h2) = shared[0], shared[1]
        if any(G.gtangent(g, h) for h in (h1, h2)):
            continue
        rest = sum(L for L, _ in shared[2:])
        w = d["area"] / max(0.5 * (L1 + L2), 1e-9)
        if w > 0.15 * min(L1, L2) or w > 0.1 * G.size or rest > 0.5 * (L1 + L2):
            continue
        a1 = _gangle(G, g, h1)
        a2 = _gangle(G, g, h2)
        if a1 is None or a2 is None or not (15 < a1 < 75 and 15 < a2 < 75) or abs(a1 - a2) > 2.0:
            continue
        faces = list(G.groups[g])
        out.append({"kind": "chamfer", "width": w, "angles": (a1, a2), "groups": [g], "rails": [h1, h2], "faces": faces,
                    "area": d["area"]})
    return out


def _gangle(G, g, h):
    for i in G.groups[g]:
        for j in G.nb[i]:
            if G.group_of[j] == h:
                return G.angle(i, j)
    return None
