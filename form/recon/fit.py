"""Fitting analytic surfaces (plane, cylinder, cone, sphere, torus) to mesh points with numpy and scipy.

Each fit starts from a closed-form estimate (normals give the axis, normal lines meet on the axis) and is refined by
least squares on the geometric distance. `Prim.dist` is the signed distance of points to the surface, `Prim.normal`
the unit normal of the surface at (near) those points, pointing away from the axis or centre (for a plane: `n`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

KINDS = ("plane", "cylinder", "cone", "sphere", "torus")


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / max(np.linalg.norm(v), 1e-300)


def _perp(a):
    """Two unit vectors perpendicular to a and to each other."""
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(np.cross(a, t))
    return u, np.cross(a, u)


@dataclass
class Prim:
    kind: str
    p: dict = field(default_factory=dict)          # o, a (axis or normal), r, R, half_angle, c
    rms: float = 0.0
    max: float = 0.0

    # cylindrical coordinates about the axis (o, a): axial s and radial rho, with the radial unit vector
    def _sr(self, P):
        o, a = self.p["o"], self.p["a"]
        d = P - o
        s = d @ a
        radial = d - s[:, None] * a
        rho = np.linalg.norm(radial, axis=1)
        return s, rho, radial / np.maximum(rho, 1e-300)[:, None]

    def dist(self, P: np.ndarray) -> np.ndarray:
        P = np.atleast_2d(P)
        k = self.kind
        if k == "plane":
            return (P - self.p["o"]) @ self.p["a"]
        if k == "sphere":
            return np.linalg.norm(P - self.p["o"], axis=1) - self.p["r"]
        s, rho, _ = self._sr(P)
        if k == "cylinder":
            return rho - self.p["r"]
        if k == "cone":
            al = self.p["half_angle"]
            return (rho - self.p["r"] - s * math.tan(al)) * math.cos(al)
        if k == "torus":
            return np.hypot(rho - self.p["R"], s) - self.p["r"]
        raise ValueError(k)

    def normal(self, P: np.ndarray) -> np.ndarray:
        P = np.atleast_2d(P)
        k = self.kind
        if k == "plane":
            return np.tile(self.p["a"], (len(P), 1))
        if k == "sphere":
            d = P - self.p["o"]
            return d / np.maximum(np.linalg.norm(d, axis=1), 1e-300)[:, None]
        s, rho, er = self._sr(P)
        a = self.p["a"]
        if k == "cylinder":
            return er
        if k == "cone":
            al = self.p["half_angle"]
            return er * math.cos(al) - a[None, :] * math.sin(al)
        if k == "torus":
            v = (rho - self.p["R"])[:, None] * er + s[:, None] * a[None, :]
            return v / np.maximum(np.linalg.norm(v, axis=1), 1e-300)[:, None]
        raise ValueError(k)

    def public(self) -> dict:
        out = {"kind": self.kind, "rms_mm": round(self.rms, 6), "max_mm": round(self.max, 6)}
        for k, v in self.p.items():
            out[k] = [round(float(x), 6) for x in v] if isinstance(v, np.ndarray) else round(float(v), 6)
        if "half_angle" in self.p:
            out["half_angle_deg"] = round(math.degrees(self.p["half_angle"]), 4)
        return out


def _finish(prim: Prim, P) -> Prim:
    d = prim.dist(P)
    prim.rms, prim.max = float(np.sqrt(np.mean(d * d))), float(np.abs(d).max())
    return prim


def fit_plane(P, N=None) -> Prim:
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    n = vt[-1]
    if N is not None and float((N @ n).sum()) < 0:
        n = -n
    return _finish(Prim("plane", {"o": c, "a": _unit(n)}), P)


def _axis_from_normals(N, cone=False):
    """Cylinder: normals are perpendicular to the axis (smallest eigenvector of N^T N). Cone: n.a is constant (smallest
    eigenvector of the covariance of the normals)."""
    M = np.cov(N.T) if cone else N.T @ N
    w, v = np.linalg.eigh(M)
    return _unit(v[:, 0])


def _axis_point(P, N, a):
    """The point (on the plane through the centroid perpendicular to a) nearest every normal line: they all meet the axis."""
    u, v = _perp(a)
    p2 = np.c_[P @ u, P @ v]
    n2 = np.c_[N @ u, N @ v]
    ln = np.linalg.norm(n2, axis=1)
    ok = ln > 1e-6
    if ok.sum() < 2:
        return None
    n2 = n2[ok] / ln[ok, None]
    p2 = p2[ok]
    # line i: points p2 + t n2; distance of x to it is |(x - p2) x n2|; normal of the line m = (-n2y, n2x)
    m = np.c_[-n2[:, 1], n2[:, 0]]
    A, b = m, np.einsum("ij,ij->i", m, p2)
    try:
        x, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    c = P.mean(axis=0)
    return x[0] * u + x[1] * v + (c @ a) * a


def _circle2(x, y):
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0], sol[1]
    r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0))
    return cx, cy, r


def _dangles(th, ph):
    """d a / d theta and d a / d phi for the axis a = _dir(theta, phi)."""
    return (np.array([math.cos(th) * math.cos(ph), math.cos(th) * math.sin(ph), -math.sin(th)]),
            np.array([-math.sin(th) * math.sin(ph), math.sin(th) * math.cos(ph), 0.0]))


def _jacobian(kind, x, P):
    """The analytic Jacobian of Prim.dist with respect to the packed parameters (o, theta, phi, sizes...).

    Vectorised over the points; scipy's finite differences cost (n + 1) evaluations per step and made the fits the
    slowest part of segmentation."""
    x = np.asarray(x, dtype=np.float64)
    o = x[:3]
    d = P - o
    if kind == "sphere":
        ln = np.maximum(np.linalg.norm(d, axis=1), 1e-300)
        return np.c_[-d / ln[:, None], -np.sign(x[3]) * np.ones(len(P))]
    th, ph = x[3], x[4]
    a = _dir(th, ph)
    dth, dph = _dangles(th, ph)
    s = d @ a
    radial = d - s[:, None] * a
    rho = np.maximum(np.linalg.norm(radial, axis=1), 1e-300)
    e = radial / rho[:, None]
    if kind == "cylinder":
        g_a = -s[:, None] * e
        return np.c_[-e, g_a @ dth, g_a @ dph, -np.sign(x[5]) * np.ones(len(P))]
    if kind == "cone":
        r, al = x[5], x[6]
        ca, ta = math.cos(al), math.tan(al)
        g_o = (-e + ta * a[None, :]) * ca
        g_a = (-s[:, None] * e - ta * d) * ca
        return np.c_[g_o, g_a @ dth, g_a @ dph, -ca * np.ones(len(P)), -(rho - r) * math.sin(al) - s * ca]
    if kind == "torus":
        R = abs(x[5])
        q = np.maximum(np.hypot(rho - R, s), 1e-300)
        cr, cs = (rho - R) / q, s / q
        g_o = -cr[:, None] * e - cs[:, None] * a[None, :]
        g_a = -(cr * s)[:, None] * e + cs[:, None] * d
        return np.c_[g_o, g_a @ dth, g_a @ dph, -cr * np.sign(x[5]), -np.sign(x[6]) * np.ones(len(P))]
    raise ValueError(kind)


def _refine(kind, x0, P, unpack):
    from scipy.optimize import least_squares

    def res(x):
        return unpack(x).dist(P)
    jac = (lambda x: _jacobian(kind, x, P)) if kind in ("cylinder", "cone", "sphere", "torus") else "2-point"
    try:
        sol = least_squares(res, x0, jac=jac, method="lm", max_nfev=12 * (len(x0) + 1), xtol=1e-10, ftol=1e-10)
        return _finish(unpack(sol.x), P)
    except Exception:
        return _finish(unpack(np.asarray(x0)), P)


def _ang(a):
    a = _unit(a)
    return np.array([math.acos(max(-1.0, min(1.0, a[2]))), math.atan2(a[1], a[0])])


def _dir(th, ph):
    return np.array([math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)])


def fit_cylinder(P, N) -> Prim | None:
    a = _axis_from_normals(N)
    o = _axis_point(P, N, a)
    if o is None:
        return None
    u, v = _perp(a)
    cx, cy, r = _circle2((P - o) @ u, (P - o) @ v)
    o = o + cx * u + cy * v
    th, ph = _ang(a)

    def unpack(x):
        return Prim("cylinder", {"o": x[:3], "a": _dir(x[3], x[4]), "r": abs(x[5])})
    pr = _refine("cylinder", np.r_[o, th, ph, r], P, unpack)
    return _canon(pr, P)


def fit_cone(P, N) -> Prim | None:
    a = _axis_from_normals(N, cone=True)
    o = _axis_point(P, N, a)
    if o is None:
        return None
    best = None
    for sgn in (1.0, -1.0):
        aa = a * sgn
        s = (P - o) @ aa
        rho = np.linalg.norm((P - o) - s[:, None] * aa, axis=1)
        if np.ptp(s) < 1e-9:
            continue
        t, r0 = np.polyfit(s, rho, 1)
        al = math.atan(t)
        th, ph = _ang(aa)

        def unpack(x):
            return Prim("cone", {"o": x[:3], "a": _dir(x[3], x[4]), "r": x[5], "half_angle": x[6]})
        pr = _refine("cone", np.r_[o, th, ph, r0, al], P, unpack)
        if best is None or pr.rms < best.rms:
            best = pr
    if best is None or abs(best.p["half_angle"]) < 1e-4 or abs(best.p["half_angle"]) > math.radians(89):
        return None
    return _canon(best, P)


def fit_sphere(P, N=None) -> Prim | None:
    A = np.c_[2 * P, np.ones(len(P))]
    sol, *_ = np.linalg.lstsq(A, (P * P).sum(axis=1), rcond=None)
    c = sol[:3]
    r = math.sqrt(max(sol[3] + c @ c, 0.0))

    def unpack(x):
        return Prim("sphere", {"o": x[:3], "r": abs(x[3])})
    return _refine("sphere", np.r_[c, r], P, unpack)


def _circle3(C):
    """Plane and circle through 3-D points: (centre, normal, radius, rms)."""
    m = C.mean(axis=0)
    _, _, vt = np.linalg.svd(C - m, full_matrices=False)
    n = vt[-1]
    u, v = vt[0], vt[1]
    cx, cy, r = _circle2((C - m) @ u, (C - m) @ v)
    c = m + cx * u + cy * v
    d = np.hypot(np.linalg.norm(C - c - ((C - c) @ n)[:, None] * n, axis=1) - r, (C - c) @ n)
    return c, n, r, float(np.sqrt(np.mean(d * d)))


def fit_torus(P, N) -> Prim | None:
    from scipy.optimize import minimize_scalar
    span = float(np.ptp(P, axis=0).max()) or 1.0
    best = None
    for sgn in (1.0, -1.0):
        def cost(r):
            return _circle3(P - sgn * r * N)[3]
        try:
            m = minimize_scalar(cost, bounds=(span * 1e-3, span * 5), method="bounded", options={"xatol": span * 1e-4, "maxiter": 60})
        except Exception:
            continue
        r = float(m.x)
        c, n, R, _ = _circle3(P - sgn * r * N)
        th, ph = _ang(n)

        def unpack(x):
            return Prim("torus", {"o": x[:3], "a": _dir(x[3], x[4]), "R": abs(x[5]), "r": abs(x[6])})
        pr = _refine("torus", np.r_[c, th, ph, R, r], P, unpack)
        if best is None or pr.rms < best.rms:
            best = pr
    if best is None or best.p["r"] >= best.p["R"]:            # spindle and horn tori are not handled
        return None
    return _canon(best, P)


def _canon(pr: Prim, P) -> Prim:
    """Move the axis point to the foot of the points' centroid and point the axis to +z, +y or +x first."""
    if "a" not in pr.p or pr.kind == "plane":
        return pr
    a = _unit(pr.p["a"])
    o = pr.p["o"]
    k = int(np.argmax(np.abs(a)))
    flip = a[k] < 0
    if flip:
        a = -a
        if pr.kind == "cone":
            pr.p["half_angle"] = -pr.p["half_angle"]
    if pr.kind in ("cylinder", "cone"):
        c = P.mean(axis=0)
        t = float((c - o) @ a)
        if pr.kind == "cone":
            pr.p["r"] = pr.p["r"] + t * math.tan(pr.p["half_angle"])
        o = o + t * a
    pr.p["o"], pr.p["a"] = o, a
    return _finish(pr, P)


def fit_on_axis(kind, P, o, a) -> Prim | None:
    """Fit a surface of revolution about a known axis line (o, a), then refine everything by least squares.

    A small patch of a cone or torus does not show its axis well, but a turned part has one axis for all its
    surfaces: the axis of a cylinder found earlier is a good guess."""
    a = _unit(a)
    d = P - o
    s = d @ a
    rho = np.linalg.norm(d - s[:, None] * a, axis=1)
    th, ph = _ang(a)
    if kind == "cylinder":
        x0 = np.r_[o, th, ph, rho.mean()]
        return _canon(_refine(kind, x0, P, lambda x: Prim("cylinder", {"o": x[:3], "a": _dir(x[3], x[4]), "r": abs(x[5])})), P)
    if kind == "cone":
        if np.ptp(s) < 1e-9:
            return None
        t, r0 = np.polyfit(s, rho, 1)
        x0 = np.r_[o, th, ph, r0, math.atan(t)]
        pr = _refine(kind, x0, P, lambda x: Prim("cone", {"o": x[:3], "a": _dir(x[3], x[4]), "r": x[5], "half_angle": x[6]}))
        return _canon(pr, P)
    if kind == "torus":
        cs, cr, r = _circle2(s, rho)
        x0 = np.r_[o + cs * a, th, ph, cr, r]
        pr = _refine(kind, x0, P, lambda x: Prim("torus", {"o": x[:3], "a": _dir(x[3], x[4]), "R": abs(x[5]), "r": abs(x[6])}))
        return None if pr.p["r"] >= pr.p["R"] else _canon(pr, P)
    if kind == "sphere":
        cs = float(np.mean(s))
        x0 = np.r_[o + cs * a, np.sqrt(np.mean(rho ** 2 + (s - cs) ** 2))]
        return _refine(kind, x0, P, lambda x: Prim("sphere", {"o": x[:3], "r": abs(x[3])}))
    return None


FITTERS = {"plane": fit_plane, "cylinder": fit_cylinder, "cone": fit_cone, "sphere": fit_sphere, "torus": fit_torus}


def _meets_axis(P, N, o, a) -> bool:
    """Do the normal lines of these points pass near the axis line (o, a), as they do on any surface of revolution
    about it? A cheap test before fitting about a borrowed axis."""
    c = np.cross(N, a)
    ln = np.linalg.norm(c, axis=1)
    ok = ln > 1e-3
    if ok.sum() < 3:
        return True
    d = np.abs(np.einsum("ij,ij->i", P[ok] - o, c[ok])) / ln[ok]
    return float(np.median(d)) <= max(0.05 * float(np.ptp(P, axis=0).max()), 0.05)


def _sane(pr: Prim | None) -> Prim | None:
    if pr is None or not np.isfinite(pr.rms):
        return None
    if pr.kind == "cone":                       # nearly flat or nearly straight: a plane or a cylinder, not a cone
        ha = abs(pr.p["half_angle"])
        if ha < math.radians(0.5) or ha > math.radians(85):
            return None
    return pr


def fit(kind: str, P, N, axes=(), good: float | None = None) -> Prim | None:
    """The best fit of `kind`: free, then (unless the free fit is already within `good`) about each known axis in
    `axes` ((o, a) pairs)."""
    cands = []
    try:
        cands.append(_sane(FITTERS[kind](P, N)))
    except (np.linalg.LinAlgError, ValueError, FloatingPointError):
        pass
    if good is not None and cands and cands[0] is not None and cands[0].max <= good:
        return cands[0]
    if kind != "plane":
        for o, a in axes:
            if not _meets_axis(P, N, o, a):
                continue
            try:
                cands.append(_sane(fit_on_axis(kind, P, o, a)))
            except (np.linalg.LinAlgError, ValueError, FloatingPointError):
                pass
    cands = [c for c in cands if c is not None]
    return min(cands, key=lambda c: c.max) if cands else None
