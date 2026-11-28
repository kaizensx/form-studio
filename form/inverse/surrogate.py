"""A Gaussian-process surrogate (NumPy only): what a search believes about a quantity between the points it has
really evaluated, and how unsure it is.

    gp = GP().fit(X, y)             # X (n, d) in the unit box, y (n,)
    mean, std = gp.predict(Z)

Kernel: Matérn 5/2 with one length scale per variable (Rasmussen and Williams 2006, eq. 4.17), a constant mean and a
small noise term. The length scales are the ones with the highest marginal likelihood among a fixed set of
candidates: one shared length first, then each variable's on its own, twice round. That is a coarse fit, and it is
enough here, because every point the surrogate proposes is evaluated for real before anything is reported.
"""
from __future__ import annotations

import numpy as np

LENGTHS = (0.08, 0.15, 0.3, 0.6, 1.2, 2.5, 6.0)
NOISE = 1e-6
SQ5 = 5.0 ** 0.5


def _k(A: np.ndarray, B: np.ndarray, ls: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.maximum((((A[:, None, :] - B[None, :, :]) / ls) ** 2).sum(axis=2), 0.0))
    return (1 + SQ5 * d + 5.0 / 3.0 * d * d) * np.exp(-SQ5 * d)


class GP:
    def __init__(self, noise: float = NOISE):
        self.noise = noise
        self.X = self.ls = self.alpha = self.L = None
        self.mu, self.sd = 0.0, 1.0

    def _nll(self, ls) -> float:
        K = _k(self.X, self.X, ls) + self.noise * np.eye(len(self.X))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return float("inf")
        a = np.linalg.solve(L.T, np.linalg.solve(L, self.z))
        return float(0.5 * self.z @ a + np.log(np.diag(L)).sum())

    def fit(self, X, y) -> "GP":
        self.X = np.asarray(X, float)
        y = np.asarray(y, float)
        self.mu = float(y.mean())
        self.sd = float(y.std()) or 1.0
        self.z = (y - self.mu) / self.sd
        d = self.X.shape[1]
        best = min(((self._nll(np.full(d, s)), s) for s in LENGTHS), key=lambda t: t[0])
        ls, nll = np.full(d, best[1]), best[0]
        if d > 1 and len(self.X) >= 2 * d:
            for _ in range(2):
                for j in range(d):
                    for s in LENGTHS:
                        if s == ls[j]:
                            continue
                        trial = ls.copy()
                        trial[j] = s
                        v = self._nll(trial)
                        if v < nll - 1e-9:
                            ls, nll = trial, v
        if not np.isfinite(nll):                         # points on top of each other: more noise, a long scale
            self.noise, ls = 1e-3, np.full(d, 1.2)
        self.ls = ls
        K = _k(self.X, self.X, ls) + self.noise * np.eye(len(self.X))
        self.L = np.linalg.cholesky(K + 1e-10 * np.eye(len(K)))
        self.alpha = np.linalg.solve(self.L.T, np.linalg.solve(self.L, self.z))
        return self

    def predict(self, Z) -> tuple:
        Z = np.asarray(Z, float)
        Ks = _k(Z, self.X, self.ls)
        mean = Ks @ self.alpha
        v = np.linalg.solve(self.L, Ks.T)
        var = np.maximum(1.0 + self.noise - (v * v).sum(axis=0), 1e-12)
        return self.mu + self.sd * mean, self.sd * np.sqrt(var)


def latin_hypercube(n: int, d: int, rng) -> np.ndarray:
    """n points in the unit box, one in each of n slices of every variable."""
    out = np.empty((n, d))
    for j in range(d):
        out[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return out
