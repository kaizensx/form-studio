"""Subdivision-surface cages to exact NURBS solids: the organic route from a quad cage to a STEP solid.

Two kinds of cage, one idea: a coarse quad net whose smooth limit surface is the part's skin, edited by moving the
net's points (directly, or through named handles that are a design's parameters).

* An open **grid cage** (nu x nv points, a disk-like skin: a helmet, a mask, a sculpted shell) is evaluated as a
  clamped uniform bicubic B-spline: the Catmull-Clark limit inside, its border pinned to the cage's border. One grid is
  one exact B-spline surface, C2 everywhere inside (smoother than G1). A shell is two grids, the skin and its inside
  (the skin offset by the wall), joined at the rim by ruled faces: a closed solid of six faces.
* A **quad cage** of any genus, closed or open, with creases (a character prop, a sculpted grip, a lid with a sharp
  rim) is subdivided by Catmull-Clark and turned into one bicubic Bezier patch per quad with Loop and Schaefer's
  approximation (ACC, 2008), generalised to creases and borders: exact where the net is regular (every patch whose
  corners are regular is the limit surface itself), and at an extraordinary vertex (not four quads round it) the edge
  points round it are put in one tangent plane, so the skin is G1 at the vertex and within a measured angle along the
  patch borders next to it (seam_angles() reports the worst). Infinitely sharp creases are C0 borders carrying the
  crease's exact B-spline; semi-sharp ones are resolved by subdivision levels first; open borders follow the B-spline
  boundary rules and are capped or thickened. Blocks of regular patches are merged into one multi-span B-spline face
  each; the faces are sewn into a closed OCCT solid. form.craft.subd_report measures the result against the true limit
  surface (deviation in mm, seams, BRepCheck, STEP round trip): nothing at an extraordinary vertex is called exact.

Why this route (evaluated against OpenSubdiv bindings, Blender headless and OCCT plate surfaces): it is plain numpy and
scipy plus the OCCT that build123d already ships, so it installs and packages the same way on macOS, Windows and Linux.
OpenSubdiv has no maintained Python wheels; Blender is optional (renders and, when present, its QuadriFlow remesher)
and never required to build a part; OCCT plate surfaces fill holes but give no editable cage.

Fitting (fit_grid, fit_cage) is linear least squares: every point of the limit surface is a fixed linear combination of
cage points (a B-spline basis, or the ACC stencil times Bernstein weights), so a cage that best matches a set of target
points (a scanned or sculpted mesh) comes from one sparse solve, refined by moving each target's (u, v) to its closest
point on the surface and solving again.

    from form.craft import subd
    C = subd.dome_grid(270, 215, 165, n=12)                        # a grid cage
    C = subd.apply_handles(C, HANDLES, v)                          # named handles moved by parameters
    shell = subd.shell_solid(C, wall=3)                            # outer skin + inside + rim, one closed solid

    cage = subd.Cage(V, quads, levels=1, creases=edges, regions={"lid": faces})
    body = cage.solid()                                            # exact B-spline blocks + measured ACC patches
    at, axis = cage.region_frame("lid")                            # where a magnet pair goes

form.craft.subd needs numpy and scipy for cages and fitting; OCCT (the kernel worker) only for the *_face / *_solid
builders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ._common import need, note

DEG = 3


# ── B-spline grids (numpy / scipy) ──────────────────────────────────────────────────────────────────────────────

def knots(n: int, k: int = DEG) -> np.ndarray:
    """Clamped uniform knot vector on [0, 1] for n control points."""
    need(n > k, f"subd: a grid needs at least {k + 1} points a side", "Use a finer cage.", ["cage"])
    inner = np.linspace(0.0, 1.0, n - k + 1)
    return np.r_[[0.0] * k, inner, [1.0] * k]


def basis(x, n: int, k: int = DEG):
    """Sparse B-spline basis matrix (len(x) x n) on the clamped uniform knots."""
    from scipy.interpolate import BSpline
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return BSpline.design_matrix(x, knots(n, k), k).tocsr()


def _rowkron(A, B):
    """Row-wise Kronecker product of two sparse matrices with the same number of rows (tensor-product basis)."""
    import scipy.sparse as sp
    A, B = A.tocsr(), B.tocsr()
    rows, cols, vals = [], [], []
    nb = B.shape[1]
    for r in range(A.shape[0]):
        a0, a1 = A.indptr[r], A.indptr[r + 1]
        b0, b1 = B.indptr[r], B.indptr[r + 1]
        ai, av = A.indices[a0:a1], A.data[a0:a1]
        bi, bv = B.indices[b0:b1], B.data[b0:b1]
        c = (ai[:, None] * nb + bi[None, :]).ravel()
        rows.append(np.full(c.size, r))
        cols.append(c)
        vals.append((av[:, None] * bv[None, :]).ravel())
    return sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                         shape=(A.shape[0], A.shape[1] * nb))


def tensor_basis(u, v, nu: int, nv: int):
    """Sparse (len(u) x nu*nv) basis: row i evaluates the grid surface at (u[i], v[i]); columns are C.reshape(-1, 3)."""
    Bu, Bv = basis(u, nu), basis(v, nv)
    # fast path: each row of a cubic basis has at most 4 non-zeros, so the product has at most 16
    Bu, Bv = Bu.tocsr(), Bv.tocsr()
    n = len(u)
    ku = np.diff(Bu.indptr)
    kv = np.diff(Bv.indptr)
    if np.all(ku == ku[0]) and np.all(kv == kv[0]) and n:
        a, b = ku[0], kv[0]
        ai = Bu.indices.reshape(n, a)
        av = Bu.data.reshape(n, a)
        bi = Bv.indices.reshape(n, b)
        bv = Bv.data.reshape(n, b)
        cols = (ai[:, :, None] * nv + bi[:, None, :]).reshape(n, a * b)
        vals = (av[:, :, None] * bv[:, None, :]).reshape(n, a * b)
        import scipy.sparse as sp
        return sp.csr_matrix((vals.ravel(), cols.ravel(), np.arange(0, n * a * b + 1, a * b)), shape=(n, nu * nv))
    return _rowkron(Bu, Bv)


def grid_eval(C: np.ndarray, u, v) -> np.ndarray:
    """Points of the grid surface at parameter pairs (u[i], v[i])."""
    nu, nv = C.shape[:2]
    return tensor_basis(u, v, nu, nv) @ C.reshape(-1, 3)


def grid_sample(C: np.ndarray, su: int, sv: int) -> np.ndarray:
    """The surface on an su x sv parameter grid: (su, sv, 3)."""
    nu, nv = C.shape[:2]
    Bu = basis(np.linspace(0, 1, su), nu).toarray()
    Bv = basis(np.linspace(0, 1, sv), nv).toarray()
    return np.einsum("ia,abk,jb->ijk", Bu, C, Bv)


def grid_normals(S: np.ndarray, outward_hint: np.ndarray | None = None) -> np.ndarray:
    """Unit normals of a sampled grid surface (su, sv, 3) by central differences (one-sided at the border)."""
    Su = np.gradient(S, axis=0)
    Sv = np.gradient(S, axis=1)
    N = np.cross(Su, Sv)
    L = np.linalg.norm(N, axis=2, keepdims=True)
    N = N / np.maximum(L, 1e-12)
    if outward_hint is not None:
        c = S.reshape(-1, 3).mean(0)
        if np.mean(np.sum((S - c) * N, axis=2)) < 0:
            N = -N
    return N


def _smooth_operator(nu: int, nv: int):
    """Second differences of the control net in both directions (a thin-plate-like bending penalty)."""
    import scipy.sparse as sp

    def d2(n):
        if n < 3:
            return sp.csr_matrix((0, n))
        return sp.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n))
    Iu, Iv = sp.identity(nu), sp.identity(nv)
    return sp.vstack([sp.kron(d2(nu), Iv), sp.kron(Iu, d2(nv))]).tocsr()


def fit_grid(P: np.ndarray, u, v, nu: int, nv: int, smooth: float = 1e-4, weights=None, pin=None) -> np.ndarray:
    """Least-squares grid cage (nu, nv, 3) whose surface passes nearest the points P at parameters (u, v).
    smooth: bending penalty relative to the data term; pin: {(i, j): xyz} control points held where they are."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    A = tensor_basis(u, v, nu, nv)
    w = np.ones(len(P)) if weights is None else np.asarray(weights, float)
    W = sp.diags(w)
    D = _smooth_operator(nu, nv)
    lam = smooth * float(w.sum()) / max(D.shape[0], 1)
    N = (A.T @ W @ A + lam * (D.T @ D)).tocsc()
    rhs = A.T @ (w[:, None] * P)
    if pin:
        big = 1e8
        for (i, j), xyz in pin.items():
            k = i * nv + j
            N[k, k] += big
            rhs[k] += big * np.asarray(xyz, float)
    N = N + sp.identity(N.shape[0]) * 1e-10 * float(w.sum())
    lu = spl.splu(N.tocsc())
    C = np.column_stack([lu.solve(rhs[:, d]) for d in range(3)])
    return C.reshape(nu, nv, 3)


def correct_params(C: np.ndarray, P: np.ndarray, u, v, iters: int = 2):
    """Move each point's (u, v) to its closest point on the surface (Gauss-Newton), so a refit measures true distance."""
    u, v = np.asarray(u, float).copy(), np.asarray(v, float).copy()
    h = 1e-5
    for _ in range(iters):
        S = grid_eval(C, u, v)
        Su = (grid_eval(C, np.clip(u + h, 0, 1), v) - grid_eval(C, np.clip(u - h, 0, 1), v)) / (
            np.clip(u + h, 0, 1) - np.clip(u - h, 0, 1))[:, None]
        Sv = (grid_eval(C, u, np.clip(v + h, 0, 1)) - grid_eval(C, u, np.clip(v - h, 0, 1))) / (
            np.clip(v + h, 0, 1) - np.clip(v - h, 0, 1))[:, None]
        r = P - S
        a, b, c = (Su * Su).sum(1), (Su * Sv).sum(1), (Sv * Sv).sum(1)
        e, f = (Su * r).sum(1), (Sv * r).sum(1)
        det = a * c - b * b
        ok = np.abs(det) > 1e-18
        du = np.where(ok, (c * e - b * f) / np.where(ok, det, 1), 0)
        dv = np.where(ok, (a * f - b * e) / np.where(ok, det, 1), 0)
        u = np.clip(u + np.clip(du, -0.05, 0.05), 0, 1)
        v = np.clip(v + np.clip(dv, -0.05, 0.05), 0, 1)
    return u, v


def fit_grid_refined(P, u, v, nu: int, nv: int, rounds: int = 3, smooth: float = 1e-4, pin=None):
    """fit_grid, then parameter correction and refit, `rounds` times. Returns (C, u, v, distances)."""
    C = fit_grid(P, u, v, nu, nv, smooth, pin=pin)
    for _ in range(rounds):
        u, v = correct_params(C, P, u, v)
        C = fit_grid(P, u, v, nu, nv, smooth, pin=pin)
    u, v = correct_params(C, P, u, v, iters=2)
    d = np.linalg.norm(grid_eval(C, u, v) - P, axis=1)
    return C, u, v, d


def offset_grid(C: np.ndarray, d: float, su: int | None = None, sv: int | None = None, outward: bool = True) -> np.ndarray:
    """A grid cage for the surface offset by d along its normal (negative: inward), fitted on the same knots.
    Exact to the fit (well under 0.05 mm when the radius of curvature is several times |d|)."""
    nu, nv = C.shape[:2]
    su, sv = su or nu * 4, sv or nv * 4
    S = grid_sample(C, su, sv)
    N = grid_normals(S, outward_hint=np.zeros(3) if outward else None)
    T = S + d * N
    uu, vv = np.meshgrid(np.linspace(0, 1, su), np.linspace(0, 1, sv), indexing="ij")
    return fit_grid(T.reshape(-1, 3), uu.ravel(), vv.ravel(), nu, nv, smooth=1e-6)


# ── handles: named, smooth deformations of a cage (a design's parameters) ─────────────────────────────────────────

@dataclass(frozen=True)
class Handle:
    """Moves the cage points near `center` (within `radius`, smoothly) by value mm along `direction`, or along the
    cage's own normal there when direction is "normal". `scale` handles instead scale the cage about center by
    (1 + value/100) along direction's axes (a percentage)."""
    name: str
    label: str
    center: tuple
    radius: float
    direction: tuple | str = "normal"
    default: float = 0.0
    lo: float = -20.0
    hi: float = 20.0
    step: float = 0.5
    unit: str = "mm"
    doc: str = ""
    kind: str = "move"           # move | scale

    def param(self, feature: str = "", group: str = "form"):
        from ..recipes.base import Param
        return Param(self.name, self.label, self.default, self.lo, self.hi, self.step, self.unit, group, feature,
                     self.doc or f"Cage handle: moves the surface near ({self.center[0]:g}, {self.center[1]:g}, "
                                 f"{self.center[2]:g}) by this much.")


def _falloff(d: np.ndarray, r: float) -> np.ndarray:
    x = np.clip(d / max(r, 1e-9), 0, 1)
    return (1 - x * x) ** 3                     # smooth (C2) bump, 1 at the centre, 0 at the radius


def cage_normals(C: np.ndarray) -> np.ndarray:
    """Normals at a grid cage's points (outward from its centroid)."""
    return grid_normals(C, outward_hint=np.zeros(3))


def apply_handles(C: np.ndarray, handles, values: dict) -> np.ndarray:
    """The cage with every handle moved to its value (values[h.name], default h.default). Works on grid cages
    (nu, nv, 3) and on point lists (n, 3)."""
    X = np.array(C, dtype=np.float64)
    flat = X.reshape(-1, 3)
    N = cage_normals(X).reshape(-1, 3) if X.ndim == 3 else None
    for h in handles:
        val = float(values.get(h.name, h.default))
        if abs(val) < 1e-12:
            continue
        c = np.asarray(h.center, float)
        w = _falloff(np.linalg.norm(flat - c, axis=1), h.radius)
        if h.kind == "scale":
            ax = np.asarray(h.direction, float)
            flat += w[:, None] * (flat - c) * ax[None, :] * (val / 100.0)
        elif isinstance(h.direction, str):
            need(N is not None, "subd: a 'normal' handle needs a grid cage", "Give the handle a direction.", [h.name])
            flat += w[:, None] * N * val
        else:
            dv = np.asarray(h.direction, float)
            flat += w[:, None] * (dv / (np.linalg.norm(dv) or 1)) * val
    return flat.reshape(X.shape)


# ── built-in grid cages ───────────────────────────────────────────────────────────────────────────────────────────

def square_to_disk(s: np.ndarray, t: np.ndarray):
    """Map the square [-1, 1]^2 onto the unit disk without folding (Shirley-Chiu concentric map, smoothed)."""
    x = s * np.sqrt(np.maximum(0, 1 - t * t / 2))
    y = t * np.sqrt(np.maximum(0, 1 - s * s / 2))
    return x, y


def dome_grid(length: float, width: float, height: float, n: int = 12, rim=None, crown_back: float = 0.0,
              squash: float = 2.2) -> np.ndarray:
    """A grid cage (n, n, 3) of a dome or helmet skin: the square grid is mapped onto a disk, then onto a
    superellipsoid cap length x width x height above z = 0 (x forward). rim(theta) -> z of the lower edge at the azimuth
    theta (radians, 0 = front), default 0 all round. The cage's border is that edge; its middle is the crown."""
    s = np.linspace(-1, 1, n)
    S, T = np.meshgrid(s, s, indexing="ij")
    X, Y = square_to_disk(S, T)
    r = np.clip(np.hypot(X, Y), 0, 1)
    th = np.arctan2(Y, X)
    a, b = length / 2, width / 2
    # polar angle from the crown: r = 1 at the rim
    phi = r * (math.pi / 2)
    cs, sn = np.cos(th), np.sin(th)
    e = 2.0 / squash
    sx = np.sign(cs) * np.abs(cs) ** e
    sy = np.sign(sn) * np.abs(sn) ** e
    z0 = np.zeros_like(th) if rim is None else np.vectorize(rim)(th)
    zc = height
    Z = z0 + (zc - z0) * np.cos(phi)
    rad = np.sin(phi)
    Xw = a * rad * sx + crown_back * (1 - rad) * (-a)
    Yw = b * rad * sy
    return np.stack([Xw, Yw, Z], axis=2)


DISK_R = 0.42      # a skin's border: the circle of this radius about (0.5, 0.5) of its cage's parameter square


def dome_point(length, width, height, s, t, rim=None, tuck: float = 0.0, squash: float = 2.2):
    """Points of a dome or head-like cap at parameters (s, t) of the cage's square, the skin's border (z = rim(theta))
    on the circle DISK_R; outside the circle the cap carries on past its border (tucking under), so a trimmed skin
    has a smooth margin. tuck (radians): how far past the widest point the border lies (0: a half-ellipsoid, 0.3:
    a head that narrows to the neck)."""
    du, dv = (np.asarray(s, float) - 0.5) / DISK_R, (np.asarray(t, float) - 0.5) / DISK_R
    r = np.hypot(du, dv)
    th = np.arctan2(dv, du)
    pmax = math.pi / 2 + tuck
    phi = np.minimum(r * pmax, math.pi * 0.97)
    a, b = length / 2, width / 2
    e = 2.0 / squash
    cs, sn = np.cos(th), np.sin(th)
    sx = np.sign(cs) * np.abs(cs) ** e
    sy = np.sign(sn) * np.abs(sn) ** e
    z0 = np.zeros_like(th) if rim is None else np.vectorize(rim)(th)
    zz = (np.cos(phi) - math.cos(pmax)) / (1 - math.cos(pmax))
    Z = z0 + (height - z0) * zz
    rad = np.sin(phi)
    return np.stack([a * rad * sx, b * rad * sy, Z], axis=-1)


def dome_cage(length: float, width: float, height: float, n: int = 14, rim=None, tuck: float = 0.0,
              squash: float = 2.2) -> np.ndarray:
    """A grid cage (n, n, 3) whose limit surface follows dome_point (fitted by least squares), for a skin trimmed by
    the circle DISK_R: a helmet, a mask, a cowl. Edit it with handles (apply_handles), build it with sculpted_shell."""
    k = 4 * n
    g = np.linspace(0, 1, k)
    S, T = np.meshgrid(g, g, indexing="ij")
    P = dome_point(length, width, height, S, T, rim, tuck, squash).reshape(-1, 3)
    return fit_grid(P, S.ravel(), T.ravel(), n, n, smooth=1e-5)


def sculpted_shell(C: np.ndarray, wall: float, radius: float = DISK_R, label: str = "shell"):
    """A shell solid from a skin cage: the skin trimmed by the circle `radius`, its inside (the skin offset inward
    by wall, on the same parameters) and a ruled rim straight across. Three faces; C2 inside the skins."""
    need(wall > 0, "sculpted_shell: the wall must be positive", "Give a wall thickness in mm.", ["wall"])
    return trimmed_shell_solid(C, offset_grid(C, -wall), radius, label=label)


# ── OCCT: grids and patches to faces and solids (kernel worker only) ──────────────────────────────────────────────

def grid_surface(C: np.ndarray):
    """The grid cage as an exact OCCT Geom_BSplineSurface (clamped, bicubic)."""
    from OCP.Geom import Geom_BSplineSurface
    from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
    from OCP.collections import Array1_double as TColStd_Array1OfReal, Array1_int as TColStd_Array1OfInteger
    from OCP.gp import gp_Pnt
    nu, nv = C.shape[:2]
    poles = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            x, y, z = C[i, j]
            poles.SetValue(i + 1, j + 1, gp_Pnt(float(x), float(y), float(z)))

    def kv(n):
        u = np.linspace(0, 1, n - DEG + 1)
        K, M = TColStd_Array1OfReal(1, len(u)), TColStd_Array1OfInteger(1, len(u))
        for i, x in enumerate(u):
            K.SetValue(i + 1, float(x))
            M.SetValue(i + 1, DEG + 1 if i in (0, len(u) - 1) else 1)
        return K, M
    Ku, Mu = kv(nu)
    Kv, Mv = kv(nv)
    return Geom_BSplineSurface(poles, Ku, Kv, Mu, Mv, DEG, DEG, False, False)


def grid_face(C: np.ndarray):
    """A build123d Face of the grid surface (its whole parameter range)."""
    from build123d import Face
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    return Face(BRepBuilderAPI_MakeFace(grid_surface(C), 1e-7).Face())


def _sew_shape(faces, tol: float = 1e-3):
    """Sew OCCT faces (edges that meet along part of their length are cut to match). Returns (shape, free edges)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    sew = BRepBuilderAPI_Sewing(tol)
    for f in faces:
        sew.Add(f.wrapped if hasattr(f, "wrapped") else f)
    sew.Perform()
    return sew.SewedShape(), sew.NbFreeEdges()


def _sew(faces, tol: float = 1e-3, label: str = "body"):
    """Sew OCCT faces into a closed solid (build123d Solid), oriented outward. Raises a RecipeError if it leaks."""
    from build123d import Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    shape, nfree = _sew_shape(faces, tol)
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    need(ex.More(), f"subd: the {label}'s faces did not sew into a shell", "Check the cage for gaps.", ["cage"])
    shell = TopoDS.Shell(ex.Current())
    ms = BRepBuilderAPI_MakeSolid(shell)
    fix = ShapeFix_Solid(ms.Solid())
    fix.Perform()
    s = Solid(fix.Solid())
    if s.volume < 0:
        s = Solid(s.wrapped.Reversed())
    need(nfree == 0, f"subd: the {label} is not closed ({nfree} free edges after sewing)",
         "The cage has a hole or the rim faces do not meet; check the cage.", ["cage"])
    return s


def shell_solid(C: np.ndarray, wall: float, inner: np.ndarray | None = None, label: str = "shell"):
    """A closed solid from a grid skin and its inside: the skin (C), the inside (inner, or C offset by -wall along
    the normal) and four ruled faces across the rim. Six faces, the two big ones exact B-splines."""
    from build123d import Face
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.GeomFill import GeomFill
    need(wall > 0, "subd.shell_solid: the wall must be positive", "Give a wall thickness in mm.", ["wall"])
    In = offset_grid(C, -wall) if inner is None else inner
    so, si = grid_surface(C), grid_surface(In)
    faces = [Face(BRepBuilderAPI_MakeFace(so, 1e-7).Face()), Face(BRepBuilderAPI_MakeFace(si, 1e-7).Face())]
    for iso in ("u0", "u1", "v0", "v1"):
        t = 0.0 if iso[1] == "0" else 1.0
        co = so.UIso(t) if iso[0] == "u" else so.VIso(t)
        ci = si.UIso(t) if iso[0] == "u" else si.VIso(t)
        rs = GeomFill.Surface_s(co, ci)
        faces.append(Face(BRepBuilderAPI_MakeFace(rs, 1e-7).Face()))
    return _sew(faces, tol=1e-4, label=label)


def trimmed_face(C: np.ndarray, radius: float, center=(0.5, 0.5)):
    """The part of the grid surface inside a circle of its parameter square: (OCCT face, its border edge). A skin
    mapped onto a disk (form.meshbody) has no corners, so it fits without the distortion a square's corners bring."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.Geom2d import Geom2d_Circle
    from OCP.ShapeFix import ShapeFix_Face
    from OCP.gp import gp_Ax2d, gp_Dir2d, gp_Pnt2d
    surf = grid_surface(C)
    circ = Geom2d_Circle(gp_Ax2d(gp_Pnt2d(float(center[0]), float(center[1])), gp_Dir2d(1.0, 0.0)), float(radius))
    edge = BRepBuilderAPI_MakeEdge(circ, surf).Edge()
    from OCP.GeomAbs import GeomAbs_C2
    BRepLib.BuildCurves3d_s(edge, 1e-6, GeomAbs_C2, 14, 2000)      # enough spans to follow a fine cage closely
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    for reverse in (False, True):
        w = BRepBuilderAPI_MakeWire(edge.Reversed() if reverse else edge).Wire()
        face = BRepBuilderAPI_MakeFace(surf, w, True).Face()
        # the face must be the inside of the circle: its centre classifies IN
        if BRepClass_FaceClassifier(face, gp_Pnt2d(float(center[0]), float(center[1])), 1e-9).State() == TopAbs_IN:
            break
    fix = ShapeFix_Face(face)
    fix.Perform()
    return fix.Face(), edge


def trimmed_shell_solid(Co: np.ndarray, Ci: np.ndarray, radius: float, center=(0.5, 0.5), label: str = "shell"):
    """A closed solid from two trimmed grid skins (outside Co, inside Ci, the same circle of their parameter squares)
    and one ruled face across the rim between their borders: three faces."""
    from OCP.BRepFill import BRepFill
    fo, eo = trimmed_face(Co, radius, center)
    fi, ei = trimmed_face(Ci, radius, center)
    rim = BRepFill.Face_s(eo, ei)
    return _sew([fo, fi, rim], tol=1e-3, label=label)


# ── quad cages: Catmull-Clark with creases and boundaries, ACC and exact B-spline patches ─────────────────────────
#
# Rules (DeRose, Kass and Truong 1998, with OpenSubdiv's "edge and corner" boundary): an edge with sharpness s >= 1
# (and every boundary edge) is subdivided by the crease rules, its children get s - 1 (infinite stays infinite);
# 0 < s < 1 blends the crease and smooth rules. A vertex with two sharp edges follows its crease (a + 6v + b) / 8, one
# with three or more (or a boundary vertex with one face) is a corner and stays. Infinitely sharp creases and
# boundaries are cubic B-spline curves of their vertices; each side of a crease is the boundary surface of its sector
# (phantom points 2b - i), so a patch whose four corners are regular in their sector (smooth valence 4, a crease
# vertex with two faces on this side, a corner with one) is exactly a bicubic B-spline patch. Semi-sharp creases are
# removed by ceil(s) subdivision levels first; after that the surface is the smooth limit of the finer cage.

INF = math.inf


def _ekey(a, b) -> tuple:
    a, b = int(a), int(b)
    return (a, b) if a < b else (b, a)


def _norm_creases(creases) -> dict:
    """{(a, b): sharpness} from a dict {(a, b): s} or a list of edges (infinitely sharp). s True or None: infinite."""
    out: dict = {}
    if creases is None:
        return out
    items = creases.items() if isinstance(creases, dict) else ((e, INF) for e in creases)
    for e, s in items:
        a, b = e
        s = INF if s is True or s is None else float(s)
        need(s >= 0, f"subd: crease ({a}, {b}) has a negative sharpness", "Give sharpness >= 0 (inf: sharp).", ["creases"])
        if s > 0:
            k = _ekey(a, b)
            out[k] = max(out.get(k, 0.0), s)
    return out


def _sharp_arrays(sharp) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(sharp, tuple):
        return sharp
    if not sharp:
        return np.zeros((0, 2), np.int64), np.zeros(0)
    keys = np.array(list(sharp.keys()), dtype=np.int64).reshape(-1, 2)
    return np.sort(keys, axis=1), np.array(list(sharp.values()), float)


def _halfedges(F):
    """Half-edge arrays of a polygon mesh: start vertex, face, next and previous half-edge, face count."""
    if isinstance(F, np.ndarray) and F.ndim == 2:
        m, s = F.shape
        hv = F.reshape(-1).astype(np.int64)
        hf = np.repeat(np.arange(m), s)
        loc = np.tile(np.arange(s), m)
        base = hf * s
        return hv, hf, base + (loc + 1) % s, base + (loc - 1) % s, m
    sizes = np.array([len(f) for f in F], dtype=np.int64)
    hv = np.concatenate([np.asarray(f, dtype=np.int64) for f in F])
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    hf = np.repeat(np.arange(len(F)), sizes)
    loc = np.arange(len(hv)) - starts[hf]
    return hv, hf, starts[hf] + (loc + 1) % sizes[hf], starts[hf] + (loc - 1) % sizes[hf], len(F)


def _topo(nV: int, F, sharp) -> dict:
    """Edges, sharpness and vertex classes of a polygon mesh (vectorised)."""
    hv, hf, nxt, prv, m = _halfedges(F)
    a, b = hv, hv[nxt]
    code = np.minimum(a, b) * nV + np.maximum(a, b)
    ucode, einv = np.unique(code, return_inverse=True)
    einv = einv.reshape(-1)
    E = len(ucode)
    e0, e1 = ucode // nV, ucode % nV
    nfe = np.bincount(einv, minlength=E)
    need(nfe.max(initial=0) <= 2, "subd: the cage is not manifold (an edge has more than two faces)",
         "Give every edge one or two quads.", ["cage"])
    s = np.zeros(E)
    s[nfe == 1] = INF
    keys, vals = _sharp_arrays(sharp)
    if len(keys):
        c = keys[:, 0] * nV + keys[:, 1]
        idx = np.searchsorted(ucode, c)
        ok = idx < E
        ok[ok] = ucode[idx[ok]] == c[ok]
        s[idx[ok]] = np.maximum(s[idx[ok]], vals[ok])
    val = np.bincount(e0, minlength=nV) + np.bincount(e1, minlength=nV)
    nfv = np.bincount(hv, minlength=nV)
    se = s > 0
    ns = np.bincount(e0[se], minlength=nV) + np.bincount(e1[se], minlength=nV)
    ssum = np.bincount(e0[se], weights=s[se], minlength=nV) + np.bincount(e1[se], weights=s[se], minlength=nV)
    bnd = np.zeros(nV, bool)
    bnd[e0[nfe == 1]] = True
    bnd[e1[nfe == 1]] = True
    corner = (ns >= 3) | (bnd & (nfv == 1))
    crease = (ns == 2) & ~corner
    avg = np.where(ns > 0, ssum / np.maximum(ns, 1), 0.0)
    return dict(hv=hv, hf=hf, nxt=nxt, prv=prv, m=m, einv=einv, e0=e0, e1=e1, nfe=nfe, s=s, val=val, nfv=nfv,
                ns=ns, bnd=bnd, corner=corner, crease=crease, avg=avg)


def _cc_step(V: np.ndarray, F, sharp):
    """One Catmull-Clark step with creases and boundaries. Returns (V, quads, child sharpness, parent face)."""
    V = np.asarray(V, dtype=np.float64)
    nV = len(V)
    T = _topo(nV, F, sharp)
    hv, hf, prv, m, einv, e0, e1, s = T["hv"], T["hf"], T["prv"], T["m"], T["einv"], T["e0"], T["e1"], T["s"]
    fp = np.zeros((m, 3))
    np.add.at(fp, hf, V[hv])
    fp /= np.bincount(hf, minlength=m)[:, None]
    E = len(e0)
    fsum = np.zeros((E, 3))
    np.add.at(fsum, einv, fp[hf])
    mid = (V[e0] + V[e1]) / 2
    smooth_e = (V[e0] + V[e1] + fsum) / 4
    w = np.clip(s, 0, 1)[:, None]
    ep = w * mid + (1 - w) * smooth_e
    Fsum = np.zeros((nV, 3))
    np.add.at(Fsum, hv, fp[hf])
    Rsum = np.zeros((nV, 3))
    np.add.at(Rsum, e0, mid)
    np.add.at(Rsum, e1, mid)
    n = np.maximum(T["val"], 1).astype(float)[:, None]
    nf = np.maximum(T["nfv"], 1)[:, None]
    smooth_v = (Fsum / nf + 2 * Rsum / n + (n - 3) * V) / n
    se = s > 0
    nb = np.zeros((nV, 3))
    np.add.at(nb, e0[se], V[e1[se]])
    np.add.at(nb, e1[se], V[e0[se]])
    sharp_v = np.where(T["corner"][:, None], V, (nb + 6 * V) / 8)
    wv = np.where(T["corner"] | T["crease"], np.clip(T["avg"], 0, 1), 0.0)[:, None]
    vp = wv * sharp_v + (1 - wv) * smooth_v
    Vout = np.vstack([vp, fp, ep])
    Q = np.stack([hv, nV + m + einv, nV + hf, nV + m + einv[prv]], axis=1)
    keep = (T["nfe"] == 2) & (s > 1)
    j = np.nonzero(keep)[0]
    mids = nV + m + j
    ck = np.vstack([np.stack([e0[j], mids], 1), np.stack([mids, e1[j]], 1)])
    cv = np.r_[s[j] - 1, s[j] - 1]
    return Vout, Q, (np.sort(ck, axis=1), cv), hf


def catmull_clark(V: np.ndarray, F: list, creases=None) -> tuple[np.ndarray, np.ndarray]:
    """One Catmull-Clark step on a polygon mesh (any polygons; open borders follow the B-spline boundary rules,
    creases {(a, b): sharpness} the crease rules). Returns (V, quads)."""
    Vout, Q, _, _ = _cc_step(V, [list(f) for f in F] if not isinstance(F, np.ndarray) else F,
                             _norm_creases(creases))
    return Vout, Q


def subdivide(V, F, creases=None, levels: int = 1):
    """`levels` Catmull-Clark steps with creases. Returns (V, quads, remaining creases {(a, b): s}, parent face of
    every quad in the input's faces)."""
    sh = _sharp_arrays(_norm_creases(creases))
    V = np.asarray(V, dtype=np.float64)
    F = F if isinstance(F, np.ndarray) else [list(f) for f in F]
    parent = np.arange(len(F))
    for _ in range(int(levels)):
        V, F, sh, p = _cc_step(V, F, sh)
        parent = parent[p]
    keys, vals = sh
    return V, np.asarray(F, dtype=np.int64), {_ekey(*k): float(v) for k, v in zip(keys, vals) if v > 0}, parent


def limit_points(V: np.ndarray, Q: np.ndarray, creases=None) -> np.ndarray:
    """Exact limit positions of a quad cage's vertices: smooth (n^2 v + 4 sum(edge) + sum(diagonal)) / (n (n + 5)),
    crease (a + 4v + b) / 6, corner v. Edges still semi-sharp below 1 count as smooth."""
    V = np.asarray(V, dtype=np.float64)
    nV = len(V)
    T = _topo(nV, Q, _sharp_arrays(_norm_creases(creases)) if not isinstance(creases, tuple) else creases)
    hv, nxt, e0, e1, s = T["hv"], T["nxt"], T["e0"], T["e1"], T["s"]
    nb = np.zeros((nV, 3))
    np.add.at(nb, e0, V[e1])
    np.add.at(nb, e1, V[e0])
    dg = np.zeros((nV, 3))
    np.add.at(dg, hv, V[hv[nxt[nxt]]])
    n = np.maximum(T["val"], 1).astype(float)[:, None]
    out = (n * n * V + 4 * nb + dg) / (n * (n + 5))
    se = s >= 1
    nbs = np.zeros((nV, 3))
    np.add.at(nbs, e0[se], V[e1[se]])
    np.add.at(nbs, e1[se], V[e0[se]])
    sharp = T["avg"] >= 1
    cr = T["crease"] & sharp
    co = T["corner"] & sharp
    out[cr] = (nbs[cr] + 4 * V[cr]) / 6
    out[co] = V[co]
    return out


def _acc(nV: int, Q: np.ndarray, sharp=None):
    """ACC operator generalised to creases and boundaries: M (len(Q)*16 x nV) maps cage points to the 16 Bezier
    points of every quad's patch (row q*16 + r*4 + c; corner a at (0, 0), b at (0, 3), c at (3, 3), d at (3, 0)), and
    the topology facts the patches need. Corners: exact limit points. Edge points on a crease: (2v + w) / 3 (the crease
    B-spline, exact). Interior points: (n v + 2 e1 + 2 e2 + f) / (n + 5), n the valence of a smooth vertex, 2k for a
    crease vertex and 4k for a corner with k faces in the patch's sector (exact where regular). Other edge points are
    the mean of the interior points either side, as in Loop and Schaefer's ACC."""
    import scipy.sparse as sp
    Q = np.asarray(Q, dtype=np.int64)
    m = len(Q)
    T = _topo(nV, Q, _sharp_arrays(sharp or {}) if not isinstance(sharp, tuple) else sharp)
    e0, e1, s = T["e0"], T["e1"], T["s"]
    sharpset = {(int(a), int(b)) for a, b in zip(e0[s > 0], e1[s > 0])}
    val, ns = T["val"], T["ns"]
    vtype = np.zeros(nV, np.int64)
    vtype[T["crease"]] = 1
    vtype[T["corner"]] = 2
    snbr = [[] for _ in range(nV)]
    for a, b in sharpset:
        snbr[a].append(b)
        snbr[b].append(a)
    he = {}
    for qi, f in enumerate(Q):
        for i in range(4):
            he[(int(f[i]), int(f[(i + 1) % 4]))] = (qi, i)

    def is_sharp(a, b):
        return _ekey(a, b) in sharpset

    ksec = np.ones((m, 4), np.int64)
    for qi, f in enumerate(Q):
        for i in range(4):
            v = int(f[i])
            if vtype[v] == 0:
                ksec[qi, i] = val[v]
                continue
            count, q, j, closed = 1, qi, i, False
            while True:
                pv = int(Q[q][(j - 1) % 4])
                nb = None if is_sharp(pv, v) else he.get((v, pv))
                if nb is None:
                    break
                q, j = nb
                if q == qi:
                    closed = True
                    break
                count += 1
            if not closed:
                q, j = qi, i
                while True:
                    nx = int(Q[q][(j + 1) % 4])
                    nb = None if is_sharp(v, nx) else he.get((nx, v))
                    if nb is None:
                        break
                    q, j = nb[0], (nb[1] + 1) % 4
                    count += 1
            ksec[qi, i] = count

    def neff(qi, i):
        v = int(Q[qi][i])
        return float(val[v]) if vtype[v] == 0 else (2.0 if vtype[v] == 1 else 4.0) * ksec[qi, i]

    I, by_edge = {}, {}
    for qi, f in enumerate(Q):
        for i in range(4):
            n = neff(qi, i)
            d = {}
            for c, w in ((f[i], n), (f[(i + 1) % 4], 2), (f[(i - 1) % 4], 2), (f[(i + 2) % 4], 1)):
                d[int(c)] = d.get(int(c), 0) + w / (n + 5)
            I[(qi, i)] = d
            by_edge.setdefault((int(f[i]), int(f[(i + 1) % 4])), []).append((qi, i))
            by_edge.setdefault((int(f[i]), int(f[(i - 1) % 4])), []).append((qi, i))
    # diagonal neighbours for the smooth limit stencil
    diag = [[] for _ in range(nV)]
    nbr = [set() for _ in range(nV)]
    for f in Q:
        for i in range(4):
            diag[f[i]].append(int(f[(i + 2) % 4]))
            nbr[f[i]].add(int(f[(i + 1) % 4]))
            nbr[f[i]].add(int(f[(i - 1) % 4]))
    lim_cache = {}

    def limit(v):
        if v in lim_cache:
            return lim_cache[v]
        if vtype[v] == 2:
            d = {v: 1.0}
        elif vtype[v] == 1:
            a, b = snbr[v][:2]
            d = {v: 4 / 6, a: 1 / 6}
            d[b] = d.get(b, 0) + 1 / 6
        else:
            n = val[v]
            d = {v: n * n / (n * (n + 5))}
            for e in nbr[v]:
                d[e] = d.get(e, 0) + 4 / (n * (n + 5))
            for g in diag[v]:
                d[g] = d.get(g, 0) + 1 / (n * (n + 5))
        lim_cache[v] = d
        return d

    def edge_pt(v, w):
        if vtype[v] > 0 and is_sharp(v, w):
            return {v: 2 / 3, w: 1 / 3}
        users = by_edge[(v, w)]
        out = {}
        for key in users:
            for c, x in I[key].items():
                out[c] = out.get(c, 0) + x / len(users)
        return out

    rows, cols, vals = [], [], []
    for qi, f in enumerate(Q):
        a, b, c, d = (int(x) for x in f)
        base = qi * 16
        for (r, cc), combo in (((0, 0), limit(a)), ((0, 3), limit(b)), ((3, 3), limit(c)), ((3, 0), limit(d)),
                               ((0, 1), edge_pt(a, b)), ((0, 2), edge_pt(b, a)), ((1, 3), edge_pt(b, c)),
                               ((2, 3), edge_pt(c, b)), ((3, 2), edge_pt(c, d)), ((3, 1), edge_pt(d, c)),
                               ((2, 0), edge_pt(d, a)), ((1, 0), edge_pt(a, d)),
                               ((1, 1), I[(qi, 0)]), ((1, 2), I[(qi, 1)]), ((2, 2), I[(qi, 2)]), ((2, 1), I[(qi, 3)])):
            for k, wgt in combo.items():
                rows.append(base + r * 4 + cc)
                cols.append(k)
                vals.append(wgt)
    M = sp.csr_matrix((vals, (rows, cols)), shape=(m * 16, nV))
    corner_reg = np.zeros((m, 4), bool)
    for qi, f in enumerate(Q):
        for i in range(4):
            v = int(f[i])
            corner_reg[qi, i] = ((vtype[v] == 0 and ns[v] == 0 and val[v] == 4) or (vtype[v] == 1 and ksec[qi, i] == 2)
                                 or (vtype[v] == 2 and ksec[qi, i] == 1))
    smooth_ev = (vtype == 0) & (ns == 0) & (val != 4) & (T["nfv"] > 0)
    irregular = np.zeros(nV, bool)
    irregular[Q[~corner_reg]] = True
    info = dict(valence=val, g1_valence=np.where(smooth_ev, val, 4), regular=corner_reg.all(1), irregular=irregular,
                sharp=sharpset, vtype=vtype, boundary=int(np.sum(T["nfe"] == 1)), he=he)
    return M, info


def acc_operator(nV: int, Q: np.ndarray, creases=None):
    """Sparse matrix M (len(Q)*16 x nV): the 16 Bezier control points of each quad's ACC patch, as linear combinations
    of the cage points (before the tangent-plane step). Patch q, row r, column c is row q*16 + r*4 + c. Also returns
    the valence of every cage point."""
    M, info = _acc(nV, Q, _norm_creases(creases))
    return M, info["valence"]


def tangent_planes(B: np.ndarray, Q: np.ndarray, valence: np.ndarray) -> np.ndarray:
    """Put the edge points round every extraordinary vertex into one plane through its limit point (the plane that
    fits them best), so the patches meet with one normal there (G1 at the vertex). B: (m, 4, 4, 3), changed copy.
    Vertices given valence 4 are left alone (crease, corner and boundary vertices are passed as 4)."""
    B = B.copy()
    corners = ((0, 0, (0, 1), (1, 0)), (0, 3, (0, 2), (1, 3)), (3, 3, (3, 2), (2, 3)), (3, 0, (3, 1), (2, 0)))
    groups = {}
    for qi, f in enumerate(Q):
        for k, (r, c, e1, e2) in enumerate(corners):
            v = int(f[k])
            if valence[v] != 4:
                groups.setdefault(v, []).append((qi, r, c, e1, e2))
    inner = {(0, 0): (1, 1), (0, 3): (1, 2), (3, 3): (2, 2), (3, 0): (2, 1)}
    for v, uses in groups.items():
        L = B[uses[0][0], uses[0][1], uses[0][2]]
        E = np.array([B[q, e[0], e[1]] for q, _, _, e1, e2 in uses for e in (e1, e2)])
        _, _, vt = np.linalg.svd(E - L)
        n = vt[2]
        # each edge point is shared by the two patches on either side of its edge: project it once, and shift the
        # two patches' interior points at v so the edge point stays their midpoint (C1 across the border there)
        edges = {}
        for k, (q, r, c, e1, e2) in enumerate(uses):
            for e in (e1, e2):
                key = tuple(np.round(B[q, e[0], e[1]], 7))
                edges.setdefault(key, []).append((k, q, e))
        rows, rhs = [], []
        for key, sh in edges.items():
            d = -np.dot(B[sh[0][1], sh[0][2][0], sh[0][2][1]] - L, n) * n
            for _, q, e in sh:
                B[q, e[0], e[1]] = B[q, e[0], e[1]] + d
            if len(sh) == 2:
                row = np.zeros(len(uses))
                row[sh[0][0]] = row[sh[1][0]] = 0.5
                rows.append(row)
                rhs.append(d)
        if rows:
            S = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
            for k, (q, r, c, _, _) in enumerate(uses):
                i, j = inner[(r, c)]
                B[q, i, j] = B[q, i, j] + S[k]
    return B


def _rot(B: np.ndarray, r: int) -> np.ndarray:
    """A patch's 4 x 4 (x 3) control points re-indexed for its quad's corners rolled by r (corner r becomes a)."""
    for _ in range(r % 4):
        B = B.transpose(1, 0, *range(2, B.ndim))[::-1]
    return B


class Cage:
    """A quad cage (any genus, closed or open): points V (n, 3) and polygons F, counter-clockwise seen from outside.

    creases: {(a, b): sharpness} or a list of edges (infinitely sharp: a C0 border between exact patches); a finite
    sharpness s is resolved by ceil(s) subdivision levels first (the semi-sharp rules), so levels may grow. Open borders
    follow the B-spline boundary rules (a boundary vertex with one face is a corner). regions: {name: [face indices
    of F]}; every patch and every face of solid() keeps its region's name (region_faces, region_frame, region_tool)."""

    def __init__(self, V, F, levels: int = 0, creases=None, regions: dict | None = None):
        V = np.asarray(V, dtype=np.float64)
        F = [list(f) for f in F]
        sharp = _norm_creases(creases)
        finite = [s for s in sharp.values() if s != INF]
        k = int(levels)
        if finite:
            k = max(k, int(math.ceil(max(finite))))
        if any(len(f) != 4 for f in F) and k == 0:
            k = 1                                # one step makes any polygon mesh all quads
        self.region_names = list(regions or {})
        rid = np.full(len(F), -1, np.int64)
        for n_, (name, idx) in enumerate((regions or {}).items()):
            idx = list(idx)
            need(all(0 <= int(i) < len(F) for i in idx), f"subd.Cage: region {name!r} names a face that is not in the "
                 "cage", "Give face indices of F.", ["regions"])
            rid[idx] = n_
        sh = _sharp_arrays(sharp)
        Fx = F
        for _ in range(k):
            V, Fx, sh, parent = _cc_step(V, Fx, sh)
            rid = rid[parent]
        keys, vals = sh
        self.V, self.F = V, np.asarray(Fx, dtype=np.int64)
        self.levels = k
        self.creases = {_ekey(*kk): float(v) for kk, v in zip(keys, vals) if v > 0}
        self.face_region = rid
        self._M = None
        self._faces_meta: list = []

    # topology ------------------------------------------------------------------------------------------------
    def _build(self):
        self._M, self.info = _acc(len(self.V), self.F, self.creases)
        self.valence = self.info["valence"]

    @property
    def M(self):
        if self._M is None:
            self._build()
        return self._M

    def extraordinary(self) -> int:
        """Smooth vertices that do not have four quads round them (where ACC is an approximation)."""
        _ = self.M
        return int(np.sum(self.info["g1_valence"] != 4))

    def irregular(self) -> int:
        """Vertices where at least one patch is not an exact B-spline patch (extraordinary, dart, or a crease or corner
        sector that is not regular). 0: the whole skin is exact."""
        _ = self.M
        return int(np.sum(self.info["irregular"]))

    @property
    def exact(self) -> bool:
        _ = self.M
        return bool(self.info["regular"].all())

    def is_open(self) -> bool:
        _ = self.M
        return self.info["boundary"] > 0

    def sharp_edges(self) -> set:
        _ = self.M
        return set(self.info["sharp"])

    # patches -----------------------------------------------------------------------------------------------
    def patches(self, V=None, g1: bool = True) -> np.ndarray:
        """(m, 4, 4, 3) bicubic Bezier control points, one patch per quad."""
        M = self.M
        B = (M @ (self.V if V is None else V)).reshape(len(self.F), 4, 4, 3)
        return tangent_planes(B, self.F, self.info["g1_valence"]) if g1 else B

    def sample_operator(self, k: int = 4):
        """Sparse W (len(F) * k * k x nV): points of the limit surface on a k x k grid per patch (no tangent step)."""
        import scipy.sparse as sp
        t = np.linspace(0, 1, k)
        Bt = bernstein(t)                       # (k, 4)
        Wp = np.einsum("ar,bc->abrc", Bt, Bt).reshape(k * k, 16)      # rows: (v, u) samples; cols: r*4+c
        blk = sp.block_diag([sp.csr_matrix(Wp)] * len(self.F), format="csr")
        return blk @ self.M

    def seams(self, B=None) -> dict:
        """seam_angles over the smooth borders (creases and open borders are C0 by design and left out)."""
        return seam_angles(self.patches() if B is None else B, self.F, skip=self.sharp_edges())

    # merging regular patches into multi-span B-spline faces --------------------------------------------------
    def blocks(self) -> list:
        """Rectangular blocks of regular patches (same region, no crease inside): [[(face, roll), ...] per row], rows
        along v. A block never closes on itself (a loop of patches is split in two)."""
        _ = self.M
        F, reg, rid, he, sharp = self.F, self.info["regular"], self.face_region, self.info["he"], self.info["sharp"]
        taken = np.zeros(len(F), bool)

        def orient(q, r):
            return tuple(int(F[q][(i + r) % 4]) for i in range(4))

        def across(q, r, side):
            o = orient(q, r)
            a, b = o[side], o[(side + 1) % 4]
            if _ekey(a, b) in sharp:
                return None
            nb = he.get((b, a))
            if nb is None:
                return None
            g, k = nb
            return (g, (k + 1) % 4) if side == 1 else (g, k % 4)

        def ok(x, region, used):
            return x is not None and reg[x[0]] and not taken[x[0]] and rid[x[0]] == region and x[0] not in used

        out = []
        for seed in range(len(F)):
            if taken[seed] or not reg[seed]:
                continue
            region = rid[seed]
            row, used, cyc = [(seed, 0)], {seed}, False
            while True:
                nb = across(*row[-1], 1)
                if nb is not None and nb[0] == seed:
                    cyc = True
                    break
                if not ok(nb, region, used):
                    break
                row.append(nb)
                used.add(nb[0])
            if cyc and len(row) > 1:
                row = row[:(len(row) + 1) // 2]
                used = {x[0] for x in row}
            block, vcyc = [row], False
            while True:
                nxt = [across(q, r, 2) for q, r in block[-1]]
                if nxt[0] is not None and nxt[0][0] == seed:
                    vcyc = True
                    break
                if not all(ok(x, region, used) for x in nxt) or len({x[0] for x in nxt}) != len(nxt):
                    break
                if any(across(*nxt[j], 1) != nxt[j + 1] for j in range(len(nxt) - 1)):
                    break
                if any(x[0] in {y[0] for r_ in block for y in r_} for x in nxt):
                    vcyc = True
                    break
                block.append(nxt)
                used.update(x[0] for x in nxt)
            if vcyc and len(block) > 1:
                block = block[:(len(block) + 1) // 2]
            for r_ in block:
                for q, _ in r_:
                    taken[q] = True
            out.append(block)
        for q in range(len(F)):
            if not taken[q]:
                out.append([[(q, 0)]])
        return out

    def faces(self, merge: bool = True, B=None) -> list:
        """OCCT faces of the skin: one exact bicubic B-spline face per block of regular patches (merge=True), one
        Bezier face per other patch. self.face_meta() says which, with region names."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        B = self.patches() if B is None else B
        blocks = self.blocks() if merge else [[[(q, 0)]] for q in range(len(self.F))]
        faces, meta = [], []
        scale = float(np.ptp(self.V, axis=0).max() or 1.0)
        for blk in blocks:
            qs = [q for r_ in blk for q, _ in r_]
            name = self.region_names[self.face_region[qs[0]]] if self.face_region[qs[0]] >= 0 else None
            if len(qs) > 1:
                C, res = block_grid(blk, B)
                if res <= 1e-9 * scale + 1e-12:
                    faces.append(BRepBuilderAPI_MakeFace(grid_surface(C), 1e-7).Face())
                    meta.append({"kind": "bspline", "patches": qs, "spans": (len(blk[0]), len(blk)),
                                 "region": name, "fit_residual_mm": float(res)})
                    continue
            for q in qs:
                faces.append(_bezier_face(B[q]))
                meta.append({"kind": "bezier", "patches": [q], "spans": (1, 1), "region": name,
                             "fit_residual_mm": 0.0})
        self._faces_meta = meta
        return faces

    def face_meta(self) -> list:
        return list(self._faces_meta)

    def surface(self, merge: bool = True, label: str = "skin"):
        """The skin as one sewn build123d Shell (open borders stay free edges)."""
        from build123d import Shell
        from OCP.TopAbs import TopAbs_SHELL
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        shape, _ = _sew_shape(self.faces(merge), tol=1e-4)
        ex = TopExp_Explorer(shape, TopAbs_SHELL)
        need(ex.More(), f"subd: the {label}'s faces did not sew into a shell", "Check the cage for gaps.", ["cage"])
        return Shell(TopoDS.Shell(ex.Current()))

    def solid(self, label: str = "body", merge: bool = True, close: str = "cap", thickness: float | None = None):
        """The cage's limit surface as a closed OCCT solid: exact B-spline faces for regular blocks, ACC Bezier faces
        elsewhere. An open cage is closed by close="cap" (a planar face per planar border: exact; otherwise an OCCT
        filling surface, approximate and noted) or close="thicken" (the skin grown by thickness mm inward)."""
        faces = self.faces(merge)
        if not self.is_open():
            return _sew(faces, tol=1e-4, label=label)
        need(close in ("cap", "thicken"), f"subd.Cage.solid: unknown close {close!r}", "Use 'cap' or 'thicken'.",
             ["close"])
        if close == "thicken":
            need(thickness is not None and thickness > 0, "subd.Cage.solid: thicken needs a thickness",
                 "Give thickness in mm.", ["thickness"])
            from .surfaces import thicken
            sh = self.surface(merge, label)
            s = thicken(sh, float(thickness))
            note(f"subd: the open {label} was thickened by {float(thickness):g} mm (OCCT offset of the exact skin)")
            return s
        shape, _ = _sew_shape(faces, tol=1e-4)
        caps, kinds = _caps(shape)
        need(bool(caps), f"subd: the open {label} has no closed border to cap", "Close the cage or thicken it.",
             ["close"])
        if "filling" in kinds:
            note(f"subd: {kinds.count('filling')} non-planar border(s) of the {label} capped with an OCCT filling "
                 "surface (approximate, not the subdivision limit)")
        self._caps = kinds
        return _sew(faces + caps, tol=1e-4, label=label)

    # named regions ---------------------------------------------------------------------------------------------
    def _region_id(self, name: str) -> int:
        need(name in self.region_names, f"subd.Cage: no region {name!r}",
             f"Regions: {', '.join(self.region_names) or 'none'}.", ["regions"])
        return self.region_names.index(name)

    def region_patches(self, name: str) -> np.ndarray:
        return np.nonzero(self.face_region == self._region_id(name))[0]

    def region_faces(self, shape, name: str) -> list:
        """The faces of a solid built from this cage (or cut and fused since) that lie on region `name`: each face's
        middle point is matched to the nearest sample of the patches (within 1% of the cage size)."""
        from scipy.spatial import cKDTree
        rid = self._region_id(name)
        G = patch_eval(self.patches(), 5)
        pts = G.reshape(-1, 3)
        owner = np.repeat(np.arange(len(self.F)), 25)
        tree = cKDTree(pts)
        tol = 0.01 * float(np.ptp(self.V, axis=0).max() or 1.0)
        out = []
        for f in shape.faces():
            p = f.position_at(0.5, 0.5)
            d, i = tree.query([p.X, p.Y, p.Z])
            if d <= tol and self.face_region[owner[i]] == rid:
                out.append(f)
        return out

    def region_frame(self, name: str) -> tuple:
        """(point, outward unit normal) at the middle of region `name` on the limit surface: `at` and `axis` for
        craft.magnet_pair, or where to aim a feature."""
        B = self.patches()
        qs = self.region_patches(name)
        G = patch_eval(B[qs], 7).reshape(-1, 3)
        c = G.mean(0)
        k = int(np.argmin(np.linalg.norm(G - c, axis=1)))
        q, rem = qs[k // 49], k % 49
        t = np.linspace(0, 1, 7)
        v_, u_ = t[rem // 7], t[rem % 7]
        p, Su, Sv = _patch_point(B[q], u_, v_)
        nrm = np.cross(Su, Sv)
        nrm /= np.linalg.norm(nrm) or 1.0
        return tuple(float(x) for x in p), tuple(float(x) for x in nrm)

    def region_tool(self, name: str, out: float = 1.0, depth: float = 2.0, label: str = ""):
        """A closed solid that follows region `name`: from depth mm under the skin to out mm over it (control points
        moved along the surface normal, so it follows the skin to well under 0.1 mm for a gentle region). Intersect
        it with a shell for the region's piece (a lid, a panel for craft.parts) or cut it away (craft.cut)."""
        need(out >= 0 and depth > 0 and out + depth > 0.05, "subd.Cage.region_tool: out >= 0 and depth > 0",
             "Give the slab's reach over and under the skin in mm.", ["out", "depth"])
        B = self.patches()
        qs = self.region_patches(name)
        need(len(qs) > 0, f"subd.Cage.region_tool: region {name!r} has no patches", "Name some faces.", ["regions"])
        P = B[qs]
        # one normal per control point position (shared points get the same normal, so the slab stays closed)
        t = np.array([0, 1 / 3, 2 / 3, 1])
        N = np.zeros_like(P)
        for k in range(len(qs)):
            for r in range(4):
                for c in range(4):
                    _, Su, Sv = _patch_point(P[k], t[c], t[r])
                    N[k, r, c] = np.cross(Su, Sv)
        keys = np.round(P.reshape(-1, 3), 6)
        _, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        acc = np.zeros((inv.max() + 1, 3))
        np.add.at(acc, inv, N.reshape(-1, 3) / np.maximum(np.linalg.norm(N.reshape(-1, 3), axis=1, keepdims=True), 1e-12))
        acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
        Nn = acc[inv].reshape(P.shape)
        Po, Pi = P + out * Nn, P - depth * Nn
        faces = [_bezier_face(p) for p in Po] + [_bezier_face(p) for p in Pi]
        inreg = set(int(q) for q in qs)
        he = self.info["he"]
        sides = (((0, 0), (0, 3)), ((0, 3), (3, 3)), ((3, 3), (3, 0)), ((3, 0), (0, 0)))
        for k, q in enumerate(qs):
            f = self.F[q]
            for i in range(4):
                nb = he.get((int(f[(i + 1) % 4]), int(f[i])))
                if nb is not None and nb[0] in inreg:
                    continue
                (r0, c0), (r1, c1) = sides[i]
                idx = [(r0 + (r1 - r0) * j // 3, c0 + (c1 - c0) * j // 3) for j in range(4)]
                co = np.array([Po[k][r, c] for r, c in idx])
                ci = np.array([Pi[k][r, c] for r, c in idx])
                W = np.stack([co, co + (ci - co) / 3, co + 2 * (ci - co) / 3, ci])
                faces.append(_bezier_face(W))
        return _sew(faces, tol=1e-4, label=label or f"{name} region")


def block_grid(block: list, B: np.ndarray, per_span: int = 4):
    """The clamped bicubic B-spline grid (nu, nv, 3) of a block of C2-joined patches ([[(face, roll), ...] per row]),
    by least squares on samples of the patches (exact when they are one B-spline: the residual says how close)."""
    a, b = len(block[0]), len(block)
    su = np.linspace(0, 1, a * per_span + 1)
    sv = np.linspace(0, 1, b * per_span + 1)
    ci = np.minimum((su * a).astype(int), a - 1)
    ri = np.minimum((sv * b).astype(int), b - 1)
    lu, lv = su * a - ci, sv * b - ri
    Bu_l, Bv_l = bernstein(lu), bernstein(lv)
    P = {}
    S = np.empty((len(su), len(sv), 3))
    for j in range(b):
        for i in range(a):
            q, r = block[j][i]
            P[(i, j)] = _rot(B[q], r)
    for x in range(len(su)):
        for y in range(len(sv)):
            S[x, y] = np.einsum("r,c,rck->k", Bv_l[y], Bu_l[x], P[(ci[x], ri[y])])
    Au = basis(su, a + 3).toarray()
    Av = basis(sv, b + 3).toarray()
    pu, pv = np.linalg.pinv(Au), np.linalg.pinv(Av)
    C = np.einsum("ix,xyk,jy->ijk", pu, S, pv)
    res = float(np.abs(np.einsum("xi,ijk,yj->xyk", Au, C, Av) - S).max())
    return C, res


def _patch_point(P: np.ndarray, u: float, v: float):
    """Point and derivatives (along u: columns, along v: rows) of one bicubic Bezier patch."""
    bu, bv = bernstein(np.array([u]))[0], bernstein(np.array([v]))[0]
    du, dv = _dbern(u), _dbern(v)
    return (np.einsum("r,c,rck->k", bv, bu, P), np.einsum("r,c,rck->k", bv, du, P),
            np.einsum("r,c,rck->k", dv, bu, P))


def _bezier_face(P: np.ndarray):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.Geom import Geom_BezierSurface
    from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    arr = TColgp_Array2OfPnt(1, 4, 1, 4)
    for r in range(4):
        for c in range(4):
            x, y, z = P[r, c]
            arr.SetValue(c + 1, r + 1, gp_Pnt(float(x), float(y), float(z)))
    return BRepBuilderAPI_MakeFace(Geom_BezierSurface(arr), 1e-7).Face()


def _caps(shape):
    """Faces that close every free border of a sewn shell: planar where the border is planar (exact), an OCCT
    filling surface otherwise. Returns (faces, kinds)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
    from OCP.GeomAbs import GeomAbs_C0
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    fb = ShapeAnalysis_FreeBounds(shape, 1e-3, False, False)
    wires = fb.GetClosedWires()
    ex = TopExp_Explorer(wires, TopAbs_WIRE)
    caps, kinds = [], []
    while ex.More():
        w = TopoDS.Wire(ex.Current())
        mk = BRepBuilderAPI_MakeFace(w, True)
        if mk.IsDone():
            caps.append(mk.Face())
            kinds.append("planar")
        else:
            fill = BRepOffsetAPI_MakeFilling()
            ee = TopExp_Explorer(w, TopAbs_EDGE)
            while ee.More():
                fill.Add(TopoDS.Edge(ee.Current()), GeomAbs_C0)
                ee.Next()
            fill.Build()
            need(fill.IsDone(), "subd: a border of the open cage could not be capped", "Thicken the skin instead.",
                 ["close"])
            caps.append(TopoDS.Face(fill.Shape()))
            kinds.append("filling")
        ex.Next()
    return caps, kinds


def bernstein(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, float)[:, None]
    s = 1 - t
    return np.hstack([s ** 3, 3 * s * s * t, 3 * s * t * t, t ** 3])


def patch_eval(B: np.ndarray, k: int = 6) -> np.ndarray:
    """(m, k, k, 3) points of every patch on a k x k grid (rows along v, columns along u)."""
    Bt = bernstein(np.linspace(0, 1, k))
    return np.einsum("ar,mrcx,bc->mabx", Bt, B, Bt)


def patches_solid(B: np.ndarray, label: str = "body"):
    """Sew bicubic Bezier patches (m, 4, 4, 3) into a closed solid."""
    return _sew([_bezier_face(P) for P in B], tol=1e-4, label=label)


def seam_angles(B: np.ndarray, Q: np.ndarray, samples: int = 7, skip=None) -> dict:
    """Normal angle (degrees) across every patch border, sampled along it: the measured smoothness of an ACC skin.
    0 = tangent (G1). Returns worst, mean and the share of borders within 1 degree. skip: undirected edges (a, b),
    a < b, left out (creases, which are C0 on purpose)."""
    def normal(P, s, t):
        bs, bt = bernstein(np.array([s]))[0], bernstein(np.array([t]))[0]
        dbs = _dbern(s)
        dbt = _dbern(t)
        Su = np.einsum("r,c,rcx->x", bt, dbs, P)
        Sv = np.einsum("r,c,rcx->x", dbt, bs, P)
        n = np.cross(Su, Sv)
        return n / (np.linalg.norm(n) or 1)

    skip = skip or set()
    # border of patch q between corners i and i+1, and the (s, t) along it
    side = {0: lambda w: (w, 0.0), 1: lambda w: (1.0, w), 2: lambda w: (1 - w, 1.0), 3: lambda w: (0.0, 1 - w)}
    owner = {}
    for qi, f in enumerate(Q):
        for i in range(4):
            owner.setdefault((int(f[i]), int(f[(i + 1) % 4])), (qi, i))
    angles = []
    done = set()
    for (a, b), (qi, i) in owner.items():
        if (b, a) not in owner or (b, a) in done or _ekey(a, b) in skip:
            continue
        done.add((a, b))
        qj, j = owner[(b, a)]
        worst = 0.0
        for w in np.linspace(0.08, 0.92, samples):
            s1, t1 = side[i](w)
            s2, t2 = side[j](1 - w)
            n1, n2 = normal(B[qi], s1, t1), normal(B[qj], s2, t2)
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(n1, n2)))))))
        angles.append(worst)
    A = np.array(angles) if angles else np.zeros(1)
    return {"borders": len(angles), "worst_deg": round(float(A.max()), 4), "mean_deg": round(float(A.mean()), 4),
            "within_1deg": round(float(np.mean(A <= 1.0)), 4), "within_0_1deg": round(float(np.mean(A <= 0.1)), 4)}


def _dbern(t: float) -> np.ndarray:
    s = 1 - t
    return np.array([-3 * s * s, 3 * s * s - 6 * s * t, 6 * s * t - 3 * t * t, 3 * t * t])


def quad_sphere(n: int = 4, radius: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """A closed quad cage round a sphere: a cube's six faces each split n x n and pushed out to the sphere. Eight
    extraordinary (valence 3) vertices at the cube's corners."""
    verts, index, quads = [], {}, []

    def vid(p):
        key = tuple(np.round(p, 9))
        if key not in index:
            index[key] = len(verts)
            verts.append(p)
        return index[key]
    g = np.linspace(-1, 1, n + 1)
    for axis in range(3):
        for sgn in (-1, 1):
            for i in range(n):
                for j in range(n):
                    corners = []
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        p = np.zeros(3)
                        p[axis] = sgn
                        p[(axis + 1) % 3] = g[i + di]
                        p[(axis + 2) % 3] = g[j + dj]
                        corners.append(vid(p))
                    if sgn < 0:
                        corners = corners[::-1]
                    quads.append(corners)
    V = np.array(verts, dtype=np.float64)
    V = V / np.linalg.norm(V, axis=1, keepdims=True) * radius
    return V, np.array(quads, dtype=np.int64)


def region_frame(cage: "Cage", name: str) -> tuple:
    """(point, outward unit normal) at the middle of a cage's named region (Cage.region_frame): craft.region_frame."""
    return cage.region_frame(name)


def region_tool(cage: "Cage", name: str, out: float = 1.0, depth: float = 2.0, label: str = ""):
    """A closed solid that follows a cage's named region (Cage.region_tool): craft.region_tool."""
    return cage.region_tool(name, out=out, depth=depth, label=label)


def voxel_cage(cells, size: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """A closed quad cage round a set of unit cubes {(i, j, k)}: every cube face with no cube behind it, outward.
    Any genus (a slab with two cells missing is genus 2); vertices where the surface turns are extraordinary."""
    cells = {tuple(int(x) for x in c) for c in cells}
    verts, index, quads = [], {}, []

    def vid(p):
        key = tuple(int(x) for x in p)
        if key not in index:
            index[key] = len(verts)
            verts.append(key)
        return index[key]
    for c in sorted(cells):
        for axis in range(3):
            for sgn in (-1, 1):
                nb = list(c)
                nb[axis] += sgn
                if tuple(nb) in cells:
                    continue
                u, w = (axis + 1) % 3, (axis + 2) % 3
                corners = []
                for du, dw in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    p = list(c)
                    p[axis] += 1 if sgn > 0 else 0
                    p[u] += du
                    p[w] += dw
                    corners.append(vid(p))
                quads.append(corners if sgn > 0 else corners[::-1])
    return np.array(verts, dtype=np.float64) * size, np.array(quads, dtype=np.int64)


def fit_cage(cage: Cage, targets_fn, rounds: int = 6, smooth: float = 0.02, k: int = 5) -> np.ndarray:
    """Fit a closed cage's points so its limit surface follows a target surface. targets_fn(points (n, 3)) -> the
    closest points on the target. Each round: sample the limit surface, find the targets, solve the cage by least
    squares with an umbrella (Laplacian) penalty. Returns the new V (also set on the cage)."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    W = cage.sample_operator(k)
    nV = len(cage.V)
    # umbrella Laplacian of the cage
    rows, cols = [], []
    for f in cage.F:
        for i in range(4):
            rows += [f[i], f[(i + 1) % 4]]
            cols += [f[(i + 1) % 4], f[i]]
    A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(nV, nV))
    A.data[:] = 1.0
    deg = np.asarray(A.sum(1)).ravel()
    Lap = sp.identity(nV) - sp.diags(1 / np.maximum(deg, 1)) @ A
    V = cage.V.copy()
    for _ in range(rounds):
        S = W @ V
        T = targets_fn(S)
        lam = smooth * W.shape[0] / nV
        N = (W.T @ W + lam * (Lap.T @ Lap)).tocsc()
        rhs = W.T @ T + lam * (Lap.T @ (Lap @ V))
        lu = spl.splu(N)
        V = np.column_stack([lu.solve(rhs[:, d]) for d in range(3)])
    cage.V = V
    return V



def note_tier(what: str) -> None:
    note(f"{what}: sculpted surface (subdivision cage to NURBS); its handles are parameters, its shape between them "
         "is the cage's")


# ── the skin route: a section stack fitted as one B-spline grid ───────────────────────────────────────────────────
#
# A loft through 60-70-point periodic splines makes one heavy face per pair of sections, and "offsets" built as
# independent lofts of nudged sections share faces with each other, so booleans between bands fail. Here the stack
# is sampled in numpy, one bicubic grid is fitted to it (the crown at the middle of the parameter square, the lowest
# section on the circle DISK_R), and every offset is the same grid offset along its normal: a shell is three faces
# (outside, inside, rim), a band is three faces clipped by its region, and no two offsets share a face.

def _section_points(s: dict, th: np.ndarray) -> np.ndarray:
    """Points of one section dict ({z, a, b, n, cx, cy, squash, rotate}) at superellipse parameters th: (len(th), 3).
    The same law as surfaces.superellipse, vectorised; every section is sampled at the same parameters, so the
    meridians (lines of constant th) never twist."""
    a, b, n = float(s["a"]), float(s["b"]), float(s.get("n", 2.0))
    ct, st = np.cos(th), np.sin(th)
    x = a * np.sign(ct) * np.abs(ct) ** (2.0 / n)
    y = b * np.sign(st) * np.abs(st) ** (2.0 / n)
    sq = float(s.get("squash", 0.0) or 0.0)
    if sq:
        y = np.where(x > 0, y * (1 - sq * (x / a) ** 2), y)
    r = math.radians(float(s.get("rotate", 0.0) or 0.0))
    c, si = math.cos(r), math.sin(r)
    x, y = x * c - y * si, x * si + y * c
    return np.stack([x + float(s.get("cx", 0.0) or 0.0), y + float(s.get("cy", 0.0) or 0.0),
                     np.full_like(th, float(s["z"]))], axis=1)


def _ext_weight(tau: np.ndarray, tb: float) -> np.ndarray:
    """The integral of a smoothstep rising from 0 at tau = 0 to 1 at tau = tb (a C1 blend between two directions)."""
    x = np.clip(tau / tb, 0, None)
    return np.where(x <= 1, tb * (x ** 3 - x ** 4 / 2), tb * 0.5 + (tau - tb))


@dataclass
class Skin:
    """An organic skin as one exact B-spline grid C (n x n poles), trimmed by the circle `radius` of its parameter
    square. The circle is the lowest section; the middle of the square is the crown. Offsets are the same grid offset
    along its normal (offset_grid), cached, so the outside, the inside and every band share no faces.

        skin = subd.skin_from_sections(secs, tip)       # skin.deviation: how far the fit is from the sections
        shell = skin.shell(3.0)                         # three faces
        pad = skin.band(2.0, region, depth=1.5)         # a raised pad: the layer -1.5 .. +2 mm, clipped to region
        lens = skin.layer(-9, -6) & window              # a lens that follows the inside, 6-9 mm in"""
    C: np.ndarray
    radius: float = DISK_R
    deviation: dict | None = None
    label: str = "skin"

    def __post_init__(self):
        self._off: dict = {}

    def offset(self, d: float) -> np.ndarray:
        """The grid of the skin offset by d mm along its outward normal (negative: inward)."""
        k = round(float(d), 4)
        if k == 0:
            return self.C
        if k not in self._off:
            self._off[k] = offset_grid(self.C, k)
        return self._off[k]

    def ray(self, origin, direction, d: float = 0.0):
        """Where a ray from origin along direction first meets the skin offset by d: (point, outward unit normal).
        The surface is the whole grid (its margin past the trim included), so aim inside the trimmed skin."""
        from build123d import Vector
        from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        face = grid_face(self.offset(d))
        inter = BRepIntCurveSurface_Inter()
        inter.Init(face.wrapped, gp_Lin(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, direction))), 1e-7)
        best = None
        while inter.More():
            if inter.W() > 1e-6 and (best is None or inter.W() < best[0]):
                p = inter.Pnt()
                best = (inter.W(), np.array([p.X(), p.Y(), p.Z()]))
            inter.Next()
        need(best is not None, "Skin.ray: the ray misses the skin", "Aim the ray at the skin.", ["origin", "direction"])
        p = best[1]
        nv = face.normal_at(Vector(*p))
        nrm = np.array([nv.X, nv.Y, nv.Z])
        nrm /= np.linalg.norm(nrm) or 1.0
        c = self.C.reshape(-1, 3).mean(0)
        if np.dot(nrm, p - c) < 0:                                       # outward: away from the cage's middle
            nrm = -nrm
        return tuple(float(x) for x in p), tuple(float(x) for x in nrm)

    def layer(self, lo: float, hi: float, label: str = ""):
        """The solid between the skin offset by lo and by hi (lo < hi, mm, + outward): three faces."""
        need(hi - lo > 0.05, f"subd.Skin.layer: hi ({hi:g}) must be above lo ({lo:g})", "Give lo < hi.", ["lo", "hi"])
        return trimmed_shell_solid(self.offset(hi), self.offset(lo), self.radius, label=label or self.label)

    def shell(self, wall: float, label: str = ""):
        """The skin and its inside, wall mm in along the normal, joined at the rim: a closed solid of three faces."""
        need(wall > 0, "subd.Skin.shell: the wall must be positive", "Give a wall thickness in mm.", ["wall"])
        return self.layer(-float(wall), 0.0, label)

    def band(self, amount: float, region, depth: float = 1.0):
        """A pad, rim or trim strip that follows the skin: the layer from depth mm under the skin to amount mm over
        it, clipped to region (a solid, or a list of solids united first, so regions with the same amount make one
        band and never share a face). Union it with the shell; keep depth under the wall."""
        from ._common import attempt, one
        need(amount > 0 and depth > 0, "subd.Skin.band: amount and depth must be positive",
             "Give the band's height over the skin and its root depth in mm.", ["amount", "depth"])
        if isinstance(region, (list, tuple)):
            reg = region[0]
            for r in region[1:]:
                reg = reg + r
            region = reg
        lay = self.layer(-float(depth), float(amount))
        return attempt("Skin.band", [("clip", lambda: one(lay & region))],
                       "The region does not reach the skin; move or enlarge it.", ["region"])


def skin_from_sections(sections: list[dict], tip=None, n: int = 18, radius: float = DISK_R, around: int = 120,
                       along: int = 44, smooth: float = 2e-5, label: str = "skin") -> Skin:
    """Fit one B-spline grid (n x n poles) to a section stack (organic.profile_sections, helmet_fullface()["sections"],
    dome_sections: [{z, a, b, n, cx, cy, squash, rotate}, ...] rising in z) closed by tip (x, y, z) above the last
    section. The stack is sampled in numpy (around x along points on the meridians), mapped onto a disk of the grid's
    parameter square (the crown at its middle, the lowest section on the circle `radius`), carried a little past the
    lowest section (turning to straight down, so the trimmed skin has a smooth margin) and fitted in one sparse solve.

    Returns a Skin whose .deviation is measured: {"max_mm", "mean_mm", "p95_mm", "samples"} over the sampled section
    points inside the trim (distance from each section point to the surface at its parameters, an upper bound on the
    true distance). It is also left as a craft note. A finer grid (n 20-24) follows tighter curvature."""
    from scipy.interpolate import CubicSpline
    need(len(sections) >= 3, "skin_from_sections needs at least 3 sections", "Add sections.", ["sections"])
    zs = [float(s["z"]) for s in sections]
    need(all(b > a for a, b in zip(zs, zs[1:])), "skin_from_sections: sections must rise in z",
         "Sort the sections by z.", ["sections"])
    need(tip is not None, "skin_from_sections: the stack needs a tip (a closed crown)",
         "Give tip=(x, y, z) above the last section, as profile_sections(crown=...) returns.", ["tip"])
    n = int(n)
    need(8 <= n <= 40, f"skin_from_sections: n = {n} is outside 8-40", "Use n between 12 and 24.", ["n"])
    th = np.linspace(-math.pi, math.pi, int(around), endpoint=False)
    M = np.stack([_section_points(s, th) for s in sections] + [np.tile(np.asarray(tip, float), (len(th), 1))])
    # M: (K + 1, around, 3), bottom to tip. Meridian parameter rho: 1 at the lowest section, 0 at the tip, by chord
    seg = np.linalg.norm(np.diff(M, axis=0), axis=2)
    cum = np.vstack([np.zeros((1, len(th))), np.cumsum(seg, axis=0)])
    rho = 1.0 - cum / cum[-1]
    corner = math.sqrt(0.5) / radius                                     # rho at the parameter square's corners
    rr = np.r_[np.linspace(0.0, 1.0, int(along)), np.linspace(1.0, corner + 0.02, max(6, int(along) // 4))[1:]]
    P = np.empty((len(rr), len(th), 3))
    inside = rr <= 1.0
    tau = rr[~inside] - 1.0
    W = _ext_weight(tau, 0.15)[:, None]
    for j in range(len(th)):
        cs = CubicSpline(rho[::-1, j], M[::-1, j, :], bc_type="natural")
        P[inside, j] = cs(rr[inside])
        T = cs(1.0, 1)                                                   # leave along the tangent, then straight down
        D = np.array([0.0, 0.0, -np.linalg.norm(T)])
        P[~inside, j] = cs(1.0) + T * (tau[:, None] - W) + D * W
    R, TH = np.meshgrid(rr, th, indexing="ij")
    s = 0.5 + radius * R * np.cos(TH)
    t = 0.5 + radius * R * np.sin(TH)
    keep = (s >= 0) & (s <= 1) & (t >= 0) & (t <= 1)
    w = np.maximum(R, 0.08)                                              # polar samples crowd at the crown
    C = fit_grid(P[keep], s[keep], t[keep], n, n, smooth=smooth, weights=w[keep])
    ins = keep & (R <= 1.0)
    d = np.linalg.norm(grid_eval(C, s[ins], t[ins]) - P[ins], axis=1)
    dev = {"max_mm": round(float(d.max()), 3), "mean_mm": round(float(d.mean()), 3),
           "p95_mm": round(float(np.percentile(d, 95)), 3), "samples": int(d.size)}
    note(f"skin_from_sections: the {label} is one {n} x {n} B-spline grid fitted to {len(sections)} sections; "
         f"deviation from the sections max {dev['max_mm']:g} mm, mean {dev['mean_mm']:g} mm")
    return Skin(C, float(radius), dev, label)
