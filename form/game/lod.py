"""Proxy geometry: which LOD comes from where, and the collision hulls.

LODs from a cage come from its subdivision levels first: level L of a cage with Q quads (after the first level every
face is a quad) has 2 * Q * 4^(L-1) triangles, clean quads at no cost. When no level is close enough under a budget,
the next finer level is decimated to it, and the report says so ("automatic retopology": an edge-collapse decimation
is not hand topology). CAD bodies and sculpts have no levels: their LODs are always decimated (or QuadriFlow
remeshed, when asked).

Collision is a convex hull per part by default (scipy's Qhull, at most HULL_POINTS points per hull, so every engine
takes it: PhysX caps a convex mesh at 255). CoACD (approximate convex decomposition, MIT) is optional, in its own
Python made by Form Studio with one click (form/engines.py "game.coacd"); it runs out of process:

    <engine python> -m form.game.lod coacd <in.npz> <out.npz> <threshold>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

LEVEL_FILL = 0.6           # a cage level is used as is when it fills at least 60% of the budget (and is under it)
MAX_LEVEL = 6
HULL_POINTS = 64
COACD_ENGINE = "game.coacd"
COACD_TIMEOUT_S = 600


def cage_quads(F: list) -> int:
    """Quads after one Catmull-Clark level: an n-gon becomes n quads."""
    return sum(len(f) for f in F)


def level_tris(F: list, level: int) -> int:
    """Triangles of the cage at a subdivision level (level 0: the cage triangulated)."""
    if level == 0:
        return sum(len(f) - 2 for f in F)
    return 2 * cage_quads(F) * 4 ** (level - 1)


def plan_lods(F: list, budgets: list[int], tolerance: float = 0.02, max_level: int = MAX_LEVEL) -> list[dict]:
    """For each budget: {"lod", "budget", "level", "decimate": bool, "source", "expected_tris"}.

    The finest level at or under budget x (1 + tolerance) is used as is when it fills at least LEVEL_FILL of the
    budget; otherwise the next finer level is decimated to the budget."""
    out = []
    for i, b in enumerate(budgets):
        cap = b * (1 + tolerance)
        under = [L for L in range(0, max_level + 1) if level_tris(F, L) <= cap]
        L = max(under) if under else None
        if L is not None and level_tris(F, L) >= LEVEL_FILL * b:
            out.append({"lod": i, "budget": b, "level": L, "decimate": False, "expected_tris": level_tris(F, L),
                        "source": f"cage level {L} (clean quads)"})
        else:
            src = 0 if L is None else min(L + 1, max_level)
            if level_tris(F, src) <= cap:          # even the finest level is under budget: use it
                out.append({"lod": i, "budget": b, "level": src, "decimate": False,
                            "expected_tris": level_tris(F, src), "source": f"cage level {src} (clean quads)"})
            else:
                out.append({"lod": i, "budget": b, "level": src, "decimate": True, "expected_tris": b,
                            "source": f"cage level {src}, decimated to the budget (automatic retopology)"})
    return out


def high_level(F: list, lod0_tris: int, cap_tris: int = 1_500_000) -> int:
    """The level baked from: the first with at least 4 x LOD0's triangles (and 200k), at most cap_tris."""
    want = max(4 * lod0_tris, 200_000)
    for L in range(1, MAX_LEVEL + 1):
        if level_tris(F, L) >= want or level_tris(F, L + 1) > cap_tris:
            return L
    return MAX_LEVEL


# ---- collision -------------------------------------------------------------------------------------------------

def _labels(n: int, T: np.ndarray) -> np.ndarray:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]]])
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    return connected_components(g, directed=False)[1]


def _farthest(P: np.ndarray, k: int) -> np.ndarray:
    """k points of P spread out (farthest-point sampling, deterministic: starts at the lowest-index extreme)."""
    if len(P) <= k:
        return P
    pick = [int(np.argmax(P[:, 0]))]
    d = np.linalg.norm(P - P[pick[0]], axis=1)
    for _ in range(k - 1):
        j = int(np.argmax(d))
        pick.append(j)
        d = np.minimum(d, np.linalg.norm(P - P[j], axis=1))
    return P[pick]


def hull(P: np.ndarray, max_points: int = HULL_POINTS) -> tuple[np.ndarray, np.ndarray]:
    """A convex hull (points, outward triangles) of at most max_points points."""
    from scipy.spatial import ConvexHull
    h = ConvexHull(P)
    V = P[h.vertices]
    if len(V) > max_points:
        V = _farthest(V, max_points)
        h = ConvexHull(V)
        V = V[h.vertices]
        h = ConvexHull(V)
    T = h.simplices.copy()
    c = V.mean(0)
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    flip = np.einsum("ij,ij->i", n, V[T[:, 0]] - c) < 0
    T[flip] = T[flip][:, [0, 2, 1]]
    return V, T


def _inside(P: np.ndarray, V: np.ndarray, tol: float) -> bool:
    from scipy.spatial import ConvexHull
    h = ConvexHull(V)
    A, b = h.equations[:, :3], h.equations[:, 3]
    return bool(np.all(P @ A.T + b <= tol))


def convex_parts(P: np.ndarray, T: np.ndarray, tolerance_mm: float | None = None, max_parts: int = 16) -> list[dict]:
    """A convex hull per part (connected shell). A small part that lies inside a bigger part's hull (within
    tolerance_mm, default 1% of the asset's size) is covered by it and gets no hull of its own. Largest first."""
    P = np.asarray(P, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64)
    used = np.unique(T)
    lab = _labels(len(P), T)
    size = float(np.linalg.norm(P[used].max(0) - P[used].min(0)))
    tol = size * 0.01 if tolerance_mm is None else float(tolerance_mm)
    parts = []
    for k in np.unique(lab[used]):
        Q = P[used][lab[used] == k]
        if len(Q) < 4 or np.linalg.matrix_rank(Q - Q.mean(0), tol=1e-9 * max(size, 1)) < 3:
            continue
        V, H = hull(Q)
        vol = float(np.einsum("ij,ij->i", V[H[:, 0]], np.cross(V[H[:, 1]], V[H[:, 2]])).sum() / 6)
        parts.append({"V": V, "T": H, "volume_mm3": vol, "points": Q})
    parts.sort(key=lambda p: -p["volume_mm3"])
    kept: list[dict] = []
    for p in parts:
        if any(_inside(p["V"], q["V"], tol) for q in kept):
            continue
        kept.append(p)
    if len(kept) > max_parts:                      # too many: the smallest merge into one hull
        rest = np.concatenate([p["V"] for p in kept[max_parts - 1:]])
        V, H = hull(rest)
        kept = kept[:max_parts - 1] + [{"V": V, "T": H, "volume_mm3": 0.0}]
    return [{"V": p["V"], "T": p["T"], "volume_mm3": round(p["volume_mm3"], 3), "method": "convex hull per part"}
            for p in kept]


def coacd_parts(P: np.ndarray, T: np.ndarray, cfg: dict | None = None, threshold: float = 0.05,
                work: Path | None = None) -> list[dict]:
    """CoACD's decomposition, run in its engine environment. Raises RuntimeError when it is not installed or fails."""
    from .. import engines
    py = engines.python(COACD_ENGINE, cfg)
    if py is None:
        raise RuntimeError("CoACD is not installed. Settings › Software › CoACD sets up its own Python in one click; "
                           "a convex hull per part works without it.")
    import tempfile
    d = Path(work or tempfile.mkdtemp(prefix="form-coacd-"))
    src, dst = d / "coacd_in.npz", d / "coacd_out.npz"
    np.savez(src, P=np.asarray(P, np.float64), T=np.asarray(T, np.int64))
    r = subprocess.run([str(py), "-m", "form.game.lod", "coacd", str(src), str(dst), str(float(threshold))],
                       env=engines.child_env(), capture_output=True, text=True, timeout=COACD_TIMEOUT_S)
    if r.returncode != 0 or not dst.is_file():
        raise RuntimeError("CoACD failed: " + (r.stderr or r.stdout)[-800:])
    z = np.load(dst, allow_pickle=False)
    out = []
    for i in range(int(z["n"])):
        V, H = hull(z[f"V{i}"])
        out.append({"V": V, "T": H, "volume_mm3": 0.0, "method": f"CoACD (threshold {threshold:g})"})
    return out


def _coacd_child(src: str, dst: str, threshold: str) -> int:      # runs in the CoACD engine's own Python
    import coacd                                                    # noqa: PLC0415 (only there)
    z = np.load(src, allow_pickle=False)
    mesh = coacd.Mesh(z["P"], z["T"])
    parts = coacd.run_coacd(mesh, threshold=float(threshold), max_convex_hull=32, seed=0)
    np.savez(dst, n=len(parts), **{f"V{i}": np.asarray(v, np.float64) for i, (v, _f) in enumerate(parts)})
    print(json.dumps({"parts": len(parts)}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "coacd":
        sys.exit(_coacd_child(*sys.argv[2:5]))
    sys.exit("usage: python -m form.game.lod coacd <in.npz> <out.npz> <threshold>")
