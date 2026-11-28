"""Topology optimisation by SIMP: where material carries the load, and where it does not (runs in the FEA engine's
Python: NumPy and SciPy).

    out = optimise(problem, volfrac=0.5, rmin=2.4)

Minimum compliance (the stiffest layout) for a given amount of material, by the method of Bendsøe and Sigmund
(Topology Optimization, 2003) as written down in Sigmund's 99 lines (2001) and Andreassen, Clausen, Schevenels,
Lazarov and Sigmund's 88 lines (2011):

* every element e has a density x_e between 0 and 1 and the stiffness E_min + x_e^p (E_0 - E_min), with the
  penalty p = 3 making half-dense material a poor trade, so the result is mostly solid or empty;
* a filter of radius rmin (the density filter of Bruns and Tortorelli 2001 and Bourdin 2001, or Sigmund's
  sensitivity filter) removes checkerboards and sets the smallest member;
* the update is the optimality criteria method with a move limit, the multiplier of the volume found by bisection.

`problem` is anything with: `n` elements, `vol` (n,) element volumes, `centres` (n, dim) and
`solve(E) -> (compliance, ce)`, where E (n,) is each element's stiffness relative to solid and ce (n,) its strain
energy at unit stiffness, so that compliance = sum(E * ce). Two are here and in form/topo/mesh3d.py: `Grid2D`, the
structured plane-stress grid of the published benchmarks (the MBB beam and the cantilever), and the tetrahedral
mesh of a design's strength study. Both run through this one loop, so the benchmark verifies the loop the product
uses (form/topo/verify.py).

Elements may be passive: `solid` ones stay at 1 (the faces that carry loads and supports, a rim that must stay),
`void` ones at 0. The volume fraction counts every element, passive ones too.
"""
from __future__ import annotations

import time

import numpy as np
import scipy.sparse as sp_
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree

EMIN = 1e-9
MOVE = 0.2


def filter_matrix(centres: np.ndarray, rmin: float) -> sp_.csr_matrix:
    """H[i, j] = max(0, rmin - distance between the centres of elements i and j)."""
    tree = cKDTree(centres)
    pairs = tree.query_pairs(rmin, output_type="ndarray")
    d = np.linalg.norm(centres[pairs[:, 0]] - centres[pairs[:, 1]], axis=1)
    w = np.maximum(rmin - d, 0.0)
    n = len(centres)
    i = np.concatenate([pairs[:, 0], pairs[:, 1], np.arange(n)])
    j = np.concatenate([pairs[:, 1], pairs[:, 0], np.arange(n)])
    return sp_.csr_matrix((np.concatenate([w, w, np.full(n, rmin)]), (i, j)), shape=(n, n))


def optimise(problem, volfrac: float, rmin: float, penal: float = 3.0, ft: str = "density", move: float = MOVE,
             max_iter: int = 200, tol: float = 0.01, solid=None, void=None, on_iter=None, cancelled=None,
             emin: float = EMIN, budget_s: float | None = None) -> dict:
    """Returns {"x" (design densities), "density" (the physical, filtered densities the stiffness used),
    "compliance", "history": [{"iteration", "compliance", "volume", "change"}], "iterations", "converged",
    "stopped", "seconds"}. on_iter(record, density) is called once before the first iteration (iteration 0, the even
    start, no compliance yet) and after every iteration; cancelled() stops the loop."""
    if ft not in ("density", "sensitivity"):
        raise ValueError("ft is \"density\" or \"sensitivity\"")
    n, v = problem.n, np.asarray(problem.vol, float)
    vtot = float(v.sum())
    solid = np.zeros(n, bool) if solid is None else np.asarray(solid, bool)
    void = np.zeros(n, bool) if void is None else np.asarray(void, bool)
    free = ~(solid | void)
    need = float(v[solid].sum()) / vtot
    if need >= volfrac - 1e-9:
        raise ValueError(f"The parts that must stay solid are {need * 100:.0f} % of the volume, which is not below the "
                         f"{volfrac * 100:.0f} % asked for.")
    H = filter_matrix(np.asarray(problem.centres, float), float(rmin))
    Hv = H @ sp_.diags(v)                                # volume-weighted, for elements of different sizes
    Hs = np.asarray(Hv.sum(axis=1)).ravel()

    def physical(x):
        return np.asarray(Hv @ x).ravel() / Hs if ft == "density" else x
    x = np.full(n, (volfrac * vtot - v[solid].sum()) / max(v[free].sum(), 1e-300))
    x[solid], x[void] = 1.0, 0.0
    xp = physical(x)
    history, t0, stopped, change = [], time.perf_counter(), "", 1.0
    if on_iter is not None:                              # where it starts: the material spread evenly
        on_iter({"iteration": 0, "compliance": None, "volume": float(v @ xp) / vtot, "change": None, "seconds": 0.0}, xp)
    c = float("nan")
    for it in range(1, int(max_iter) + 1):
        if cancelled is not None and cancelled():
            stopped = "cancelled"
            break
        E = emin + xp ** penal * (1.0 - emin)
        c, ce = problem.solve(E)
        dc = -penal * (1.0 - emin) * xp ** (penal - 1) * ce
        dv = v.copy()
        if ft == "density":
            dc = v * np.asarray(H.T @ (dc / Hs)).ravel()
            dv = v * np.asarray(H.T @ (dv / Hs)).ravel()
        else:
            dc = np.asarray(Hv @ (x * dc / v)).ravel() / Hs / np.maximum(1e-3, x) * 1.0
        dc = np.minimum(dc, 0.0)
        l1, l2 = 0.0, 1e9
        while (l2 - l1) / (l1 + l2) > 1e-3:
            lm = 0.5 * (l1 + l2)
            xn = np.clip(x * np.sqrt(-dc / dv / lm), np.maximum(0.0, x - move), np.minimum(1.0, x + move))
            xn[solid], xn[void] = 1.0, 0.0
            xpn = physical(xn)
            if float(v @ xpn) > volfrac * vtot:
                l1 = lm
            else:
                l2 = lm
        change = float(np.abs(xn - x)[free].max()) if free.any() else 0.0
        x, xp = xn, xpn
        rec = {"iteration": it, "compliance": float(c), "volume": float(v @ xp) / vtot, "change": change,
               "seconds": round(time.perf_counter() - t0, 2)}
        history.append(rec)
        if on_iter is not None:
            on_iter(rec, xp)
        if change <= tol:
            break
        if budget_s is not None and time.perf_counter() - t0 > budget_s:
            stopped = f"the time limit of {budget_s:.0f} s"
            break
    else:
        stopped = f"the limit of {max_iter} iterations"
    return {"x": x, "density": xp, "compliance": float(c), "history": history, "iterations": len(history),
            "converged": not stopped and change <= tol, "stopped": stopped, "seconds": round(time.perf_counter() - t0, 2),
            "volume": float(v @ xp) / vtot, "grey": float((v * 4 * xp * (1 - xp)).sum() / vtot)}


# ---- the published benchmarks: a structured grid of plane-stress squares -------------------------------------------

def _ke(nu: float) -> np.ndarray:
    """The 8 x 8 stiffness of a unit square, four nodes, plane stress, E = 1 (Sigmund 2001)."""
    k = np.array([1 / 2 - nu / 6, 1 / 8 + nu / 8, -1 / 4 - nu / 12, -1 / 8 + 3 * nu / 8,
                  -1 / 4 + nu / 12, -1 / 8 - nu / 8, nu / 6, 1 / 8 - 3 * nu / 8])
    return 1 / (1 - nu ** 2) * np.array([
        [k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7]], [k[1], k[0], k[7], k[6], k[5], k[4], k[3], k[2]],
        [k[2], k[7], k[0], k[5], k[6], k[3], k[4], k[1]], [k[3], k[6], k[5], k[0], k[7], k[2], k[1], k[4]],
        [k[4], k[5], k[6], k[7], k[0], k[1], k[2], k[3]], [k[5], k[4], k[3], k[2], k[1], k[0], k[7], k[6]],
        [k[6], k[3], k[4], k[1], k[2], k[7], k[0], k[5]], [k[7], k[2], k[1], k[4], k[3], k[6], k[5], k[0]]])


class Grid2D:
    """nelx x nely unit squares, numbered down each column from the top left, as in the 88 lines. case "mbb": half
    of the MBB beam (a unit load down at the top left, the left edge on rollers, the bottom right corner held
    vertically). case "cantilever": the left edge fixed, a unit load down at the middle of the right edge."""

    def __init__(self, nelx: int, nely: int, case: str = "mbb", nu: float = 0.3):
        self.nelx, self.nely, self.case = int(nelx), int(nely), case
        nx, ny = self.nelx, self.nely
        self.n = nx * ny
        self.vol = np.ones(self.n)
        ex, ey = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
        self.centres = np.column_stack([ex.ravel() + 0.5, ey.ravel() + 0.5])
        self.KE = _ke(nu)
        n1 = (ny + 1) * ex.ravel() + ey.ravel()
        n2 = (ny + 1) * (ex.ravel() + 1) + ey.ravel()
        self.edof = np.column_stack([2 * n1 + 2, 2 * n1 + 3, 2 * n2 + 2, 2 * n2 + 3, 2 * n2, 2 * n2 + 1, 2 * n1, 2 * n1 + 1])
        self.iK = np.kron(self.edof, np.ones((8, 1), int)).ravel()
        self.jK = np.kron(self.edof, np.ones((1, 8), int)).ravel()
        self.ndof = 2 * (nx + 1) * (ny + 1)
        f = np.zeros(self.ndof)
        if case == "mbb":
            f[1] = -1.0
            fixed = np.union1d(np.arange(0, 2 * (ny + 1), 2), [self.ndof - 1])
        elif case == "cantilever":
            f[2 * ((ny + 1) * nx + ny // 2) + 1] = -1.0
            fixed = np.arange(0, 2 * (ny + 1))
        else:
            raise ValueError("case is \"mbb\" or \"cantilever\"")
        self.f = f
        self.free = np.setdiff1d(np.arange(self.ndof), fixed)

    def solve(self, E: np.ndarray):
        sK = (self.KE.ravel()[None, :] * E[:, None]).ravel()
        K = sp_.coo_matrix((sK, (self.iK, self.jK)), shape=(self.ndof, self.ndof)).tocsc()
        K = ((K + K.T) * 0.5).tocsc()
        u = np.zeros(self.ndof)
        u[self.free] = splu(K[self.free][:, self.free].tocsc()).solve(self.f[self.free])
        ue = u[self.edof]
        ce = np.einsum("ei,ij,ej->e", ue, self.KE, ue)
        return float(E @ ce), ce

    def image(self, density: np.ndarray) -> np.ndarray:
        """(nely, nelx), row 0 at the top."""
        return np.asarray(density).reshape(self.nelx, self.nely).T
