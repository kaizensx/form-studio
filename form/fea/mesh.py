"""Tetrahedral meshes of a B-rep for the strength studies, made by Netgen (runs in the FEA engine's Python only).

    geo = load("part.step")            # or from_shape(a netgen.occ shape); several solids are glued where they touch
    m = generate(geo, h=4.0)           # a Mesh: vertices, tetrahedra, boundary triangles with their B-rep face
    m = generate(geo, h=4.0, field=(points, sizes))   # the same with a size field: h is restricted at each point

Netgen meshes the faces of the B-rep itself (its own OCCT reads the STEP), so every boundary vertex lies on the true
surface at every refinement, and its curvature sizing puts more elements on fillets and around holes. Netgen also
places the mid-side node of every edge on the geometry (its second-order mesh), so the solver's quadratic (10-node)
elements follow curved faces: a fillet is a curved surface in the model, not a row of flat facets
(form/fea/solve.py maps each element with its own quadratic shape functions, an isoparametric element).

Each boundary triangle carries the number of the B-rep face it lies on. A picked face (points on it, from the kernel)
is found on the mesh by the triangles nearest to those points: `faces_at`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

CURVATURE_SAFETY = 2.5        # Netgen: elements per radius of curvature (more on fillets and holes)
SEGMENTS_PER_EDGE = 1.2
GRADING = 0.35                # how fast the size may grow away from a fine region (0.1 slow, 1 fast)


class MeshError(RuntimeError):
    pass


@dataclass
class Geometry:
    geo: object                                  # netgen.occ.OCCGeometry
    bbox: np.ndarray                             # (2, 3)
    solids: int
    volume: float
    glued: bool = False

    @property
    def diag(self) -> float:
        return float(np.linalg.norm(self.bbox[1] - self.bbox[0]))


@dataclass
class Mesh:
    P: np.ndarray                                # (nv, 3) vertices, mm
    T: np.ndarray                                # (nt, 4) tetrahedra
    dom: np.ndarray                              # (nt,) solid number of each tetrahedron, from 0
    S: np.ndarray                                # (ns, 3) boundary triangles (outside faces and faces between solids)
    face: np.ndarray                             # (ns,) B-rep face number of each triangle, from 0
    h: float
    seconds: float = 0.0
    info: dict = field(default_factory=dict)
    edges: np.ndarray | None = None              # (ne, 2) vertex pairs (low, high) of every edge of the tetrahedra
    edge_mid: np.ndarray | None = None           # (ne, 3) the mid-side node of each, on the geometry where it is curved


def from_shape(shape) -> Geometry:
    """A netgen.occ shape (a solid, or several: glued where their faces touch, so the mesh is shared there)."""
    from netgen.occ import Glue, OCCGeometry
    solids = list(shape.solids)
    if not solids:
        raise MeshError("The shape has no solid to mesh (a surface or an open shell cannot carry a strength study).")
    glued = False
    if len(solids) > 1:
        shape = Glue(solids)
        glued = True
    bb = shape.bounding_box
    lo, hi = bb[0], bb[1]
    box = np.array([[lo.x, lo.y, lo.z], [hi.x, hi.y, hi.z]], dtype=float)
    return Geometry(OCCGeometry(shape), box, len(list(shape.solids)), float(sum(s.mass for s in shape.solids)), glued)


def load(step_path: str) -> Geometry:
    from netgen.occ import OCCGeometry
    try:
        g = OCCGeometry(str(step_path))
    except Exception as e:                       # noqa: BLE001 - Netgen raises its own types
        raise MeshError(f"Netgen could not read the STEP file: {e}") from e
    return from_shape(g.shape)


def solid_centres(g: Geometry) -> list:
    """Centre of mass and volume of each solid, in the order of the mesh's solid numbers."""
    out = []
    for s in g.geo.shape.solids:
        c = s.center
        out.append({"centre": [c.x, c.y, c.z], "volume": float(s.mass)})
    return out


def generate(g: Geometry, h: float, field=None, hmin: float = 0.0, curved: bool = True) -> Mesh:
    """Mesh at size h (mm). field = (points (n, 3), sizes (n,)): the size is restricted to sizes[i] at points[i].
    curved: also take the mid-side nodes of Netgen's second-order mesh, which lie on the geometry."""
    from netgen.meshing import MeshingParameters
    t0 = time.perf_counter()
    mp = MeshingParameters(maxh=float(h), minh=float(hmin), grading=GRADING, curvaturesafety=CURVATURE_SAFETY,
                           segmentsperedge=SEGMENTS_PER_EDGE, optsteps3d=3)
    if field is not None:
        pts, sizes = field
        for (x, y, z), s in zip(np.asarray(pts, float), np.asarray(sizes, float)):
            mp.RestrictH(float(x), float(y), float(z), float(max(s, hmin or 0.0)))
    try:
        m = g.geo.GenerateMesh(mp)
    except Exception as e:                       # noqa: BLE001
        raise MeshError(f"Netgen could not mesh the solid at {h:.3g} mm: {e}") from e
    if m.ne == 0:
        raise MeshError(f"Netgen made no tetrahedra at {h:.3g} mm (the solid may be open or self-intersecting).")
    P = np.array(m.Coordinates(), dtype=float)
    el = m.Elements3D().NumPy()
    T = np.array(el["nodes"][:, :4], dtype=np.int64) - 1
    dom = np.array(el["index"], dtype=np.int64) - 1
    se = m.Elements2D().NumPy()
    S = np.array(se["nodes"][:, :3], dtype=np.int64) - 1
    fd = np.array(se["index"], dtype=np.int64) - 1
    used = np.zeros(len(P), bool)
    used[T.ravel()] = True
    if not used.all():                           # points Netgen kept that no tetrahedron uses
        remap = np.cumsum(used) - 1
        P, T, S = P[used], remap[T], remap[S]
    out = Mesh(P, T, dom, S, fd, float(h), time.perf_counter() - t0)
    if curved:
        try:
            out.edges, out.edge_mid = _second_order(m, used, len(P))
        except Exception:                        # noqa: BLE001 - no second-order mesh: straight sides, said in the result
            out.edges = out.edge_mid = None
    out.seconds = time.perf_counter() - t0
    out.info = quality(out)
    out.info["curved"] = out.edge_mid is not None
    return out


# mid-side node k of Netgen's 10-node tetrahedron lies between these two of its corners
_NG_TET_MIDS = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _second_order(m, used: np.ndarray, nv: int):
    """Mid-side nodes of Netgen's second-order version of the mesh, placed on the geometry: (edges, positions).
    `used` and `nv`: which of the first-order points were kept, and how many."""
    n0 = len(used)
    m.SecondOrder()
    P2 = np.array(m.Coordinates(), dtype=float)
    T10 = np.array(m.Elements3D().NumPy()["nodes"][:, :10], dtype=np.int64) - 1
    if T10.shape[1] < 10 or (T10[:, 4:] < n0).any():
        raise MeshError("Netgen made no second-order mesh.")
    remap = np.cumsum(used) - 1
    a = np.concatenate([remap[T10[:, i]] for i, _ in _NG_TET_MIDS])
    b = np.concatenate([remap[T10[:, j]] for _, j in _NG_TET_MIDS])
    mid = np.concatenate([T10[:, 4 + k] for k in range(6)])
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    code, first = np.unique(lo * nv + hi, return_index=True)
    return np.column_stack([lo[first], hi[first]]), P2[mid[first]]


def _tet_edges(m: Mesh) -> np.ndarray:
    a, b, c, d = (m.P[m.T[:, i]] for i in range(4))
    return np.stack([np.linalg.norm(x - y, axis=1) for x, y in ((a, b), (a, c), (a, d), (b, c), (b, d), (c, d))])


def quality(m: Mesh) -> dict:
    a, b, c, d = (m.P[m.T[:, i]] for i in range(4))
    vol = np.abs(np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)) / 6.0
    edges = _tet_edges(m)
    lrms = np.sqrt((edges ** 2).mean(axis=0))
    q = 6 * np.sqrt(2) * vol / np.maximum(lrms ** 3, 1e-300)        # 1 for a regular tetrahedron
    return {"tets": int(len(m.T)), "vertices": int(len(m.P)), "volume": float(vol.sum()),
            "h_min": float(edges.min()), "h_mean": float(edges.mean()), "h_max": float(edges.max()),
            "quality_min": float(q.min()), "quality_mean": float(q.mean())}


def element_sizes(m: Mesh) -> np.ndarray:
    return _tet_edges(m).mean(axis=0)


# ---- picked faces ------------------------------------------------------------------------------------------------

def _closest_on_triangles(p, A, B, C):
    """Distance from point p to each triangle (A, B, C) (Ericson, Real-Time Collision Detection 5.1.5), vectorised."""
    ab, ac, ap = B - A, C - A, p - A
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - B
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - C
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) < 1e-300, 1.0, va + vb + vc)
    v, w = vb / den, vc / den
    q = A + ab * v[:, None] + ac * w[:, None]

    def ratio(num, d):
        return np.clip(num / np.where(d == 0, 1.0, d), 0, 1)
    t1, t2 = ratio(d1, d1 - d3), ratio(d2, d2 - d6)
    t3 = ratio(d4 - d3, (d4 - d3) + (d5 - d6))
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    q[m] = A[m] + ab[m] * t1[m, None]
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    q[m] = A[m] + ac[m] * t2[m, None]
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    q[m] = B[m] + (C[m] - B[m]) * t3[m, None]
    m = (d1 <= 0) & (d2 <= 0)
    q[m] = A[m]
    m = (d3 >= 0) & (d4 <= d3)
    q[m] = B[m]
    m = (d6 >= 0) & (d5 <= d6)
    q[m] = C[m]
    return np.linalg.norm(q - p, axis=1)


def face_areas(m: Mesh) -> np.ndarray:
    a, b, c = m.P[m.S[:, 0]], m.P[m.S[:, 1]], m.P[m.S[:, 2]]
    tri = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    return np.bincount(m.face, weights=tri, minlength=int(m.face.max()) + 1)


def faces_at(m: Mesh, ref: dict, diag: float) -> list:
    """The B-rep face numbers a picked face refers to. ref: {"samples": [[x, y, z], ...], "area": mm2 (optional)}:
    points on the face, from the kernel. Raises MeshError when no boundary triangle is near them, or when the face
    found has a different area than the picked one (the pick and the mesh are not the same geometry)."""
    pts = np.asarray(ref.get("samples") or [ref["at"]], dtype=float).reshape(-1, 3)
    A, B, C = m.P[m.S[:, 0]], m.P[m.S[:, 1]], m.P[m.S[:, 2]]
    size = np.sqrt(np.linalg.norm(np.cross(B - A, C - A), axis=1))
    votes = {}
    for p in pts:
        d = _closest_on_triangles(p, A, B, C)
        k = int(np.argmin(d))
        if d[k] > 0.35 * size[k] + 1e-4 * diag + 1e-6:
            continue
        votes[int(m.face[k])] = votes.get(int(m.face[k]), 0) + 1
    if not votes:
        raise MeshError(f"No face of the meshed solid is at the picked point {np.round(pts[0], 3).tolist()} "
                        "(pick a point on the part's surface, in design millimetres).")
    f = max(votes, key=votes.get)
    if ref.get("area"):
        got = float(face_areas(m)[f])
        if abs(got - float(ref["area"])) > 0.08 * float(ref["area"]) + 1e-9:
            raise MeshError(f"The face found on the mesh has {got:.4g} mm2; the picked face has {float(ref['area']):.4g} "
                            "mm2. The mesh and the pick do not describe the same face.")
    return [f]


# ---- the outside surface: outward normals, and the edges where two faces meet ---------------------------------------

def surface(m: Mesh) -> dict:
    """Per boundary triangle: "outside" (it belongs to one tetrahedron: not a face between two glued solids),
    "normal" (unit, pointing out of the tetrahedron that owns it), "owner" (that tetrahedron), "area"."""
    S, P = m.S, m.P
    n = int(P.shape[0])

    def code(k):
        return (k[:, 0] * n + k[:, 1]) * n + k[:, 2]
    tf = np.concatenate([m.T[:, [0, 1, 2]], m.T[:, [0, 1, 3]], m.T[:, [0, 2, 3]], m.T[:, [1, 2, 3]]])
    owner = np.tile(np.arange(len(m.T)), 4)
    tc, sc = code(np.sort(tf, axis=1)), code(np.sort(S, axis=1))
    order = np.argsort(tc, kind="stable")
    tcs = tc[order]
    lo, hi = np.searchsorted(tcs, sc, "left"), np.searchsorted(tcs, sc, "right")
    own = owner[order[np.minimum(lo, len(order) - 1)]]
    a, b, c = P[S[:, 0]], P[S[:, 1]], P[S[:, 2]]
    nrm = np.cross(b - a, c - a)
    area = np.linalg.norm(nrm, axis=1) / 2
    nrm /= np.maximum(2 * area, 1e-300)[:, None]
    cen = P[m.T[own]].mean(axis=1)
    nrm[np.einsum("ij,ij->i", nrm, cen - (a + b + c) / 3) > 0] *= -1
    return {"outside": (hi - lo) == 1, "normal": nrm, "owner": own, "area": area}


def face_edges(m: Mesh, surf: dict | None = None) -> dict:
    """Edges of the outside surface where two B-rep faces meet: {"v": (n, 2) vertex numbers, "f1", "f2": the faces,
    "reentrant": the solid's interior angle there is more than 180 degrees (an inside corner), "angle_deg": how far the
    surface normal turns across the edge (0 for faces that meet tangentially, as a fillet does)}."""
    surf = surf or surface(m)
    S, P, n = m.S, m.P, int(m.P.shape[0])
    idx = np.where(surf["outside"])[0]
    e = np.concatenate([S[idx][:, [0, 1]], S[idx][:, [1, 2]], S[idx][:, [2, 0]]])
    opp = np.concatenate([S[idx][:, 2], S[idx][:, 0], S[idx][:, 1]])
    tri = np.tile(idx, 3)
    ek = np.sort(e, axis=1)
    ec = ek[:, 0] * n + ek[:, 1]
    _, inv, cnt = np.unique(ec, return_inverse=True, return_counts=True)
    two = cnt[inv] == 2                          # an edge of a closed surface belongs to exactly two triangles
    o = np.argsort(inv[two], kind="stable")
    rows = np.where(two)[0][o]
    i1, i2 = rows[0::2], rows[1::2]
    t1, t2 = tri[i1], tri[i2]
    keep = m.face[t1] != m.face[t2]
    i1, t1, t2 = i1[keep], t1[keep], t2[keep]
    n1, n2 = surf["normal"][t1], surf["normal"][t2]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n1, n2), -1, 1)))
    mid = (P[ek[i1][:, 0]] + P[ek[i1][:, 1]]) / 2
    w = P[opp[i1]] - mid
    reentrant = np.einsum("ij,ij->i", n2, w) > 1e-9 * np.linalg.norm(w, axis=1)
    return {"v": ek[i1], "f1": m.face[t1], "f2": m.face[t2], "reentrant": reentrant, "angle_deg": ang}


def distance_to_segments(pts: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distance of each point to the nearest of the segments a[i]-b[i] (inf when there are none)."""
    out = np.full(len(pts), np.inf)
    if len(a) == 0 or len(pts) == 0:
        return out
    ab = b - a
    den = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-300)
    step = max(1, int(3e6 // max(1, len(a))))
    for s in range(0, len(pts), step):
        p = pts[s:s + step, None, :]
        t = np.clip(np.einsum("pij,ij->pi", p - a[None], ab) / den, 0, 1)
        q = a[None] + ab[None] * t[..., None]
        out[s:s + step] = np.linalg.norm(p - q, axis=2).min(axis=1)
    return out
