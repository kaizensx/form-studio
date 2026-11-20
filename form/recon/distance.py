"""Distances between a point set and a triangle mesh, and the two-sided Hausdorff distance between two meshes.

The distance from a point to a triangle is exact (closest point on the triangle, Ericson's method). Which triangles to
test comes from a k-d tree over points sampled on every triangle at most `spacing` apart: the k nearest samples give
an upper bound, then every triangle with a sample inside that bound plus the spacing is tested, so the search is exact.
Hausdorff is measured on samples of each surface (vertices, edge points and interior points at most `spacing` apart);
the report states the spacing and the number of samples.
"""
from __future__ import annotations

import numpy as np


def closest_on_triangles(P: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """Closest point on triangle (A[i], B[i], C[i]) to P[i], all (n, 3)."""
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = P - B
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = P - C
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    out = np.empty_like(P)
    done = np.zeros(len(P), dtype=bool)

    def put(mask, val):
        m = mask & ~done
        out[m] = val[m] if val.ndim == 2 else val
        done[m] = True

    put((d1 <= 0) & (d2 <= 0), A)
    put((d3 >= 0) & (d4 <= d3), B)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), A + v[:, None] * ab)
        put((d6 >= 0) & (d5 <= d6), C)
        w = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), A + w[:, None] * ac)
        w2 = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), B + w2[:, None] * (C - B))
        den = 1.0 / (va + vb + vc)
        vv, ww = vb * den, vc * den
        rest = A + vv[:, None] * ab + ww[:, None] * ac
    put(np.ones(len(P), dtype=bool), np.nan_to_num(rest))
    return out


def sample_surface(V: np.ndarray, F: np.ndarray, spacing: float, cap: int = 400_000):
    """Points on every triangle at most about `spacing` apart, with the triangle each came from: (S (n, 3), tri (n,)).

    Vertices are always included. If the spacing would give more than `cap` points it is widened; the returned spacing
    is the one used."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    L = np.maximum(np.maximum(np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1)), np.linalg.norm(a - c, axis=1))
    while True:
        k = np.clip(np.ceil(L / spacing).astype(np.int64), 1, 200)
        total = int(((k + 1) * (k + 2) // 2).sum())
        if total <= cap or spacing > 1e6:
            break
        spacing *= 1.5
    pts, tri = [], []
    for kk in np.unique(k):
        idx = np.flatnonzero(k == kk)
        i, j = np.meshgrid(np.arange(kk + 1), np.arange(kk + 1), indexing="ij")
        m = (i + j) <= kk
        u, v = i[m] / kk, j[m] / kk
        w = 1 - u - v
        P = (w[None, :, None] * a[idx, None, :] + u[None, :, None] * b[idx, None, :] + v[None, :, None] * c[idx, None, :])
        pts.append(P.reshape(-1, 3))
        tri.append(np.repeat(idx, len(u)))
    return np.concatenate(pts), np.concatenate(tri), float(max(spacing, (L / k).max()))


class MeshDistance:
    """Distance from points to one triangle mesh."""

    def __init__(self, V: np.ndarray, F: np.ndarray, spacing: float | None = None, k: int = 16):
        from scipy.spatial import cKDTree
        self.V, self.F, self.k = V, F, k
        if spacing is None:
            spacing = max(float(np.ptp(V, axis=0).max()) / 150, 1e-3)
        self.S, self.tri, self.spacing = sample_surface(V, F, spacing, cap=300_000)
        self.tree = cKDTree(self.S)
        self.eps = 1e-9 * max(float(np.ptp(V, axis=0).max()), 1.0)

    def closest(self, P: np.ndarray, chunk: int = 20000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(distance (n,), closest point (n, 3), triangle (n,))."""
        P = np.asarray(P, dtype=np.float64)
        D = np.empty(len(P))
        Q = np.empty_like(P)
        TI = np.empty(len(P), dtype=np.int64)
        V, F = self.V, self.F
        k = min(self.k, len(self.S))
        for s in range(0, len(P), chunk):
            p = P[s:s + chunk]
            _, nn = self.tree.query(p, k=k)
            nn = nn.reshape(len(p), -1)
            cand = self.tri[nn]                                  # (n, k) candidate triangles (with repeats)
            best = np.full(len(p), np.inf)
            bq = np.zeros_like(p)
            bt = np.zeros(len(p), dtype=np.int64)
            for j in range(cand.shape[1]):
                t = cand[:, j]
                q = closest_on_triangles(p, V[F[t, 0]], V[F[t, 1]], V[F[t, 2]])
                d = np.linalg.norm(q - p, axis=1)
                better = d < best
                best[better], bq[better], bt[better] = d[better], q[better], t[better]
            # exact: the true closest triangle has a sample within `spacing` of the closest point, so within
            # best + spacing of p. Test every triangle with a sample in that ball.
            # Points already within 1e-9 of the size of the mesh of a triangle keep that distance (error below that).
            far = np.flatnonzero(best > self.eps)
            balls = self.tree.query_ball_point(p[far], best[far] + self.spacing * 1.001, workers=-1) if len(far) else []
            cnt = np.fromiter((len(b) for b in balls), dtype=np.int64, count=len(balls))
            if cnt.sum():
                pi = np.repeat(far, cnt)
                ti = self.tri[np.fromiter((j for b in balls for j in b), dtype=np.int64, count=int(cnt.sum()))]
                key = np.unique(pi * (len(F) + 1) + ti)
                pi, ti = key // (len(F) + 1), key % (len(F) + 1)
                for s2 in range(0, len(pi), 400_000):
                    a_, t_ = pi[s2:s2 + 400_000], ti[s2:s2 + 400_000]
                    q = closest_on_triangles(p[a_], V[F[t_, 0]], V[F[t_, 1]], V[F[t_, 2]])
                    d = np.linalg.norm(q - p[a_], axis=1)
                    o = np.lexsort((d, a_))
                    a_, d, q, t_ = a_[o], d[o], q[o], t_[o]
                    first = np.r_[True, a_[1:] != a_[:-1]]
                    a_, d, q, t_ = a_[first], d[first], q[first], t_[first]
                    better = d < best[a_]
                    best[a_[better]], bq[a_[better]], bt[a_[better]] = d[better], q[better], t_[better]
            D[s:s + chunk], Q[s:s + chunk], TI[s:s + chunk] = best, bq, bt
        return D, Q, TI


def hausdorff(VA, FA, VB, FB, spacing: float | None = None) -> dict:
    """Two-sided Hausdorff distance between meshes A and B, sampled at `spacing` (mm), with mean and 99th percentile."""
    diag = float(np.linalg.norm(np.ptp(np.vstack([VA, VB]), axis=0)))
    if spacing is None:
        spacing = max(diag / 300, 1e-3)
    SA, _, spa = sample_surface(VA, FA, spacing)
    SB, _, spb = sample_surface(VB, FB, spacing)
    dA = MeshDistance(VB, FB, spacing).closest(SA)[0]       # A's samples to B
    dB = MeshDistance(VA, FA, spacing).closest(SB)[0]       # B's samples to A
    return {"hausdorff_mm": float(max(dA.max(), dB.max())), "a_to_b_max_mm": float(dA.max()), "b_to_a_max_mm": float(dB.max()),
            "a_to_b_mean_mm": float(dA.mean()), "b_to_a_mean_mm": float(dB.mean()),
            "p99_mm": float(np.percentile(np.r_[dA, dB], 99)), "samples": int(len(SA) + len(SB)),
            "sample_spacing_mm": round(float(max(spa, spb)), 4)}
