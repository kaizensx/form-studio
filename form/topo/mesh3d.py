"""The topology problem on a design: the tetrahedral mesh, supports, loads and material of a static strength study
(form/fea/core.py), with one density per tetrahedron (runs in the FEA engine's Python).

    prob = TetProblem(geo, spec, h=2.0)          # spec: the strength study's engine spec
    out = simp.optimise(prob, volfrac, rmin, solid=prob.keep(...))

The elements are the strength study's own (quadratic tetrahedra, form/fea/solve.py): the stiffness is assembled with
each element's modulus scaled by its density, and solved by the same solvers. One mesh is used for the whole
optimisation (no refinement while the layout moves); the reconstructed design is then studied again with the
refining solver, which is the number that counts.

Non-design regions: `keep()` marks the elements at the faces that carry supports and loads (and, when a pull
direction is given, a rim along the side walls) as solid; they are never removed.

A pull direction makes the layout 2.5D: `centres` are flattened along it, so the filter averages each element with
everything above and below it and the density cannot change along the pull. That is what lets the result be
written as pockets cut along that direction (form/topo/recon.py).

`Sampler` reads a density field as a picture across the pull direction, on the same grid for every iteration.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp_
from scipy.spatial import cKDTree

from ..fea import core
from ..fea import mesh as mesh_mod
from ..fea import solve as S

PAIRS_MAX = 40_000_000       # filter neighbours; above this the mesh is too fine for the thickness along the pull
EMIN_3D = 1e-6               # void stiffness on the tetrahedral mesh (the iterative solver needs a bounded contrast)


class TopologyError(RuntimeError):
    def __init__(self, message: str, hint: str = "", kind: str = "topology"):
        super().__init__(message)
        self.hint, self.kind = hint, kind


def unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise TopologyError("The pull direction has no length.")
    return v / n


def frame(pull) -> tuple:
    """(e1, e2, a): a right-handed frame with a along the pull direction."""
    a = unit(pull)
    ref = np.eye(3)[int(np.argmin(np.abs(a)))]
    if abs(a[2]) > 0.999:                                # the usual case: looking down z, keep x and y as they are
        e1 = np.array([1.0, 0.0, 0.0])
    else:
        e1 = unit(np.cross(ref, a))
    e2 = np.cross(a, e1)
    return e1, e2, a


class TetProblem:
    def __init__(self, geo, spec: dict, h: float, pull=None, cancelled=None):
        self.geo, self.spec, self.h = geo, spec, float(h)
        self.cancelled = cancelled
        self.m = mesh_mod.generate(geo, self.h)
        self.faces = core._resolve_faces(geo, self.m, spec)
        self.model = core.Model(geo, self.m, spec, self.faces)
        sp = self.model.sp
        self.n = sp.nel
        self.vol = np.asarray(sp.vol, float)
        self.real_centres = self.m.P[self.m.T].mean(axis=1)
        self.pull = None if pull is None else unit(pull)
        self.centres = self.real_centres if self.pull is None else \
            self.real_centres - np.outer(self.real_centres @ self.pull, self.pull)
        self.con = self.model.constraints()
        free = core._free_rigid_motions(self.model, self.con)
        if free:
            raise TopologyError(f"The supports leave {free} rigid motion{'s' if free > 1 else ''} free, so there is no "
                                "static problem to optimise.", "Fix the strength study's supports first.")
        self.f, self.loads = self.model.load_vector()
        if not np.any(self.f):
            raise TopologyError("No load: every load of the strength study is zero.")
        self.solves = 0
        self.method = ""
        self.u = None

    # ---- what simp.optimise calls -------------------------------------------------------------------------------
    def solve(self, E: np.ndarray):
        sp, md = self.model.sp, self.model
        K = sp.stiffness(md.lam * E, md.mu * E)
        system = S.System(sp, K, self.con, self.cancelled)
        u = system.expand(system.solve(system.restrict(self.f)))
        self.method = system.method
        self.solves += 1
        self.u = u
        ce = self.unit_energy(u)
        return float(E @ ce), ce

    def unit_energy(self, u: np.ndarray) -> np.ndarray:
        """Per element: twice the strain energy at full stiffness, so compliance = sum(E * unit_energy)."""
        sp, md = self.model.sp, self.model
        U = u.reshape(-1, 3)[sp.edofs]                               # (10, nel, 3)
        g = np.einsum("aei,ajeq->eqij", U, sp.dN, optimize=True)     # displacement gradient at the quadrature points
        eps = 0.5 * (g + np.swapaxes(g, 2, 3))
        tr = np.einsum("eqii->eq", eps)
        w = md.lam[:, None] * tr * tr + 2 * md.mu[:, None] * np.einsum("eqij,eqij->eq", eps, eps)
        return (w * sp.dx).sum(axis=1)

    # ---- non-design regions -----------------------------------------------------------------------------------------
    def keep(self, keep_mm: float, rim_mm: float = 0.0) -> np.ndarray:
        """Elements that stay solid: within keep_mm of a face that carries a support or a load, and (with a pull
        direction) within rim_mm of the side walls."""
        m, surf = self.m, self.model.surf
        ids = set()
        for group in list(self.faces["fixtures"]) + list(self.faces["loads"]):
            for part in (group if isinstance(group, tuple) else (group,)):
                ids.update(int(i) for i in part)
        solid = np.zeros(self.n, bool)
        tri = np.where(np.isin(m.face, sorted(ids)) & surf["outside"])[0]
        if len(tri):
            solid[surf["owner"][tri]] = True
            if keep_mm > 0:
                solid |= self._near(tri, keep_mm)
        if rim_mm > 0 and self.pull is not None:
            side = np.where(surf["outside"] & (np.abs(surf["normal"] @ self.pull) < 0.5))[0]
            if len(side):
                solid |= self._near(side, rim_mm)
        return solid

    def _near(self, tris: np.ndarray, d: float) -> np.ndarray:
        """Elements whose centre is within d of the given boundary triangles (sampled at corners, edges and centre)."""
        P = self.m.P[self.m.S[tris]]                                 # (n, 3, 3)
        pts = np.concatenate([P.reshape(-1, 3), P.mean(axis=1), (P[:, 0] + P[:, 1]) / 2, (P[:, 1] + P[:, 2]) / 2,
                              (P[:, 2] + P[:, 0]) / 2])
        dist, _ = cKDTree(pts).query(self.real_centres, distance_upper_bound=d + self.h)
        return dist <= d + 0.35 * self.h

    def check_filter(self, rmin: float) -> None:
        n = cKDTree(self.centres).count_neighbors(cKDTree(self.centres), rmin)
        if n > PAIRS_MAX:
            raise TopologyError(f"The filter would join {n:,} pairs of elements: the mesh is too fine for the part's "
                                "thickness along the pull direction.", "Use a larger element size (h) or a smaller "
                                "member size (rmin).")

    # ---- what a viewer draws ----------------------------------------------------------------------------------------
    def surface(self) -> dict:
        """The outside of the mesh, with the matrix that takes element densities to its vertices."""
        m, surf = self.m, self.model.surf
        tri = np.where(surf["outside"])[0]
        S_ = m.S[tri]
        used, inv = np.unique(S_.ravel(), return_inverse=True)
        T = inv.reshape(-1, 3)
        own = surf["owner"][tri]
        rows = T.ravel()
        cols = np.repeat(own, 3)
        A = sp_.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(used), self.n))
        A = sp_.diags(1.0 / np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1e-300)) @ A
        return {"positions": m.P[used].astype("<f4"), "indices": T.astype("<u4"), "to_vertices": A.tocsr()}


class Sampler:
    """A density field as a picture across the pull direction: pixel (j, i) is the mean density through the part at
    (u0 + (i + 0.5) px, v0 + (j + 0.5) px) in the frame (e1, e2, a)."""

    def __init__(self, prob: TetProblem, pull, px: float | None = None, pixels_max: int = 480):
        self.e1, self.e2, self.a = frame(pull)
        m = prob.m
        R = np.column_stack([self.e1, self.e2, self.a])
        Q = m.P @ R                                                  # vertices in the frame
        lo, hi = Q.min(axis=0), Q.max(axis=0)
        span = hi - lo
        px = float(px or prob.h / 4)
        px = max(px, max(span[0], span[1]) / pixels_max)
        self.px = px
        self.nu, self.nv = max(2, int(np.ceil(span[0] / px))), max(2, int(np.ceil(span[1] / px)))
        self.u0, self.v0 = lo[0], lo[1]
        self.w0, self.w1 = float(lo[2]), float(hi[2])
        nl = int(np.clip(np.ceil(span[2] / px), 1, 16))
        ws = lo[2] + (np.arange(nl) + 0.5) * span[2] / nl
        uu = self.u0 + (np.arange(self.nu) + 0.5) * px
        vv = self.v0 + (np.arange(self.nv) + 0.5) * px
        V, U, W = np.meshgrid(vv, uu, ws, indexing="ij")             # (nv, nu, nl)
        pts = (np.column_stack([U.ravel(), V.ravel(), W.ravel()])) @ R.T
        el = locate(m, prob.real_centres, pts)
        pix = np.repeat(np.arange(self.nv * self.nu), nl)
        ok = el >= 0
        M = sp_.csr_matrix((np.ones(int(ok.sum())), (pix[ok], el[ok])), shape=(self.nv * self.nu, prob.n))
        count = np.asarray(M.sum(axis=1)).ravel()
        self.inside = (count > 0).reshape(self.nv, self.nu)
        self.thickness = (count * span[2] / nl).reshape(self.nv, self.nu)
        self.M = (sp_.diags(1.0 / np.maximum(count, 1.0)) @ M).tocsr()
        self.layers = nl

    def image(self, density: np.ndarray) -> np.ndarray:
        return np.asarray(self.M @ density).reshape(self.nv, self.nu)

    def any(self, mask: np.ndarray) -> np.ndarray:
        """Pixels whose column holds an element of the mask."""
        return (np.asarray(self.M @ mask.astype(float)) > 1e-9).reshape(self.nv, self.nu)

    def grid(self) -> dict:
        return {"nu": self.nu, "nv": self.nv, "px": self.px, "u0": float(self.u0), "v0": float(self.v0),
                "w0": self.w0, "w1": self.w1, "e1": self.e1.tolist(), "e2": self.e2.tolist(), "pull": self.a.tolist(),
                "origin": [0.0, 0.0, 0.0],
                "note": "pixel (row j, column i) is at origin + (u0 + (i + 0.5) px) e1 + (v0 + (j + 0.5) px) e2"}


def locate(m, centres: np.ndarray, pts: np.ndarray, k: int = 12) -> np.ndarray:
    """The tetrahedron that holds each point, -1 where none does."""
    P, T = m.P, m.T
    o = P[T[:, 0]]
    B = np.stack([P[T[:, 1]] - o, P[T[:, 2]] - o, P[T[:, 3]] - o], axis=2)       # columns are the edge vectors
    Binv = np.linalg.inv(B)
    k = min(k, len(T))
    _, near = cKDTree(centres).query(pts, k=k)
    near = near.reshape(len(pts), k)
    out = np.full(len(pts), -1, dtype=np.int64)
    for j in range(k):
        todo = out < 0
        if not todo.any():
            break
        e = near[todo, j]
        lam = np.einsum("nij,nj->ni", Binv[e], pts[todo] - o[e])
        inside = (lam >= -1e-9).all(axis=1) & (lam.sum(axis=1) <= 1 + 1e-9)
        idx = np.where(todo)[0][inside]
        out[idx] = e[inside]
    return out
