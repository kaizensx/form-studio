"""The numeric core of form.sketch2d: residuals of geometric constraints and a damped Gauss-Newton solver.

Unknowns are the free points' x and y and the circles' radii, in millimetres. Each constraint is a small function of a
few unknowns that is zero when the constraint holds; its Jacobian is taken by central differences over those few
unknowns only, so one iteration costs a few hundred scalar evaluations and one dense least-squares solve.

Steps are minimum-norm (numpy lstsq): unknowns no constraint pins down do not move, so an under-constrained sketch keeps
the shape it was drawn with instead of drifting. A step that makes the residual worse is halved (backtracking) and the
damping grows (Levenberg-Marquardt), so a start far from the answer still converges.

Plain Python and numpy: no kernel, no compiled solver to package.
"""
from __future__ import annotations

import math
import time

import numpy as np

TOL = 1e-9            # mm: a constraint holds when its residual is below this (squared sum below TOL**2 per row)
MAX_ITER = 60
H = 1e-7              # central-difference step (mm)


class Problem:
    """Unknowns plus residual functions. Built by Sketch.compile(); solved by solve()."""

    def __init__(self):
        self.x0: list[float] = []              # starting values of the unknowns
        self.names: list[str] = []
        self.rows: list[tuple] = []            # (fn, var indices, constraint id, count of residuals)

    def var(self, value: float, name: str) -> int:
        self.x0.append(float(value))
        self.names.append(name)
        return len(self.x0) - 1

    def add(self, fn, idx: list[int], cid: int, n: int = 1):
        """fn(vals) -> list of n residuals, where vals are the unknowns at idx (in order)."""
        self.rows.append((fn, list(idx), cid, n))

    @property
    def m(self) -> int:
        return sum(r[3] for r in self.rows)

    def residual(self, x) -> np.ndarray:
        out = []
        for fn, idx, _, _ in self.rows:
            out.extend(fn([x[i] for i in idx]))
        return np.asarray(out, dtype=np.float64)

    def jacobian(self, x) -> tuple[np.ndarray, np.ndarray]:
        n = len(x)
        F = np.empty(self.m)
        J = np.zeros((self.m, n))
        r = 0
        for fn, idx, _, k in self.rows:
            vals = [x[i] for i in idx]
            F[r:r + k] = fn(vals)
            for j, vi in enumerate(idx):
                if vi < 0:
                    continue
                a = vals[:]
                b = vals[:]
                a[j] += H
                b[j] -= H
                fa, fb = fn(a), fn(b)
                for q in range(k):
                    J[r + q, vi] += (fa[q] - fb[q]) / (2 * H)
            r += k
        return F, J


class Result:
    def __init__(self, x, ok, iters, residual, ms, rank, n, m, worst):
        self.x, self.ok, self.iters, self.residual, self.ms = x, ok, iters, residual, ms
        self.rank, self.n, self.m, self.worst = rank, n, m, worst

    @property
    def dof(self) -> int:
        """Degrees of freedom left: unknowns no constraint fixes (0 = fully constrained)."""
        return self.n - self.rank


def solve(prob: Problem, x0=None, max_iter: int = MAX_ITER, tol: float = TOL) -> Result:
    t0 = time.perf_counter()
    x = np.array(prob.x0 if x0 is None else x0, dtype=np.float64)
    n = len(x)
    if prob.m == 0:
        return Result(x, True, 0, 0.0, 0.0, 0, n, 0, [])
    F, J = prob.jacobian(x)
    cost = float(F @ F)
    lam = 0.0
    it = 0
    while it < max_iter and cost > tol * tol * max(1, prob.m):
        it += 1
        if lam:
            A = np.vstack([J, math.sqrt(lam) * np.eye(n)])
            b = np.concatenate([-F, np.zeros(n)])
        else:
            A, b = J, -F
        dx = np.linalg.lstsq(A, b, rcond=None)[0]
        # backtracking: halve the step until the residual drops
        step, better = 1.0, False
        for _ in range(12):
            xn = x + step * dx
            Fn = prob.residual(xn)
            cn = float(Fn @ Fn)
            if math.isfinite(cn) and cn < cost:
                better = True
                break
            step *= 0.5
        if not better:
            lam = max(lam * 10, 1e-6)
            if lam > 1e6:
                break
            continue
        x = xn
        lam = lam * 0.3 if lam > 1e-9 else 0.0
        F, J = prob.jacobian(x)
        cost = float(F @ F)
    ok = cost <= tol * tol * max(1, prob.m) * 100
    # which constraints are left unsatisfied (by id), worst first
    worst = []
    if not ok:
        r = 0
        for fn, idx, cid, k in prob.rows:
            e = float(np.abs(F[r:r + k]).max())
            if e > 1e-6:
                worst.append((e, cid))
            r += k
        worst.sort(reverse=True)
    rank = int(np.linalg.matrix_rank(J, tol=1e-7)) if J.size else 0
    return Result(x, ok, it, math.sqrt(cost), (time.perf_counter() - t0) * 1000, rank, n, prob.m, worst)


# ── residual building blocks (plain floats; v is the list of a constraint's unknown values) ─────────────────────────

def _unit(dx, dy):
    L = math.hypot(dx, dy)
    return (dx / L, dy / L) if L > 1e-12 else (1.0, 0.0)


def signed_dist(px, py, ax, ay, bx, by) -> float:
    """Signed distance from p to the infinite line a->b (positive on the left)."""
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy) or 1e-12
    return (dx * (py - ay) - dy * (px - ax)) / L


def sin_between(a, b) -> float:
    ux, uy = _unit(*a)
    vx, vy = _unit(*b)
    return ux * vy - uy * vx


def cos_between(a, b) -> float:
    ux, uy = _unit(*a)
    vx, vy = _unit(*b)
    return ux * vx + uy * vy
