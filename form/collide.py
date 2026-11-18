"""Fast, bounded proximity between triangle meshes, and joint sweeps built on it. numpy and scipy only (no OCCT).

How a pair of parts is compared at one pose (``query``):
  1. Bounding boxes. Their gap is a lower bound on the distance; far apart means done.
  2. Triangle centroids in a k-d tree, each with the radius of its triangle. The nearest-centroid distance minus both
     radii is a lower bound on the surface distance; nothing within the cutoff means done.
  3. Only the triangle pairs that can be within the cutoff are compared exactly: point-triangle and segment-segment
     distances, and edge-through-triangle crossings. Long triangles are split first, so "near" stays local.
  4. Surfaces that do not come near can still be nested (one part inside the other): one vertex is tested by ray
     parity against the other part's closed mesh.
The answer is exact for the meshes. The meshes are the kernel's tessellation, within ``tol`` (the linear deflection)
of the B-rep, so a mesh distance d means a true distance in [d - tolA - tolB, d + tolA + tolB].

A sweep (``sweep``) moves a joint through its range: a coarse pass over the declared samples, then bisection where it
matters: between two clear samples until the clearance bound proves the interval free (the moving part cannot travel
further than its clearance between them), and between a clear and a colliding sample until the first contact is
located. Everything checks a deadline; what was not reached is reported as not checked, never as clear.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

EPS = 1e-9


class OutOfTime(Exception):
    """The deadline passed during a query; the caller reports what it had covered."""


# ---- meshes -----------------------------------------------------------------------------------------------
class Body:
    """One part's closed triangle mesh in its own frame, prepared for proximity queries."""

    def __init__(self, V, T, tol: float = 0.05, max_edge: float | None = None):
        from scipy.spatial import cKDTree
        V = np.asarray(V, np.float64).reshape(-1, 3)
        T = np.asarray(T, np.int64).reshape(-1, 3)
        a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        cr = np.cross(b - a, c - a)
        keep = np.linalg.norm(cr, axis=1) > 1e-14
        a, b, c, cr = a[keep], b[keep], c[keep], cr[keep]
        if len(a) and float(np.einsum("ij,ij->", a, cr)) < 0:     # signed volume < 0: inward normals, flip
            b, c = c, b
        self.tol = float(tol)
        self.V = V
        self.orig = (a, b, c)                    # the closed mesh, for ray parity
        lo, hi = (V.min(0), V.max(0)) if len(V) else (np.zeros(3), np.zeros(3))
        self.lo, self.hi = lo, hi
        diag = float(np.linalg.norm(hi - lo))
        self.max_edge = float(max_edge or min(5.0, max(1.0, diag / 40)))
        a, b, c = _split_long(a, b, c, self.max_edge)
        self.a, self.b, self.c = a, b, c
        self.C = (a + b + c) / 3
        self.r = np.sqrt(np.max(np.stack([((x - self.C) ** 2).sum(1) for x in (a, b, c)]), axis=0))
        n = np.cross(b - a, c - a)
        self.N = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
        self.rmax = float(self.r.max()) if len(self.r) else 0.0
        self.tlo = np.minimum(np.minimum(a, b), c)          # per-triangle bounding boxes
        self.thi = np.maximum(np.maximum(a, b), c)
        self.tree = cKDTree(self.C) if len(self.C) else None

    @property
    def n_tri(self) -> int:
        return len(self.a)

    def radius_about(self, M, axis, origin) -> float:
        """Largest distance of the mesh, placed by M, from a line (for the motion bound of a hinge)."""
        P = _xf(M, self.V)
        u = np.asarray(axis, float) / (np.linalg.norm(axis) or 1.0)
        d = P - np.asarray(origin, float)
        return float(np.sqrt(np.max((d ** 2).sum(1) - (d @ u) ** 2).clip(0))) if len(P) else 0.0


def _split_long(a, b, c, L, rounds: int = 14):
    """Longest-edge bisection until no edge is longer than L (the pieces need not be conforming)."""
    for _ in range(rounds):
        e0, e1, e2 = (((b - a) ** 2).sum(1), ((c - b) ** 2).sum(1), ((a - c) ** 2).sum(1))
        E = np.stack([e0, e1, e2], 1)
        k = E.argmax(1)
        big = E[np.arange(len(E)), k] > L * L
        if not big.any():
            break
        A, B, Cc, kk = a[big], b[big], c[big], k[big]
        # rotate each big triangle so its longest edge is (p, q), opposite vertex r
        p = np.where((kk == 0)[:, None], A, np.where((kk == 1)[:, None], B, Cc))
        q = np.where((kk == 0)[:, None], B, np.where((kk == 1)[:, None], Cc, A))
        r = np.where((kk == 0)[:, None], Cc, np.where((kk == 1)[:, None], A, B))
        m = (p + q) / 2
        keep = ~big
        a = np.concatenate([a[keep], p, m])
        b = np.concatenate([b[keep], m, q])
        c = np.concatenate([c[keep], r, r])
    return a, b, c


def _xf(M, P):
    return P @ M[:3, :3].T + M[:3, 3]


def _dot(u, v):
    return np.einsum("ij,ij->i", u, v)


# ---- primitives (vectorised) ------------------------------------------------------------------------------
def closest_on_triangle(p, a, b, c):
    """Closest point on triangle abc to p, row-wise (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    bp = p - b
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    cp = p - c
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        den = va + vb + vc
        den = np.where(np.abs(den) < 1e-300, 1e-300, den)
        out = a + ab * (vb / den)[:, None] + ac * (vc / den)[:, None]
        w = (d4 - d3) / np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-300, 1e-300, (d4 - d3) + (d5 - d6))
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        out = np.where(m[:, None], b + (c - b) * w[:, None], out)
        w = d2 / np.where(np.abs(d2 - d6) < 1e-300, 1e-300, d2 - d6)
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        out = np.where(m[:, None], a + ac * w[:, None], out)
        m = (d6 >= 0) & (d5 <= d6)
        out = np.where(m[:, None], c, out)
        v = d1 / np.where(np.abs(d1 - d3) < 1e-300, 1e-300, d1 - d3)
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        out = np.where(m[:, None], a + ab * v[:, None], out)
        m = (d3 >= 0) & (d4 <= d3)
        out = np.where(m[:, None], b, out)
        m = (d1 <= 0) & (d2 <= 0)
        out = np.where(m[:, None], a, out)
    return out


def closest_segments(p1, q1, p2, q2):
    """Closest points between segments p1q1 and p2q2, row-wise (Ericson 5.1.9). Segments are not degenerate."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    c, b = _dot(d1, r), _dot(d1, d2)
    den = a * e - b * b
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(den > 1e-12 * a * e, np.clip((b * f - c * e) / np.where(den == 0, 1, den), 0, 1), 0.0)
        t = (b * s + f) / e
        lo, hi = t < 0, t > 1
        s = np.where(lo, np.clip(-c / a, 0, 1), np.where(hi, np.clip((b - c) / a, 0, 1), s))
        t = np.clip(t, 0, 1)
    return p1 + d1 * s[:, None], p2 + d2 * t[:, None]


def edges_cross(p, q, a, b, c, n, eps=1e-7):
    """True where segment pq passes through triangle abc (unit normal n) from one side to the other, both ends
    more than eps from its plane (faces that only touch, or lie in one plane, do not count)."""
    dp, dq = _dot(p - a, n), _dot(q - a, n)
    hit = (dp * dq < 0) & (np.abs(dp) > eps) & (np.abs(dq) > eps)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = dp / np.where(hit, dp - dq, 1.0)
    x = p + (q - p) * t[:, None]
    s1 = _dot(np.cross(b - a, x - a), n)
    s2 = _dot(np.cross(c - b, x - b), n)
    s3 = _dot(np.cross(a - c, x - c), n)
    return hit & (s1 >= 0) & (s2 >= 0) & (s3 >= 0)


def _normal(a, b, c):
    n = np.cross(b - a, c - a)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)


def triangles_cross(A, B):
    """Row-wise: do triangle A (a, b, c) and triangle B pass through each other (an edge of one pierces the other)."""
    a1, b1, c1 = A
    a2, b2, c2 = B
    n1, n2 = _normal(a1, b1, c1), _normal(a2, b2, c2)
    cross = np.zeros(len(a1), bool)
    for p, q in ((a1, b1), (b1, c1), (c1, a1)):
        cross |= edges_cross(p, q, a2, b2, c2, n2)
    for p, q in ((a2, b2), (b2, c2), (c2, a2)):
        cross |= edges_cross(p, q, a1, b1, c1, n1)
    return cross


def triangle_distance(A, B):
    """Row-wise exact distance between triangles that do not cross, with the closest points (pa on A, pb on B)."""
    a1, b1, c1 = A
    a2, b2, c2 = B
    best = np.full(len(a1), np.inf)
    pa = np.zeros_like(a1)
    pb = np.zeros_like(a1)

    def take(x, y):
        d = np.linalg.norm(x - y, axis=1)
        m = d < best
        best[m] = d[m]
        pa[m] = x[m]
        pb[m] = y[m]

    for v in (a1, b1, c1):
        take(v, closest_on_triangle(v, a2, b2, c2))
    for v in (a2, b2, c2):
        take(closest_on_triangle(v, a1, b1, c1), v)
    for p, q in ((a1, b1), (b1, c1), (c1, a1)):
        for r, t in ((a2, b2), (b2, c2), (c2, a2)):
            x, y = closest_segments(p, q, r, t)
            take(x, y)
    return best, pa, pb


def triangle_pairs(A, B):
    """Exact distance between triangle pairs and whether they cross: (d, pa, pb, cross); d = 0 where they cross."""
    d, pa, pb = triangle_distance(A, B)
    cross = triangles_cross(A, B)
    d[cross] = 0.0
    return d, pa, pb, cross


def inside(body: Body, pts) -> np.ndarray:
    """Points strictly inside the body's closed mesh: ray parity, majority of three skewed rays."""
    a, b, c = body.orig
    pts = np.asarray(pts, float).reshape(-1, 3)
    if not len(a):
        return np.zeros(len(pts), bool)
    dirs = np.array([[0.5773502, 0.5773503, 0.5773501], [-0.267261, 0.534522, 0.801784], [0.707107, -0.408248, 0.577350]])
    e1, e2 = b - a, c - a
    votes = np.zeros(len(pts), int)
    for d in dirs:
        h = np.cross(np.broadcast_to(d, e2.shape), e2)
        det = _dot(e1, h)
        ok = np.abs(det) > 1e-14
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        for i, p in enumerate(pts):
            s = p - a
            u = _dot(s, h) * inv
            qv = np.cross(s, e1)
            v = (qv @ d) * inv
            t = _dot(e2, qv) * inv
            hits = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
            votes[i] += int(hits.sum()) % 2
    return votes >= 2


# ---- one pair at one pose ---------------------------------------------------------------------------------
@dataclass
class Prox:
    d: float                  # mesh distance if exact, else a lower bound (>= cutoff)
    exact: bool               # d is the exact mesh distance (it is within the cutoff)
    pa: list | None = None    # closest points, in B's frame
    pb: list | None = None
    cross: bool = False       # the surfaces pass through each other
    depth: float = 0.0        # deepest vertex found inside the other part (a lower bound on the penetration), mm
    nested: bool = False      # one part lies wholly inside the other
    box: tuple | None = None  # region of the crossing, B's frame
    pairs: int = 0            # triangle pairs compared exactly
    tlb: object = None        # per triangle of A: lower bound on its distance to B (float32), for the motion bound

    def state(self, tol: float) -> str:
        """far | gap | contact | overlap, with mesh tolerance tol (sum of both deflections)."""
        if self.nested or (self.cross and self.depth > tol):
            return "overlap"
        if self.cross or (self.exact and self.d <= 1e-6):
            return "contact"
        return "gap" if self.exact else "far"


def query(A: Body, B: Body, M, cutoff: float, deadline: float | None = None, chunk: int = 40000,
          max_pairs: int = 1_500_000) -> Prox:
    """Proximity of A (placed in B's frame by the 4x4 M) to B, exact below `cutoff` mm."""
    if A.tree is None or B.tree is None:
        return Prox(math.inf, False)
    from scipy.spatial import cKDTree
    VA = _xf(M, A.V)
    lo, hi = VA.min(0), VA.max(0)
    gap = np.maximum(0, np.maximum(B.lo - hi, lo - B.hi))
    box_gap = float(np.linalg.norm(gap))
    if box_gap > cutoff:
        return Prox(box_gap, False)
    CA = _xf(M, A.C)
    far = max(20.0, 4 * cutoff)                                # beyond this, "at least this far" is enough
    dist, _ = B.tree.query(CA, k=1, distance_upper_bound=far, workers=-1)
    dist = np.where(np.isfinite(dist), dist, far)
    tlb = np.maximum(0.0, dist - A.r - B.rmax).astype(np.float32)   # each A triangle is at least this far from B
    lb = float(tlb.min())
    ub = float(dist.min())                                     # centroids lie on the mesh: the distance is at most this
    cut = min(cutoff, ub)
    near = np.nonzero(dist <= cut + A.r + B.rmax)[0]
    if lb > cutoff or not len(near):
        return _nest(A, B, M, VA, Prox(max(lb, cutoff, box_gap), False, tlb=tlb))
    reach = cut + A.rmax + B.rmax
    sub = cKDTree(CA[near])
    sp = sub.sparse_distance_matrix(B.tree, reach, output_type="ndarray")
    ii, jj, dc = near[sp["i"]], sp["j"].astype(np.int64), sp["v"]
    plb = dc - A.r[ii] - B.r[jj]                               # per-pair lower bound: bounding spheres ...
    keep = plb <= cut
    ii, jj, plb = ii[keep], jj[keep], plb[keep]
    if len(ii):                                                # ... and bounding boxes, whichever is tighter
        ua, inv = np.unique(ii, return_inverse=True)
        ta, tb, tc = _xf(M, A.a[ua]), _xf(M, A.b[ua]), _xf(M, A.c[ua])
        alo, ahi = np.minimum(np.minimum(ta, tb), tc)[inv], np.maximum(np.maximum(ta, tb), tc)[inv]
        g = np.maximum(0, np.maximum(B.tlo[jj] - ahi, alo - B.thi[jj]))
        plb = np.maximum(plb, np.sqrt((g * g).sum(1)))
        keep = plb <= cut
        ii, jj, plb = ii[keep], jj[keep], plb[keep]
    if not len(ii):
        return _nest(A, B, M, VA, Prox(max(lb, cutoff), False, tlb=tlb))
    capped = len(ii) > max_pairs
    rest_lb = math.inf                                         # lower bound of the pairs left out (capped)
    if capped:
        o = np.argpartition(plb, max_pairs)
        rest_lb = float(plb[o[max_pairs]])
        o = o[:max_pairs]
        o = o[np.argsort(plb[o], kind="stable")]
    else:
        o = np.argsort(plb, kind="stable")
    ii, jj, plb = ii[o], jj[o], plb[o]
    tri = lambda e: ((_xf(M, A.a[ii[e]]), _xf(M, A.b[ii[e]]), _xf(M, A.c[ii[e]])), (B.a[jj[e]], B.b[jj[e]], B.c[jj[e]]))

    # 1. crossings: only triangles whose bounding spheres overlap can cross
    n0 = int(np.searchsorted(plb, 0.0, side="right"))
    crossed = np.zeros(len(ii), bool)
    for s in range(0, n0, chunk):
        if deadline is not None and time.perf_counter() > deadline:
            raise OutOfTime()
        e = slice(s, min(s + chunk, n0))
        crossed[e] = triangles_cross(*tri(e))
    out = Prox(0.0, True, pairs=int(len(ii)), tlb=tlb)
    if crossed.any():
        out.cross = True
        k = np.nonzero(crossed)[0]
        (a1, b1, c1), _ = tri(k)
        P = np.concatenate([a1, b1, c1])
        out.box = (P.min(0).tolist(), P.max(0).tolist())
        out.pa = out.pb = P.mean(0).tolist()
        out.depth = _depth(A, B, M, ii[k], jj[k])
        out.tlb = np.zeros(len(tlb), np.float32)
        return out
    # 2. distance: in order of the lower bound, stopping once no remaining pair can be closer
    best, pa, pb = math.inf, None, None
    s, step = 0, 2000                                          # small first chunks: the early stop comes sooner
    while s < len(ii):
        if plb[s] >= best:
            break
        if deadline is not None and time.perf_counter() > deadline:
            raise OutOfTime()
        e = slice(s, s + step)
        s, step = s + step, min(chunk, step * 2)
        d, x, y = triangle_distance(*tri(e))
        k = int(np.argmin(d))
        if d[k] < best:
            best, pa, pb = float(d[k]), x[k].tolist(), y[k].tolist()
    if best <= cutoff:
        out.d, out.exact, out.pa, out.pb = best, best <= rest_lb, pa, pb
        return out
    return _nest(A, B, M, VA, Prox(max(cutoff, lb), False, pairs=int(len(ii)), tlb=tlb))


def _nest(A, B, M, VA, out: Prox) -> Prox:
    """Surfaces apart: the parts are either separate or one is nested in the other. Test one vertex each way."""
    if not len(VA) or not len(B.V):
        return out
    lo, hi = VA.min(0), VA.max(0)
    if np.all(VA[0] >= B.lo) and np.all(VA[0] <= B.hi) and inside(B, VA[:1])[0]:
        out.nested, out.box, out.d, out.tlb = True, (lo.tolist(), hi.tolist()), 0.0, None
    elif np.all(B.V[0] >= lo) and np.all(B.V[0] <= hi):
        Minv = np.linalg.inv(M)
        if inside(A, _xf(Minv, B.V[:1]))[0]:
            out.nested, out.box, out.d, out.tlb = True, (B.lo.tolist(), B.hi.tolist()), 0.0, None
    return out


def surface_distance(body: Body, pts) -> np.ndarray:
    """Exact distance from points (body frame) to the body's mesh surface."""
    pts = np.asarray(pts, float).reshape(-1, 3)
    out = np.empty(len(pts))
    if body.tree is None:
        out[:] = np.inf
        return out
    d0, _ = body.tree.query(pts, k=1)
    for i, p in enumerate(pts):
        r = d0[i] + 2 * body.rmax                       # every triangle closer than d0 has its centroid within this
        js = np.asarray(body.tree.query_ball_point(p, r), int)
        P = np.broadcast_to(p, (len(js), 3))
        q = closest_on_triangle(P, body.a[js], body.b[js], body.c[js])
        out[i] = float(np.min(np.linalg.norm(P - q, axis=1)))
    return out


def _depth(A, B, M, ii, jj, n: int = 48) -> float:
    """Penetration found at the crossing: the deepest of up to n vertices of the crossing triangles that lie inside the
    other part (ray parity on its closed mesh), measured to its surface. A true lower bound on the penetration depth."""
    best = 0.0
    Minv = np.linalg.inv(M)
    for P, other in ((_xf(M, np.concatenate([A.a[ii], A.b[ii], A.c[ii]])), B),
                     (_xf(Minv, np.concatenate([B.a[jj], B.b[jj], B.c[jj]])), A)):
        P = np.unique(np.round(P, 9), axis=0)
        if len(P) > n:
            P = P[np.linspace(0, len(P) - 1, n).astype(int)]
        ins = inside(other, P)
        if ins.any():
            best = max(best, float(surface_distance(other, P[ins]).max()))
    return best


# ---- sweeps -----------------------------------------------------------------------------------------------
@dataclass
class Sample:
    value: float
    state: str                # clear | close | contact | overlap | skipped
    clearance: float          # smallest mesh distance over the pairs (exact below the cutoff, else a lower bound)
    exact: bool
    depth: float = 0.0
    pair: tuple | None = None # the pair that decided it (closest, or deepest overlap)
    pa: list | None = None
    pb: list | None = None
    box: tuple | None = None
    lbs: dict = field(default_factory=dict)  # pair -> lower bound on the true distance (for the interval bound)
    refined: bool = False     # added by bisection, not one of the declared samples


@dataclass
class SweepResult:
    samples: list
    lo: float
    hi: float
    covered: tuple | None     # contiguous range of the coarse pass that was checked
    partial: bool             # the deadline stopped it before the coarse pass finished
    proven: list              # [(a, b)] intervals proven free between samples (continuous bound)
    unproven: list            # [(a, b)] intervals between clear samples that could not be proven in time or resolution
    contact_from: float | None  # first value with contact or overlap, located by bisection
    contact_res: float | None
    evaluated: int
    seconds: float


def sweep(bodies: dict, frames, pairs: list, values: list, bound, *, tol: float, warn: float, cutoff: float,
          deadline: float, refine: bool = True, min_step: float = 0.5, max_evals: int = 240, on_sample=None,
          hopeless: float = 16.0) -> SweepResult:
    """Check `pairs` of bodies at joint values.

    frames(v) -> {body id: 4x4 placing it (print frame -> world)}; bound(body id, v1, v2) -> how far each triangle of
    that moving body can travel between v1 and v2 (mm; an array per triangle, or one number); tol = sum of both meshes' deflections (worst pair); values = coarse samples
    in the order to check them. The interval between two clear samples is proven free when, for every pair, the true
    clearance at its ends (mesh lower bound minus tol) adds up to more than its travel, triangle by triangle."""
    t0 = time.perf_counter()
    done: dict[float, Sample] = {}
    n_eval = 0

    def evaluate(v, refined=False):
        nonlocal n_eval
        F = frames(v)
        s = Sample(v, "clear", math.inf, True, refined=refined)
        for a, b in pairs:
            M = np.linalg.inv(F[b]) @ F[a]
            r = query(bodies[a], bodies[b], M, cutoff, deadline)
            st = r.state(tol)
            if st in ("gap", "far"):                 # per triangle of the moving body where known, else one number
                s.lbs[(a, b)] = (np.maximum(r.tlb, r.d) - tol).clip(0) if r.tlb is not None else max(0.0, r.d - tol)
            else:
                s.lbs[(a, b)] = 0.0
            W = F[b]
            rank = {"far": 0, "gap": 1, "contact": 2, "overlap": 3}
            cur = {"clear": 0, "close": 1, "contact": 2, "overlap": 3}[s.state]
            if st == "overlap" and (s.state != "overlap" or r.depth > s.depth or r.nested):
                s.state, s.depth, s.pair = "overlap", (math.inf if r.nested else r.depth), (a, b)
                s.box = tuple(_xf(W, np.array(x)[None])[0].tolist() for x in r.box) if r.box else None
                s.clearance, s.exact = 0.0, True
            elif rank[st] == 2 and cur < 2:
                s.state, s.pair, s.clearance, s.exact = "contact", (a, b), 0.0, True
                s.box = tuple(_xf(W, np.array(x)[None])[0].tolist() for x in r.box) if r.box else None
                if r.pa:
                    s.pa, s.pb = _xf(W, np.array([r.pa]))[0].tolist(), _xf(W, np.array([r.pb]))[0].tolist()
            elif cur < 2 and r.d < s.clearance:
                s.clearance, s.exact, s.pair = r.d, r.exact, (a, b)
                if r.pa:
                    s.pa, s.pb = _xf(W, np.array([r.pa]))[0].tolist(), _xf(W, np.array([r.pb]))[0].tolist()
                if r.exact and r.d < warn + tol:
                    s.state = "close"
        n_eval += 1
        done[v] = s
        if on_sample:
            on_sample(s)
        return s

    coarse_done, partial = [], False
    for v in values:
        if time.perf_counter() > deadline:
            partial = True
            break
        try:
            evaluate(v)
        except OutOfTime:
            partial = True
            break
        coarse_done.append(v)
    covered = (min(coarse_done), max(coarse_done)) if coarse_done else None

    proven, unproven = [], []
    def hit(s): return s.state == "overlap"
    def touch(s): return s.state in ("contact", "overlap")

    if refine and len(coarse_done) > 1:
        grid = sorted(coarse_done)
        queue = [(grid[i], grid[i + 1]) for i in range(len(grid) - 1)]
        while queue:
            queue.sort(key=lambda ab: -(ab[1] - ab[0]))
            a, b = queue.pop(0)
            sa, sb = done[a], done[b]
            if touch(sa) and touch(sb):
                continue
            if not touch(sa) and not touch(sb):
                need = 0.0                             # how many times too far the parts could travel for a proof
                for p in pairs:
                    lbsum = np.asarray(sa.lbs.get(p, 0) + sb.lbs.get(p, 0), float)
                    need = max(need, float(np.max(np.asarray(bound(p[0], a, b), float) / np.maximum(lbsum, 1e-9))))
                if need < 1:
                    proven.append((a, b))
                    continue
                if need > hopeless:                    # a tight gap all along (a lid in its groove): halving will not prove it
                    unproven.append((a, b))
                    continue
            if b - a <= min_step or n_eval >= max_evals or time.perf_counter() > deadline:
                if not touch(sa) and not touch(sb):
                    unproven.append((a, b))
                continue
            m = (a + b) / 2
            try:
                evaluate(m, refined=True)
            except OutOfTime:
                queue.append((a, b))
                break
            queue += [(a, m), (m, b)]
        for a, b in queue:                             # what time left unrefined is sampled only, never "free"
            if not (touch(done[a]) or touch(done[b])):
                unproven.append((a, b))
    elif len(coarse_done) > 1:
        grid = sorted(coarse_done)
        unproven = [(grid[i], grid[i + 1]) for i in range(len(grid) - 1) if not (touch(done[grid[i]]) or touch(done[grid[i + 1]]))]
    # first contact: the edge, nearest the rest position, of a run of touching samples that contains an overlap
    vals = sorted(done)
    contact_from, res = None, None
    runs, cur = [], []
    for v in vals:
        if touch(done[v]):
            cur.append(v)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for run in runs:
        if not any(hit(done[v]) for v in run):
            continue
        edge = run[0] if run[0] >= 0 or run[-1] > 0 else run[-1]
        if run[0] < 0 < run[-1]:
            edge = 0.0 if 0.0 in done else run[0]
        i = vals.index(edge)
        nb = vals[i - 1] if edge == run[0] and i > 0 else (vals[i + 1] if edge == run[-1] and i + 1 < len(vals) else None)
        if contact_from is None or abs(edge) < abs(contact_from):
            contact_from, res = edge, (abs(edge - nb) if nb is not None else None)
    samples = [done[v] for v in sorted(done)]
    return SweepResult(samples, min(values) if values else 0.0, max(values) if values else 0.0, covered, partial,
                       _merge(proven), _merge(unproven), contact_from, res, n_eval, time.perf_counter() - t0)


def travel(body: Body, M, kind: str, axis, origin=(0.0, 0.0, 0.0)):
    """bound(v1, v2) for one moving body placed by M at the joint's 0: per-triangle travel (mm) between two values."""
    if kind == "slide":
        return lambda v1, v2: abs(v2 - v1)
    u = np.asarray(axis, float) / (np.linalg.norm(axis) or 1.0)
    d = _xf(M, body.C) - np.asarray(origin, float)
    rad = np.sqrt(((d ** 2).sum(1) - (d @ u) ** 2).clip(0)) + body.r        # farthest point of each triangle from the axis
    return lambda v1, v2: (2 * rad * math.sin(math.radians(abs(v2 - v1)) / 2)).astype(np.float32)


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and abs(out[-1][1] - a) < 1e-9:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out
