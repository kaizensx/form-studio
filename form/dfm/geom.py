"""Geometry for manufacturability, measured on the kernel's B-rep and its tessellation (kernel worker only).

Every measurement here is one of these, and says which:

* **Exact on the B-rep.** Face normals and surface classes (plane, cylinder, cone) from OCCT; the draft of a plane,
  of a cylinder or cone whose axis is the pull, read from the surface itself; hole and corner radii from the
  cylinder; enclosed voids from the solid's shells; edge convexity from the two faces' normals at the edge.
* **Rays on the tessellation.** Visibility along a direction (can the mould release this surface? can a tool come
  down on it?) is a ray from each surface sample along the direction, tested against every triangle of the part's
  0.05 mm tessellation. Rays that share a direction are cast together: the triangles are projected onto the plane
  normal to the direction and binned on a grid, so each ray only meets the triangles of its own cell. The answer is
  exact for the tessellation, which is within its tolerance of the B-rep.
* **A height field.** For a tool coming down a direction, the highest surface over every pixel of a grid normal to
  it (the z-map of CAM: Choi and Jerard, *Sculptured Surface Machining*, 1998, ch. 6), then the highest over a disc
  of the tool's radius (a flat end mill cannot go lower than the highest material under its end). The pixel is
  stated; a feature narrower than it can be missed.

Samples are the centroids of the tessellation's triangles, split until no edge is longer than the sample spacing, so
every square millimetre counts about the same. Each sample keeps its B-rep face (``model["faces"]`` index).
"""
from __future__ import annotations

import math

import numpy as np

EPS = 1e-9


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("a direction needs a length")
    return v / n


def basis(d) -> tuple[np.ndarray, np.ndarray]:
    """Two unit vectors normal to d and to each other."""
    d = unit(d)
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    return u, np.cross(d, u)


def fibonacci(n: int, hemisphere: bool = False) -> np.ndarray:
    """n directions spread evenly over the sphere (or the +z hemisphere): the golden-angle spiral."""
    k = np.arange(n) + 0.5
    z = 1 - k / n if hemisphere else 1 - 2 * k / n
    r = np.sqrt(np.clip(1 - z * z, 0, 1))
    phi = k * math.pi * (3 - math.sqrt(5))
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


# ---- the surface: triangles and samples -------------------------------------------------------------------------

class Surface:
    """The part's triangles (for casting) and its samples (where things are measured).

    tri_*: one row per tessellation triangle. S, N, A, F: sample point, outward unit normal, area it stands for (mm²),
    and its B-rep face index (into model["faces"])."""

    def __init__(self, model, spacing: float | None = None, max_samples: int = 60000):
        from ..analysis import refine
        faces = model["faces"]
        Ps, Ts, Fs, off = [], [], [], 0
        for i, f in enumerate(faces):
            P, T = np.asarray(f["P"], float), np.asarray(f["T"], np.int64)
            if not len(T):
                continue
            Ps.append(P)
            Ts.append(T + off)
            Fs.append(np.full(len(T), i))
            off += len(P)
        self.P = np.concatenate(Ps)
        self.T = np.concatenate(Ts)
        self.tri_face = np.concatenate(Fs)
        a, b, c = (self.P[self.T[:, k]] for k in range(3))
        n = np.cross(b - a, c - a)
        ar = np.linalg.norm(n, axis=1)
        ok = ar > 1e-14
        self.T, self.tri_face, a, b, c, n, ar = self.T[ok], self.tri_face[ok], a[ok], b[ok], c[ok], n[ok], ar[ok]
        self.tri = (a, b, c)
        self.tri_n = n / ar[:, None]
        self.tri_area = ar / 2
        lo, hi = self.P.min(axis=0), self.P.max(axis=0)
        self.lo, self.hi = lo, hi
        self.diag = float(np.linalg.norm(hi - lo)) or 1.0
        total = float(self.tri_area.sum())
        h = spacing or max(0.35, self.diag / 140.0)
        h = max(h, math.sqrt(total / max_samples) * 2.0)    # longest-edge splits leave about h²/4 per triangle
        self.h = h
        S, N, A, F, Q = [], [], [], [], []
        for i, f in enumerate(faces):
            P, T = np.asarray(f["P"], float), np.asarray(f["T"], np.int64)
            if not len(T):
                continue
            P2, T2, _parent = refine(P, T, h)
            p0, p1, p2 = P2[T2[:, 0]], P2[T2[:, 1]], P2[T2[:, 2]]
            nn = np.cross(p1 - p0, p2 - p0)
            aa = np.linalg.norm(nn, axis=1)
            keep = aa > 1e-14
            S.append(((p0 + p1 + p2) / 3)[keep])
            N.append((nn[keep] / aa[keep, None]))
            A.append(aa[keep] / 2)
            F.append(np.full(int(keep.sum()), i))
            Q.append(np.stack([p0[keep], p1[keep], p2[keep]], axis=1))
        self.S, self.N, self.A, self.F = (np.concatenate(x) for x in (S, N, A, F))
        self.Q = np.concatenate(Q)                     # (n, 3, 3): the small triangle each sample stands for
        self.faces = faces

    @property
    def area(self) -> float:
        return float(self.A.sum())


# ---- parallel rays: every triangle projected along one direction ------------------------------------------------

class Projection:
    """The part's triangles seen along direction d: each projected to the plane normal to d (coordinates on u, w)
    with its depth along d, binned on a grid so a ray only meets the triangles of its own cell."""

    def __init__(self, surf: Surface, d, cells: int = 160):
        self.d = unit(d)
        self.u, self.w = basis(self.d)
        a, b, c = surf.tri
        self.xy = [np.stack([x @ self.u, x @ self.w], axis=1) for x in (a, b, c)]
        self.z = [x @ self.d for x in (a, b, c)]
        allxy = np.concatenate(self.xy)
        self.lo = allxy.min(axis=0) - 1e-6
        ext = float((allxy.max(axis=0) - self.lo).max()) or 1.0
        self.g = ext / cells
        self.n = int(math.ceil(ext / self.g)) + 1
        tlo = np.minimum(np.minimum(self.xy[0], self.xy[1]), self.xy[2])
        thi = np.maximum(np.maximum(self.xy[0], self.xy[1]), self.xy[2])
        i0 = np.floor((tlo - self.lo) / self.g).astype(np.int64)
        i1 = np.floor((thi - self.lo) / self.g).astype(np.int64)
        span = i1 - i0 + 1
        cnt = span[:, 0] * span[:, 1]
        tid = np.repeat(np.arange(len(cnt)), cnt)
        start = np.repeat(np.cumsum(cnt) - cnt, cnt)
        k = np.arange(len(tid)) - start
        sx = span[tid, 0]
        cx = i0[tid, 0] + k % sx
        cy = i0[tid, 1] + k // sx
        cell = cx * self.n + cy
        order = np.argsort(cell, kind="stable")
        self.cell_tri = tid[order]
        cell = cell[order]
        self.start = np.searchsorted(cell, np.arange(self.n * self.n))
        self.stop = np.searchsorted(cell, np.arange(self.n * self.n), side="right")
        # barycentric set-up per triangle (2D)
        p0, p1, p2 = self.xy
        self.e1, self.e2 = p1 - p0, p2 - p0
        det = self.e1[:, 0] * self.e2[:, 1] - self.e1[:, 1] * self.e2[:, 0]
        self.flat = np.abs(det) < 1e-12                        # seen edge-on along d: a ray never crosses it
        self.inv = np.where(self.flat, 0.0, 1.0 / np.where(self.flat, 1.0, det))

    def _cands(self, q2: np.ndarray):
        c = np.floor((q2 - self.lo) / self.g).astype(np.int64)
        inside = (c[:, 0] >= 0) & (c[:, 1] >= 0) & (c[:, 0] < self.n) & (c[:, 1] < self.n)
        cid = np.where(inside, c[:, 0] * self.n + c[:, 1], 0)
        s, e = self.start[cid], self.stop[cid]
        cnt = np.where(inside, e - s, 0)
        rid = np.repeat(np.arange(len(q2)), cnt)
        first = np.repeat(np.cumsum(cnt) - cnt, cnt)
        k = np.arange(len(rid)) - first
        tri = self.cell_tri[np.repeat(s, cnt) + k]
        return rid, tri

    def _hits(self, q2, rid, tri):
        """Depth along d where each candidate ray crosses its triangle (NaN where it misses)."""
        p0 = self.xy[0][tri]
        v = q2[rid] - p0
        e1, e2, inv = self.e1[tri], self.e2[tri], self.inv[tri]
        s = (v[:, 0] * e2[:, 1] - v[:, 1] * e2[:, 0]) * inv
        t = (e1[:, 0] * v[:, 1] - e1[:, 1] * v[:, 0]) * inv
        ok = (~self.flat[tri]) & (s >= -1e-9) & (t >= -1e-9) & (s + t <= 1 + 1e-9)
        z = self.z[0][tri] + s * (self.z[1][tri] - self.z[0][tri]) + t * (self.z[2][tri] - self.z[0][tri])
        return np.where(ok, z, np.nan)

    def blocked(self, pts: np.ndarray, sign: float = 1.0, eps: float = 1e-3, chunk: int = 20000,
                maxd: float | None = None) -> np.ndarray:
        """For rays from pts along sign·d: True where the ray meets a triangle further than eps along it (and, with
        maxd, no further than maxd: a stroke of that length is blocked)."""
        out = np.zeros(len(pts), bool)
        for i0 in range(0, len(pts), chunk):
            p = pts[i0:i0 + chunk]
            q2 = np.stack([p @ self.u, p @ self.w], axis=1)
            z0 = p @ self.d
            rid, tri = self._cands(q2)
            if not len(rid):
                continue
            z = self._hits(q2, rid, tri)
            dz = sign * (z - z0[rid])
            ahead = (dz > eps) if maxd is None else ((dz > eps) & (dz <= maxd))
            hit = np.zeros(len(p), bool)
            hit[rid[np.nan_to_num(ahead, nan=False).astype(bool)]] = True
            out[i0:i0 + chunk] = hit
        return out

    def heightmap(self, pix: float, chunk: int = 60000):
        """The highest surface depth along d over every pixel centre of a grid of size pix (−inf where empty):
        (H, origin, pix)."""
        allxy = np.concatenate(self.xy)
        lo = allxy.min(axis=0) - pix
        hi = allxy.max(axis=0) + pix
        nx, ny = (int(math.ceil(x)) + 1 for x in (hi - lo) / pix)
        gx, gy = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
        q2 = np.stack([lo[0] + gx.ravel() * pix, lo[1] + gy.ravel() * pix], axis=1)
        H = np.full(len(q2), -np.inf)
        for i0 in range(0, len(q2), chunk):
            q = q2[i0:i0 + chunk]
            rid, tri = self._cands(q)
            if not len(rid):
                continue
            z = self._hits(q, rid, tri)
            ok = ~np.isnan(z)
            np.maximum.at(H, i0 + rid[ok], z[ok])
        return H.reshape(nx, ny), lo, pix

    def covered(self, pix: float) -> tuple[float, float]:
        """Projected (shadow) area along d by pixel coverage, and its error bound. A pixel counts when its centre is
        covered (edges included), so the boundary pixels count half: area = (covered − boundary / 2) × pixel², and
        the bound is half the boundary pixels' area."""
        H, _lo, _p = self.heightmap(pix)
        m = np.isfinite(H)
        edge = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
        nb = float(edge.sum())
        return (float(m.sum()) - nb / 2) * pix * pix, nb * pix * pix / 2


def disc_max(H: np.ndarray, r_pix: float) -> np.ndarray:
    """The maximum of H over a disc of radius r_pix pixels around every pixel (a flat end mill's footprint)."""
    R = int(math.floor(r_pix))
    out = H.copy()
    if R <= 0:
        return out
    nx, ny = H.shape
    pad = np.full((nx + 2 * R, ny + 2 * R), -np.inf)
    pad[R:R + nx, R:R + ny] = H
    for dx in range(-R, R + 1):
        for dy in range(-R, R + 1):
            if dx * dx + dy * dy <= r_pix * r_pix + 1e-9 and (dx or dy):
                np.maximum(out, pad[R + dx:R + dx + nx, R + dy:R + dy + ny], out=out)
    return out


# ---- B-rep: faces, edges, holes, voids ---------------------------------------------------------------------------

def _gtype(face) -> str:
    return str(getattr(face.geom_type, "name", face.geom_type)).upper()


def _vec(v) -> np.ndarray:
    return np.array([float(v.X), float(v.Y), float(v.Z)])


def cylinder_of(face):
    """(axis point, unit axis, radius, concave, angular span in radians) of a cylindrical face, or None."""
    if _gtype(face) != "CYLINDER":
        return None
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    s = BRepAdaptor_Surface(face.wrapped)
    c = s.Cylinder()
    ax = c.Axis()
    p0 = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
    d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
    r = float(c.Radius())
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
    pc = face.center()
    n = _vec(face.normal_at(pc))
    q = _vec(pc) - p0
    radial = q - (q @ d) * d
    concave = bool(n @ radial < 0)
    return p0, d, r, concave, float(umax - umin)


def cone_half_angle(face):
    if _gtype(face) != "CONE":
        return None
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    c = BRepAdaptor_Surface(face.wrapped).Cone()
    ax = c.Axis().Direction()
    return np.array([ax.X(), ax.Y(), ax.Z()]), float(c.SemiAngle())


def face_draft(face, d, n_uv: int = 7) -> dict:
    """The draft of one B-rep face against pull d, in degrees: asin(n·d) at points of the face.

    Exact for a plane (one normal), and for a cylinder or cone whose axis is the pull (a constant draft: 0° and the
    half angle). Other surfaces are sampled on an n_uv × n_uv grid of their parameters (stated as sampled)."""
    d = unit(d)
    g = _gtype(face)
    if g == "PLANE":
        n = _vec(face.normal_at(face.center()))
        v = math.degrees(math.asin(max(-1.0, min(1.0, float(n @ d)))))
        return {"min": v, "max": v, "exact": True}
    if g == "CYLINDER":
        cy = cylinder_of(face)
        if cy is not None and abs(abs(cy[1] @ d) - 1) < 1e-9:
            return {"min": 0.0, "max": 0.0, "exact": True}
    if g == "CONE":
        ca = cone_half_angle(face)
        if ca is not None and abs(abs(ca[0] @ d) - 1) < 1e-9:
            # the normal of a cone makes 90° − half angle with its axis: |draft| = half angle, sign from a normal
            n = _vec(face.normal_at(face.center()))
            v = math.degrees(math.asin(max(-1.0, min(1.0, float(n @ d)))))
            return {"min": v, "max": v, "exact": True}
    vals = []
    for i in range(n_uv):
        for j in range(n_uv):
            try:
                n = _vec(face.normal_at((i + 0.5) / n_uv, (j + 0.5) / n_uv))
            except Exception:
                continue
            vals.append(math.degrees(math.asin(max(-1.0, min(1.0, float(n @ d))))))
    if not vals:
        return {"min": float("nan"), "max": float("nan"), "exact": False}
    return {"min": min(vals), "max": max(vals), "exact": False}


def _edge_faces(shape) -> list:
    """[(edge, [face, face])] for every edge of the shape with exactly two faces."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    try:
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as EdgeFaceMap
    except ImportError:                                   # newer OCP names the template instance
        from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap
    from OCP.TopoDS import TopoDS
    from build123d import Edge, Face
    m = EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    out = []
    for i in range(1, m.Extent() + 1):
        e = Edge(TopoDS.Edge(m.FindKey(i)))
        fl = [Face(TopoDS.Face(f)) for f in m.FindFromIndex(i)]
        uniq = []
        for f in fl:
            if not any(f.wrapped.IsSame(g.wrapped) for g in uniq):
                uniq.append(f)
        if len(uniq) == 2:
            out.append((e, uniq))
    return out


def _into_face(face, p, t, step) -> bool:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    q = p + step * t
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex()
    dss = BRepExtrema_DistShapeShape(v, face.wrapped)
    return dss.IsDone() and dss.Value() < step * 0.05


def concave_line_edges(shape, min_len: float = 0.0) -> list:
    """Straight edges where the two faces meet with material on the outside of the angle (an internal corner):
    [{"edge", "dir", "mid", "length", "faces", "angle_deg"}]. Convexity from the faces' normals at the edge: the
    edge is concave when the second face's normal leans toward the first face (n2 · t1 > 0, t1 the direction in
    face 1 away from the edge)."""
    out = []
    for e, (f1, f2) in _edge_faces(shape):
        if str(getattr(e.geom_type, "name", e.geom_type)).upper() != "LINE":
            continue
        L = float(e.length)
        if L <= min_len:
            continue
        a, b = _vec(e.position_at(0)), _vec(e.position_at(1))
        ed = unit(b - a)
        mid = (a + b) / 2
        from build123d import Vector
        try:
            n1 = _vec(f1.normal_at(Vector(*mid)))
            n2 = _vec(f2.normal_at(Vector(*mid)))
        except Exception:
            continue
        t1 = np.cross(n1, ed)
        if np.linalg.norm(t1) < 1e-9:
            continue
        t1 = unit(t1)
        step = max(1e-3, min(0.05, L * 0.01))
        if not _into_face(f1, mid, t1, step):
            t1 = -t1
            if not _into_face(f1, mid, t1, step):
                continue
        lean = float(n2 @ t1)
        if lean > math.sin(math.radians(1.0)):
            ang = 180.0 + math.degrees(math.asin(min(1.0, lean)))         # the angle through the material
            out.append({"edge": e, "dir": ed, "mid": mid, "length": L, "faces": (f1, f2), "angle_deg": ang})
    return out


def holes(shape) -> list:
    """Full cylindrical bores: concave cylinders whose faces (coaxial, same radius) close the circle.
    [{"d", "depth", "axis", "at", "faces"}]. A half-round slot end or a corner fillet is not a hole."""
    groups: list = []
    for f in shape.faces():
        cy = cylinder_of(f)
        if cy is None or not cy[3]:
            continue
        p0, d, r, _c, span = cy
        for g in groups:
            q = p0 - g["p0"]
            if abs(abs(d @ g["d"]) - 1) < 1e-6 and abs(r - g["r"]) < 1e-6 and np.linalg.norm(q - (q @ g["d"]) * g["d"]) < 1e-5:
                g["span"] += span
                g["faces"].append(f)
                break
        else:
            groups.append({"p0": p0, "d": d, "r": r, "span": span, "faces": [f]})
    out = []
    for g in groups:
        if g["span"] < 2 * math.pi - 1e-3:
            continue
        ts = []
        for f in g["faces"]:
            for v in f.vertices():
                ts.append(float((_vec(v) - g["p0"]) @ g["d"]))
        if not ts:
            continue
        t0, t1 = min(ts), max(ts)
        at = g["p0"] + g["d"] * (t0 + t1) / 2
        out.append({"d": 2 * g["r"], "depth": t1 - t0, "axis": g["d"], "at": at, "faces": g["faces"]})
    return out


def fillet_corners(shape) -> list:
    """Concave cylindrical faces that are not holes: blended internal corners. [{"r", "axis", "length", "at", "face"}]"""
    out = []
    for f in shape.faces():
        cy = cylinder_of(f)
        if cy is None or not cy[3] or cy[4] >= 2 * math.pi - 1e-3:
            continue
        p0, d, r, _c, span = cy
        ts = [float((_vec(v) - p0) @ d) for v in f.vertices()]
        L = (max(ts) - min(ts)) if ts else 0.0
        out.append({"r": r, "axis": d, "length": L, "at": _vec(f.center()), "face": f, "span": span})
    return out


def voids(shape) -> list:
    """Closed cavities inside the material: every shell of a solid after its outer one. [{"volume", "at", "bbox"}]"""
    from OCP.BRepClass3d import BRepClass3d
    from build123d import Shell, Solid
    out = []
    for s in shape.solids():
        try:
            outer = BRepClass3d.OuterShell_s(s.wrapped)
        except Exception:
            outer = None
        for sh in s.shells():
            if outer is not None and sh.wrapped.IsSame(outer):
                continue
            try:
                inner = Solid(Shell(sh.wrapped))
                vol = abs(float(inner.volume))
                c = _vec(inner.center())
            except Exception:
                vol, c = float("nan"), _vec(Shell(sh.wrapped).center())
            bb = Shell(sh.wrapped).bounding_box()
            out.append({"volume": vol, "at": c, "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]})
    return out
