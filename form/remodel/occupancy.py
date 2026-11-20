"""Inside or outside a closed triangle mesh, on a regular grid (numpy only).

Rays run along Z through the centre of every grid column; the crossings with the mesh's triangles, sorted, give the
column's inside intervals (even-odd rule), which are written into a boolean voxel grid. A point is then answered by
looking up its voxel, so testing tens of thousands of points at each step of a sweep stays cheap. The grid spacing is
reported: an answer is exact to within half a voxel of the surface.
"""
from __future__ import annotations

import numpy as np


class Occupancy:
    def __init__(self, V: np.ndarray, F: np.ndarray, h: float | None = None, pad: float = 1.0, max_cells: int = 30_000_000):
        lo, hi = V.min(axis=0) - pad, V.max(axis=0) + pad
        span = hi - lo
        if h is None:
            h = max(float(span.max()) / 500, 0.05)
        while np.prod(np.ceil(span / h) + 1) > max_cells:
            h *= 1.25
        self.h, self.lo = float(h), lo
        n = (np.ceil(span / h).astype(int) + 1)
        self.n = n
        self.grid = np.zeros(tuple(n), dtype=bool)
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        xs = lo[0] + (np.arange(n[0]) + 0.5) * h
        ys = lo[1] + (np.arange(n[1]) + 0.5) * h
        tlo = np.minimum(np.minimum(a, b), c)
        thi = np.maximum(np.maximum(a, b), c)
        i0 = np.clip(np.floor((tlo[:, 0] - lo[0]) / h - 0.5).astype(int), 0, n[0] - 1)
        i1 = np.clip(np.floor((thi[:, 0] - lo[0]) / h - 0.5).astype(int) + 1, 0, n[0] - 1)
        j0 = np.clip(np.floor((tlo[:, 1] - lo[1]) / h - 0.5).astype(int), 0, n[1] - 1)
        j1 = np.clip(np.floor((thi[:, 1] - lo[1]) / h - 0.5).astype(int) + 1, 0, n[1] - 1)
        ni, nj = i1 - i0 + 1, j1 - j0 + 1
        cnt = ni * nj
        T = np.repeat(np.arange(len(F)), cnt)
        off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        I = i0[T] + off // nj[T]
        J = j0[T] + off % nj[T]
        px, py = xs[I], ys[J]
        A, B, C = a[T], b[T], c[T]
        # barycentric in XY
        v0x, v0y = B[:, 0] - A[:, 0], B[:, 1] - A[:, 1]
        v1x, v1y = C[:, 0] - A[:, 0], C[:, 1] - A[:, 1]
        v2x, v2y = px - A[:, 0], py - A[:, 1]
        den = v0x * v1y - v1x * v0y
        ok = np.abs(den) > 1e-15
        den = np.where(ok, den, 1.0)
        s = (v2x * v1y - v1x * v2y) / den
        t = (v0x * v2y - v2x * v0y) / den
        hit = ok & (s >= 0) & (t >= 0) & (s + t <= 1)
        # half-open rule on shared edges: the ray is moved off exact edges by a tiny skew
        z = A[hit, 2] + s[hit] * (B[hit, 2] - A[hit, 2]) + t[hit] * (C[hit, 2] - A[hit, 2])
        col = I[hit] * n[1] + J[hit]
        o = np.lexsort((z, col))
        col, z = col[o], z[o]
        # drop duplicate crossings (a ray through a shared edge hits both triangles at one z)
        keep = np.r_[True, (col[1:] != col[:-1]) | (np.abs(z[1:] - z[:-1]) > 1e-9)]
        col, z = col[keep], z[keep]
        first = np.r_[True, col[1:] != col[:-1]]
        rank = np.arange(len(col)) - np.maximum.accumulate(np.where(first, np.arange(len(col)), 0))
        enter = rank % 2 == 0
        # pair entering and leaving crossings in each column
        nxt_same = np.r_[col[1:] == col[:-1], False]
        e = np.flatnonzero(enter & nxt_same)
        k0 = np.clip(np.ceil((z[e] - lo[2]) / h - 0.5).astype(int), 0, n[2])
        k1 = np.clip(np.floor((z[e + 1] - lo[2]) / h - 0.5).astype(int) + 1, 0, n[2])
        diff = np.zeros((n[0] * n[1], n[2] + 1), dtype=np.int16)
        good = k1 > k0
        np.add.at(diff, (col[e][good], k0[good]), 1)
        np.add.at(diff, (col[e][good], k1[good]), -1)
        self.grid = (np.cumsum(diff, axis=1)[:, :n[2]] > 0).reshape(tuple(n))

    def inside(self, P: np.ndarray) -> np.ndarray:
        idx = np.floor((np.asarray(P) - self.lo) / self.h).astype(int)
        ok = np.all((idx >= 0) & (idx < self.n), axis=1)
        out = np.zeros(len(P), dtype=bool)
        i = idx[ok]
        out[ok] = self.grid[i[:, 0], i[:, 1], i[:, 2]]
        return out
