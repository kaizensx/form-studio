"""Subdivision-surface cages to exact NURBS solids: the organic route from a quad cage to a STEP solid.

Two kinds of cage, one idea: a coarse quad net whose smooth limit surface is the part's skin, edited by moving the
net's points (directly, or through named handles that are a design's parameters).

* An open **grid cage** (nu x nv points, a disk-like skin: a helmet, a mask, a sculpted shell) is evaluated as a
  clamped uniform bicubic B-spline: the Catmull-Clark limit inside, its border pinned to the cage's border. One grid is
  one exact B-spline surface, C2 everywhere inside (smoother than G1). A shell is two grids, the skin and its inside
  (the skin offset by the wall), joined at the rim by ruled faces: a closed solid of six faces.
* A closed **quad cage** of any genus (a character prop, a sculpted grip) is subdivided by Catmull-Clark and turned
  into one bicubic Bezier patch per quad with Loop and Schaefer's approximation (ACC, 2008): exact (C2) where the net
  is regular, and at an extraordinary vertex (not four quads round it) the edge points round it are put in one tangent
  plane, so the skin is G1 at the vertex and within a measured angle along the patch borders next to it
  (seam_angles() reports the worst). The patches are sewn into a closed OCCT solid.

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


def _sew(faces, tol: float = 1e-3, label: str = "body"):
    """Sew OCCT faces into a closed solid (build123d Solid), oriented outward. Raises a RecipeError if it leaks."""
    from build123d import Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    sew = BRepBuilderAPI_Sewing(tol)
    for f in faces:
        sew.Add(f.wrapped if hasattr(f, "wrapped") else f)
    sew.Perform()
    shape = sew.SewedShape()
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    need(ex.More(), f"subd: the {label}'s faces did not sew into a shell", "Check the cage for gaps.", ["cage"])
    shell = TopoDS.Shell(ex.Current())
    ms = BRepBuilderAPI_MakeSolid(shell)
    fix = ShapeFix_Solid(ms.Solid())
    fix.Perform()
    s = Solid(fix.Solid())
    if s.volume < 0:
        s = Solid(s.wrapped.Reversed())
    need(sew.NbFreeEdges() == 0, f"subd: the {label} is not closed ({sew.NbFreeEdges()} free edges after sewing)",
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


# ── closed quad cages: Catmull-Clark and ACC bicubic patches ──────────────────────────────────────────────────────

def catmull_clark(V: np.ndarray, F: list) -> tuple[np.ndarray, np.ndarray]:
    """One Catmull-Clark step on a closed polygon mesh (any polygons). Returns (V, quads)."""
    V = np.asarray(V, dtype=np.float64)
    F = [list(f) for f in F]
    nV = len(V)
    fp = np.array([V[f].mean(0) for f in F])
    edges = {}
    for fi, f in enumerate(F):
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            edges.setdefault((min(a, b), max(a, b)), []).append(fi)
    need(all(len(x) == 2 for x in edges.values()), "subd.catmull_clark: the cage is not closed (an edge has one face)",
         "Close the cage, or use a grid cage for an open skin.", ["cage"])
    ekeys = list(edges)
    eidx = {e: nV + len(F) + i for i, e in enumerate(ekeys)}
    ep = np.array([(V[a] + V[b] + fp[edges[(a, b)][0]] + fp[edges[(a, b)][1]]) / 4 for a, b in ekeys])
    # vertex points
    vf = [[] for _ in range(nV)]
    ve = [[] for _ in range(nV)]
    for fi, f in enumerate(F):
        for a in f:
            vf[a].append(fi)
    for a, b in ekeys:
        ve[a].append((a, b))
        ve[b].append((a, b))
    newV = np.empty_like(V)
    for i in range(nV):
        n = len(vf[i])
        Fa = fp[vf[i]].mean(0)
        R = np.mean([(V[a] + V[b]) / 2 for a, b in ve[i]], axis=0)
        newV[i] = (Fa + 2 * R + (n - 3) * V[i]) / n
    Vout = np.vstack([newV, fp, ep])
    Q = []
    for fi, f in enumerate(F):
        c = nV + fi
        m = len(f)
        for k in range(m):
            a, b, z = f[k], f[(k + 1) % m], f[k - 1]
            Q.append([a, eidx[(min(a, b), max(a, b))], c, eidx[(min(z, a), max(z, a))]])
    return Vout, np.array(Q, dtype=np.int64)


def acc_operator(nV: int, Q: np.ndarray):
    """Sparse matrix M (len(Q)*16 x nV): the 16 Bezier control points of each quad's ACC patch, as linear combinations
    of the cage points (before the tangent-plane step). Patch q, row r, column c is row q*16 + r*4 + c."""
    import scipy.sparse as sp
    Q = np.asarray(Q)
    m = len(Q)
    val = np.zeros(nV, dtype=np.int64)
    nbr = [set() for _ in range(nV)]
    diag = [[] for _ in range(nV)]
    for f in Q:
        for i in range(4):
            v = f[i]
            val[v] += 1
            nbr[v].add(f[(i + 1) % 4])
            nbr[v].add(f[(i - 1) % 4])
            diag[v].append(f[(i + 2) % 4])
    rows, cols, vals = [], [], []

    def put(row, combo):
        for c, w in combo.items():
            rows.append(row)
            cols.append(c)
            vals.append(w)

    def interior(f, i):
        v = f[i]
        n = val[v]
        d = {}
        for c, w in ((v, n), (f[(i + 1) % 4], 2), (f[(i - 1) % 4], 2), (f[(i + 2) % 4], 1)):
            d[c] = d.get(c, 0) + w / (n + 5)
        return d

    def limit(v):
        n = val[v]
        d = {v: n * n / (n * (n + 5))}
        for e in nbr[v]:
            d[e] = d.get(e, 0) + 4 / (n * (n + 5))
        for g in diag[v]:
            d[g] = d.get(g, 0) + 1 / (n * (n + 5))
        return d

    # interior points of every (face, corner), and which faces use each directed edge
    I = {}
    by_edge = {}
    for qi, f in enumerate(Q):
        for i in range(4):
            I[(qi, i)] = interior(f, i)
            by_edge.setdefault((f[i], f[(i + 1) % 4]), []).append((qi, i))
            by_edge.setdefault((f[i], f[(i - 1) % 4]), []).append((qi, i))

    def edge_pt(v, w):
        users = by_edge[(v, w)]
        out = {}
        for key in users:
            for c, x in I[key].items():
                out[c] = out.get(c, 0) + x / len(users)
        return out

    lim = {}
    for qi, f in enumerate(Q):
        a, b, c, d = (int(x) for x in f)
        base = qi * 16
        for (r, cc), combo in (((0, 0), lim.setdefault(a, limit(a))), ((0, 3), lim.setdefault(b, limit(b))),
                               ((3, 3), lim.setdefault(c, limit(c))), ((3, 0), lim.setdefault(d, limit(d))),
                               ((0, 1), edge_pt(a, b)), ((0, 2), edge_pt(b, a)), ((1, 3), edge_pt(b, c)),
                               ((2, 3), edge_pt(c, b)), ((3, 2), edge_pt(c, d)), ((3, 1), edge_pt(d, c)),
                               ((2, 0), edge_pt(d, a)), ((1, 0), edge_pt(a, d)),
                               ((1, 1), I[(qi, 0)]), ((1, 2), I[(qi, 1)]), ((2, 2), I[(qi, 2)]), ((2, 1), I[(qi, 3)])):
            put(base + r * 4 + cc, combo)
    return sp.csr_matrix((vals, (rows, cols)), shape=(m * 16, nV)), val


def tangent_planes(B: np.ndarray, Q: np.ndarray, valence: np.ndarray) -> np.ndarray:
    """Put the edge points round every extraordinary vertex into one plane through its limit point (the plane that
    fits them best), so the patches meet with one normal there (G1 at the vertex). B: (m, 4, 4, 3), changed copy."""
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
            p = np.array(key)
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


class Cage:
    """A closed quad cage (any genus): points V (n, 3) and quads F (m, 4), counter-clockwise seen from outside."""

    def __init__(self, V, F, levels: int = 0):
        V = np.asarray(V, dtype=np.float64)
        F = [list(f) for f in F]
        if any(len(f) != 4 for f in F) and levels == 0:
            levels = 1                           # one step makes any polygon mesh all quads
        for _ in range(levels):
            V, F = catmull_clark(V, F)
        self.V, self.F = V, np.asarray(F, dtype=np.int64)
        self._M = None

    @property
    def M(self):
        if self._M is None:
            self._M, self.valence = acc_operator(len(self.V), self.F)
        return self._M

    def patches(self, V=None, g1: bool = True) -> np.ndarray:
        """(m, 4, 4, 3) bicubic Bezier control points, one patch per quad."""
        M = self.M
        B = (M @ (self.V if V is None else V)).reshape(len(self.F), 4, 4, 3)
        return tangent_planes(B, self.F, self.valence) if g1 else B

    def extraordinary(self) -> int:
        _ = self.M
        return int(np.sum(self.valence != 4))

    def sample_operator(self, k: int = 4):
        """Sparse W (len(F) * k * k x nV): points of the limit surface on a k x k grid per patch (no tangent step)."""
        import scipy.sparse as sp
        t = np.linspace(0, 1, k)
        Bt = bernstein(t)                       # (k, 4)
        Wp = np.einsum("ar,bc->abrc", Bt, Bt).reshape(k * k, 16)      # rows: (v, u) samples; cols: r*4+c
        blk = sp.block_diag([sp.csr_matrix(Wp)] * len(self.F), format="csr")
        return blk @ self.M

    def solid(self, label: str = "body"):
        """The cage's limit surface as a closed OCCT solid of bicubic Bezier faces."""
        return patches_solid(self.patches(), label=label)


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
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.Geom import Geom_BezierSurface
    from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    faces = []
    for P in B:
        arr = TColgp_Array2OfPnt(1, 4, 1, 4)
        for r in range(4):
            for c in range(4):
                x, y, z = P[r, c]
                arr.SetValue(c + 1, r + 1, gp_Pnt(float(x), float(y), float(z)))
        faces.append(BRepBuilderAPI_MakeFace(Geom_BezierSurface(arr), 1e-7).Face())
    return _sew(faces, tol=1e-4, label=label)


def seam_angles(B: np.ndarray, Q: np.ndarray, samples: int = 7) -> dict:
    """Normal angle (degrees) across every patch border, sampled along it: the measured smoothness of an ACC skin.
    0 = tangent (G1). Returns worst, mean and the share of borders within 1 degree."""
    def normal(P, s, t):
        bs, bt = bernstein(np.array([s]))[0], bernstein(np.array([t]))[0]
        dbs = _dbern(s)
        dbt = _dbern(t)
        Su = np.einsum("r,c,rcx->x", bt, dbs, P)
        Sv = np.einsum("r,c,rcx->x", dbt, bs, P)
        n = np.cross(Su, Sv)
        return n / (np.linalg.norm(n) or 1)

    # border of patch q between corners i and i+1, and the (s, t) along it
    side = {0: lambda w: (w, 0.0), 1: lambda w: (1.0, w), 2: lambda w: (1 - w, 1.0), 3: lambda w: (0.0, 1 - w)}
    owner = {}
    for qi, f in enumerate(Q):
        for i in range(4):
            owner.setdefault((int(f[i]), int(f[(i + 1) % 4])), (qi, i))
    angles = []
    done = set()
    for (a, b), (qi, i) in owner.items():
        if (b, a) not in owner or (b, a) in done:
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
