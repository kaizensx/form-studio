"""NSGA-II (Deb, Pratap, Agarwal and Meyarivan 2002) on the unit box, with constraint domination. NumPy only.

    X, F, G = minimise(fn, dim, pop=64, generations=100, seed=1)

`fn(X)` takes an (n, dim) array of points in [0, 1] and returns (F, G): F is (n, m) objectives, all minimised; G is
(n, k) constraint violations, feasible where every column is <= 0 (k may be 0, or G None). The search is the paper's:
fast non-dominated sorting, crowding distance, binary tournaments, simulated binary crossover and polynomial mutation.
A feasible point dominates an infeasible one; of two infeasible points the one with the smaller total violation wins.

Also here, because the rest of form/inverse needs them: `pareto_mask` (which rows are not dominated),
`hypervolume` (two or three objectives, exact) and `igd` (distance of a found front to a reference front).
"""
from __future__ import annotations

import numpy as np

ETA_CROSS = 15.0
ETA_MUT = 20.0
P_CROSS = 0.9


def violation(G) -> np.ndarray:
    """Total constraint violation of each row (0 = feasible)."""
    if G is None:
        return np.zeros(0)
    G = np.asarray(G, float)
    if G.ndim == 1:
        G = G[:, None]
    return np.maximum(G, 0.0).sum(axis=1) if G.shape[1] else np.zeros(len(G))


def dominates_matrix(F: np.ndarray, cv: np.ndarray | None = None) -> np.ndarray:
    """D[i, j] is True where row i dominates row j (constraint domination when cv is given)."""
    F = np.asarray(F, float)
    le = (F[:, None, :] <= F[None, :, :]).all(axis=2)
    lt = (F[:, None, :] < F[None, :, :]).any(axis=2)
    D = le & lt
    if cv is not None and len(cv):
        fi, fj = (cv <= 0)[:, None], (cv <= 0)[None, :]
        D = np.where(fi & fj, D, np.where(fi & ~fj, True, np.where(~fi & fj, False, cv[:, None] < cv[None, :])))
    return D


def pareto_mask(F: np.ndarray, cv: np.ndarray | None = None) -> np.ndarray:
    """True for the rows no other row dominates. Rows with a violation are never on the front when a feasible row
    exists."""
    F = np.asarray(F, float)
    if len(F) == 0:
        return np.zeros(0, bool)
    return ~dominates_matrix(F, cv).any(axis=0)


def fronts(F: np.ndarray, cv: np.ndarray | None = None) -> list:
    """Fast non-dominated sort: a list of index arrays, the best front first."""
    D = dominates_matrix(F, cv)
    n = len(F)
    count = D.sum(axis=0).astype(int)                    # how many dominate each row
    left = np.ones(n, bool)
    out = []
    while left.any():
        cur = np.where(left & (count == 0))[0]
        if len(cur) == 0:                                # equal rows: cannot happen with strict domination, kept safe
            cur = np.where(left)[0]
        out.append(cur)
        left[cur] = False
        count = count - D[cur].sum(axis=0)
    return out


def crowding(F: np.ndarray) -> np.ndarray:
    F = np.asarray(F, float)
    n, m = F.shape
    d = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for j in range(m):
        o = np.argsort(F[:, j], kind="stable")
        span = F[o[-1], j] - F[o[0], j]
        d[o[0]] = d[o[-1]] = np.inf
        if span > 0:
            d[o[1:-1]] += (F[o[2:], j] - F[o[:-2], j]) / span
    return d


def _rank_crowd(F, cv):
    rank = np.zeros(len(F), int)
    crowd = np.zeros(len(F))
    fs = fronts(F, cv)
    for k, idx in enumerate(fs):
        rank[idx] = k
        crowd[idx] = crowding(F[idx])
    return rank, crowd, fs


def _offspring(X, rank, crowd, rng, n):
    N, d = X.shape

    def tournament(k):
        a, b = rng.integers(0, N, k), rng.integers(0, N, k)
        better = (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (crowd[a] > crowd[b]))
        return np.where(better, a, b)
    half = (n + 1) // 2
    p1, p2 = X[tournament(half)], X[tournament(half)]
    u = rng.random((half, d))
    beta = np.where(u <= 0.5, (2 * u) ** (1 / (ETA_CROSS + 1)), (1 / (2 * (1 - u))) ** (1 / (ETA_CROSS + 1)))
    cross = (rng.random((half, 1)) < P_CROSS) & (rng.random((half, d)) < 0.5)
    c1 = np.where(cross, 0.5 * ((1 + beta) * p1 + (1 - beta) * p2), p1)
    c2 = np.where(cross, 0.5 * ((1 - beta) * p1 + (1 + beta) * p2), p2)
    C = np.clip(np.concatenate([c1, c2])[:n], 0.0, 1.0)
    # polynomial mutation, each variable with probability 1/d
    mut = rng.random(C.shape) < 1.0 / d
    u = rng.random(C.shape)
    lo = (2 * u + (1 - 2 * u) * (1 - C) ** (ETA_MUT + 1)) ** (1 / (ETA_MUT + 1)) - 1
    hi = 1 - (2 * (1 - u) + 2 * (u - 0.5) * C ** (ETA_MUT + 1)) ** (1 / (ETA_MUT + 1))
    return np.clip(np.where(mut, C + np.where(u < 0.5, lo, hi), C), 0.0, 1.0)


def minimise(fn, dim: int, pop: int = 64, generations: int = 100, seed: int = 1, start: np.ndarray | None = None,
             stop=None) -> tuple:
    """Returns (X, F, G) of the final population's first front. start: points to seed the population with."""
    rng = np.random.default_rng(seed)
    pop = max(8, int(pop) + int(pop) % 2)
    X = rng.random((pop, dim))
    if start is not None and len(start):
        s = np.clip(np.asarray(start, float)[:pop], 0, 1)
        X[:len(s)] = s

    def call(Z):
        F, G = fn(Z)
        F = np.asarray(F, float).reshape(len(Z), -1)
        G = np.zeros((len(Z), 0)) if G is None else np.asarray(G, float).reshape(len(Z), -1)
        return F, G
    F, G = call(X)
    for _ in range(int(generations)):
        if stop is not None and stop():
            break
        rank, crowd, _ = _rank_crowd(F, violation(G))
        C = _offspring(X, rank, crowd, rng, pop)
        FC, GC = call(C)
        X, F, G = np.concatenate([X, C]), np.concatenate([F, FC]), np.concatenate([G, GC])
        rank, crowd, fs = _rank_crowd(F, violation(G))
        keep = []
        for idx in fs:
            if len(keep) + len(idx) <= pop:
                keep.extend(idx.tolist())
            else:
                order = idx[np.argsort(-crowd[idx], kind="stable")]
                keep.extend(order[: pop - len(keep)].tolist())
                break
        keep = np.array(keep)
        X, F, G = X[keep], F[keep], G[keep]
    m = pareto_mask(F, violation(G))
    return X[m], F[m], G[m]


# ---- measures of a front -------------------------------------------------------------------------------------------

def hypervolume(F: np.ndarray, ref: np.ndarray) -> float:
    """The volume dominated by the rows of F and bounded by ref (minimisation). Exact for two and three objectives;
    more are refused, because nothing here needs them and an approximation would be a number without a method."""
    F = np.asarray(F, float).reshape(-1, len(ref))
    ref = np.asarray(ref, float)
    F = F[(F < ref).all(axis=1)]
    if len(F) == 0:
        return 0.0
    m = F.shape[1]
    if m == 1:
        return float(ref[0] - F[:, 0].min())
    if m == 2:
        F = F[pareto_mask(F)]
        F = F[np.argsort(F[:, 0])]
        hv, prev = 0.0, ref[1]
        for a, b in F:
            if b < prev:
                hv += (ref[0] - a) * (prev - b)
                prev = b
        return float(hv)
    if m == 3:                                           # slices along the third objective
        F = F[np.argsort(F[:, 2])]
        hv = 0.0
        for i in range(len(F)):
            top = F[i + 1, 2] if i + 1 < len(F) else ref[2]
            if top > F[i, 2]:
                hv += hypervolume(F[: i + 1, :2], ref[:2]) * (top - F[i, 2])
        return float(hv)
    raise ValueError("hypervolume is computed for at most three objectives")


def igd(found: np.ndarray, reference: np.ndarray) -> float:
    """Inverted generational distance: the mean distance from each point of the reference front to the nearest found
    point. Small means the found front is both close to the reference and covers it."""
    A, R = np.asarray(found, float), np.asarray(reference, float)
    if len(A) == 0:
        return float("inf")
    d = np.linalg.norm(R[:, None, :] - A[None, :, :], axis=2)
    return float(d.min(axis=1).mean())


def zdt(name: str):
    """The analytic test problems ZDT1 and ZDT2 (Zitzler, Deb and Thiele 2000) with their known fronts:
    returns (fn(X) -> (F, None), front(n) -> (n, 2))."""
    name = name.lower()

    def fn(X):
        X = np.asarray(X, float)
        f1 = X[:, 0]
        g = 1 + 9 * X[:, 1:].sum(axis=1) / max(X.shape[1] - 1, 1)
        h = 1 - np.sqrt(f1 / g) if name == "zdt1" else 1 - (f1 / g) ** 2
        return np.column_stack([f1, g * h]), None

    def front(n=200):
        f1 = np.linspace(0, 1, n)
        return np.column_stack([f1, 1 - np.sqrt(f1) if name == "zdt1" else 1 - f1 ** 2])
    if name not in ("zdt1", "zdt2"):
        raise ValueError("zdt1 or zdt2")
    return fn, front
