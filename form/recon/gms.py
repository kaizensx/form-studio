"""A GMS-compatible score: how well two surfaces match in position and in normal direction, as one number in [0, 1].

Both meshes are sampled (points and face normals, by area, with a fixed seed). A sample of one mesh is matched when
the other has a sample within the distance threshold (5 % of the reference's largest extent) whose normal is within
the angle tolerance. For each angle tolerance from 0 to 25 degrees, recall (reference samples matched) and precision
(candidate samples matched) give the score 1 / (1/recall + 1/precision - 1). GMS is one minus the area over that
curve, divided by 25 degrees; the sweep stops at the first tolerance after zero that scores 0.99 or more.
1.0 means the same surface; it falls as positions or normals drift (a rotation, a missing face, a wrong fillet).

This follows the GMS metric of kulibinai/cadena (utils/gms.py, MIT, commit b636649), reimplemented on scipy's cKDTree
(no pykdtree, no trimesh). It is labelled GMS-compatible: it has not been cross-checked number for number against the
upstream code (tests/test_recon_gates.py does that when pykdtree and an upstream copy are present). Known differences:
our own area sampling and seed, k nearest neighbours inside the distance ball instead of a full ball query, and no
"cube trick" or automatic resampling. No code was copied. See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import numpy as np

N_POINTS = 8192
N_ANGLES = 125
MAX_ANGLE = 25.0
REL_DIST = 0.05


def sample(V: np.ndarray, F: np.ndarray, n: int = N_POINTS, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """n points on the surface, by area, with the normal of the triangle each lies on."""
    V, F = np.asarray(V, dtype=np.float64), np.asarray(F, dtype=np.int64)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    ar = np.linalg.norm(cr, axis=1)
    ok = ar > 0
    a, b, c, cr, ar = a[ok], b[ok], c[ok], cr[ok], ar[ok]
    rng = np.random.default_rng(seed)
    t = rng.choice(len(ar), size=n, p=ar / ar.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    P = a[t] + u[:, None] * (b[t] - a[t]) + v[:, None] * (c[t] - a[t])
    return P, cr[t] / ar[t][:, None]


def _matched(tree_pts, tree, nrm_a, P_b, nrm_b, thr, cos_tol, k):
    """For each sample of b: matched at each angle tolerance (rows) when a sample of a within thr has a normal at
    least that close."""
    k = min(k, len(tree_pts))
    d, i = tree.query(P_b, k=k, distance_upper_bound=thr)
    if k == 1:
        d, i = d[:, None], i[:, None]
    valid = np.isfinite(d)
    ii = np.where(valid, i, 0)
    cos = np.einsum("ijk,ik->ij", nrm_a[ii], nrm_b)
    best = np.where(valid, np.clip(cos, -1.0, 1.0), -np.inf).max(axis=1)
    return best[None, :] >= cos_tol[:, None]


def gms(VA, FA, VB, FB, n_points: int = N_POINTS, n_angles: int = N_ANGLES, rel_dist: float = REL_DIST,
        max_angle: float = MAX_ANGLE, seed: int = 0, k: int = 64) -> dict:
    """GMS-compatible score of candidate (VB, FB) against reference (VA, FA), both in the same frame and units."""
    from scipy.spatial import cKDTree
    PA, NA = sample(VA, FA, n_points, seed)
    PB, NB = sample(VB, FB, n_points, seed)
    thr = rel_dist * float(np.ptp(np.asarray(VA, dtype=np.float64), axis=0).max())
    angles = np.linspace(0.0, max_angle, n_angles)
    cos_tol = np.cos(np.radians(angles)) - 1e-12           # an angle of exactly zero still matches equal normals
    ta, tb = cKDTree(PA), cKDTree(PB)
    recall = _matched(PB, tb, NB, PA, NA, thr, cos_tol, k).mean(axis=1)       # reference samples found in candidate
    precision = _matched(PA, ta, NA, PB, NB, thr, cos_tol, k).mean(axis=1)    # candidate samples found in reference
    ok = (recall > 0) & (precision > 0)
    score = np.zeros_like(recall)
    score[ok] = 1.0 / (1.0 / recall[ok] + 1.0 / precision[ok] - 1.0)
    stop = next((i for i in range(1, len(score)) if score[i] >= 0.99), None)
    s, ang = (score, angles) if stop is None else (score[:stop + 1], angles[:stop + 1])
    span = float(ang[-1] - ang[0]) if len(ang) > 1 else 0.0
    raw = float(np.sum((s[1:] + s[:-1]) * np.diff(ang)) / 2) if len(ang) > 1 else 0.0
    aoc = span - raw
    return {"gms": round(1.0 - aoc / max_angle, 4), "aoc_deg": round(aoc, 4), "distance_mm": round(thr, 4),
            "points": int(n_points), "angles_deg": [round(float(x), 3) for x in ang],
            "curve": [round(float(x), 4) for x in s], "label": "GMS-compatible"}
