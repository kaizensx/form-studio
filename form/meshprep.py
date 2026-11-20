"""Preflight for a mesh someone brings in: how big it is, whether it is closed, how long work on it will take, and a
lighter copy to draw.

    quick(path)                 instant facts from the file alone (bytes, a binary STL's triangle count, class)
    preflight(path)             triangles, vertices, bounds, closed or not, class, time estimates and a display proxy
    python -m form.meshprep F   the same as JSON

The proxy is for display only. It is a separate file in the cache, made by vertex clustering, and is never used in
place of the source: every analysis, reconstruction and import reads the file the person gave. A preflight is cached
by the file's path, size and modification time, so a second call costs a JSON read.

numpy only; no kernel.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

PROXY_TRIANGLES = 200_000          # a mesh above this gets a display proxy of about this size
WARN_BYTES = 500_000_000           # above this the person is told work on it will be slow
CLASSES = ((200_000, "light"), (1_000_000, "medium"), (5_000_000, "heavy"))
# seconds per million triangles, measured on an Apple M-series Mac with a 1.2M-triangle closed scan-like mesh:
# read = form.recon.mesh.read_triangles (with its checksum); analyse = weld + topology, the first step of every analysis
RATE_S_PER_MTRI = {"read": 0.1, "analyse": 5.5}
VERSION = 1                        # bump when the cached result's shape changes


def kind(triangles: int | None) -> str:
    if triangles is None:
        return "unknown"
    for limit, name in CLASSES:
        if triangles < limit:
            return name
    return "very heavy"


def quick(path: Path) -> dict:
    """What the file says without being read: bytes, a binary STL's triangle count, its class and a warning when it
    is large. Fast enough to run while attaching."""
    from .recon.mesh import stl_triangle_count
    p = Path(path)
    size = p.stat().st_size
    n = None
    if p.suffix.lower() == ".stl":
        try:
            n = stl_triangle_count(p)
        except OSError:
            n = None
    out = {"bytes": size, "triangles": n, "class": kind(n)}
    if size > WARN_BYTES:
        out["warning"] = (f"{size / 1e6:.0f} MB is a very large mesh. Form Studio keeps the file as it is; drawing and "
                          "analysing it will take a while, and a lighter display copy is made for the 3D view.")
    return out


def _cache_root() -> Path:
    try:
        from . import config
        data = Path(config.load()["data"]["dir"])
    except Exception:
        data = Path(os.environ.get("FORM_DATA") or Path.home() / "FORM").expanduser()
    return data / ".cache" / "meshprep"


def _key(p: Path) -> str:
    st = p.stat()
    raw = f"{VERSION}|{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _triangles32(p: Path, fmt: str | None) -> tuple[np.ndarray, str, list]:
    """(n, 3, 3) float32 triangles. A binary STL is mapped, not read twice."""
    from .recon import mesh
    ext = (fmt or p.suffix).lower()
    if ext == ".stl":
        rec = mesh.stl_records(p)
        if rec is not None:
            return np.ascontiguousarray(rec["v"], dtype=np.float32), "stl (binary)", []
    parts, info = mesh.read_parts(p, fmt)
    T = np.concatenate([x.T for x in parts]).astype(np.float32)
    return T, info["format"], info.get("parts") or []


def _weld_exact(T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vertices shared where they are bit-for-bit equal (as STL writers repeat them). Returns (V float32, F int64)."""
    P = T.reshape(-1, 3)
    P += np.float32(0.0)                             # -0.0 and 0.0 are the same point (in place: T is our copy)
    U = P.view(np.uint32)                            # the bit patterns: exact, and no float64 copies
    h = U[:, 0].astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)       # one 64-bit key per point, sorted once
    h ^= U[:, 1].astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
    h ^= (U[:, 2].astype(np.uint64) << np.uint64(17)) * np.uint64(0x165667B19E3779F9)
    order = np.argsort(h)
    del h
    S = U[order]                                     # equal points are neighbours; a rare key collision only adds a vertex
    new = np.empty(len(order), dtype=bool)
    new[:1] = True
    new[1:] = (S[1:] != S[:-1]).any(axis=1)
    del S
    ids = np.empty(len(order), dtype=np.int64)
    ids[order] = np.cumsum(new) - 1
    V = P[order[new]]
    return V, ids.reshape(-1, 3)


def _edges(F: np.ndarray, nv: int) -> dict:
    ok = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
    key = np.empty(3 * int(ok.sum()), dtype=np.int64)
    m = len(key) // 3
    for k, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
        a, b = F[ok, i], F[ok, j]
        key[k * m:(k + 1) * m] = np.minimum(a, b) * np.int64(nv) + np.maximum(a, b)
    del a, b
    key.sort()
    edge_start = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    counts = np.diff(np.r_[edge_start, len(key)])
    return {"edges": int(len(counts)), "boundary_edges": int((counts == 1).sum()),
            "non_manifold_edges": int((counts > 2).sum()), "degenerate_triangles": int((~ok).sum())}


def decimate(V: np.ndarray, F: np.ndarray, target: int = PROXY_TRIANGLES) -> tuple[np.ndarray, np.ndarray, float]:
    """Vertex clustering on a grid sized from the surface area, so the result has about `target` triangles.
    Returns (V, F, cell size in mm). For display: thin walls and fine detail merge."""
    pick = F if len(F) <= 400_000 else F[np.random.default_rng(0).choice(len(F), 400_000, replace=False)]
    a, b, c = (V[pick[:, k]].astype(np.float64) for k in range(3))
    area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2) * len(F) / len(pick)   # sampled
    h = max(np.sqrt(2.0 * max(area, 1e-9) / target), 1e-6)
    lo = V.min(axis=0).astype(np.float64)
    for _ in range(6):
        q = np.floor((V - lo) / h).astype(np.int64)
        dims = q.max(axis=0) + 1
        cell = (q[:, 0] * dims[1] + q[:, 1]) * dims[2] + q[:, 2]
        uniq, lab = np.unique(cell, return_inverse=True)
        lab = lab.reshape(-1)
        G = lab[F]
        keep = (G[:, 0] != G[:, 1]) & (G[:, 1] != G[:, 2]) & (G[:, 0] != G[:, 2])
        G = G[keep]
        if len(G):
            srt = np.sort(G, axis=1)
            _, first = np.unique(srt, axis=0, return_index=True)
            G = G[np.sort(first)]
        if len(G) <= 1.3 * target or len(G) == 0:
            break
        h *= np.sqrt(len(G) / target)
    W = np.zeros((len(uniq), 3))
    np.add.at(W, lab, V.astype(np.float64))
    W /= np.bincount(lab, minlength=len(uniq))[:, None]
    used = np.unique(G)
    remap = -np.ones(len(W), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return W[used], remap[G], float(h)


def preflight(path: Path, fmt: str | None = None, cache: Path | None = None, proxy: bool = True) -> dict:
    """Everything worth knowing before working on a mesh, and a display proxy for a heavy one. Cached."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"No such file: {p}")
    t0 = time.perf_counter()
    root = Path(cache) if cache else _cache_root()
    folder = root / _key(p)
    rec_file = folder / "preflight.json"
    try:
        got = json.loads(rec_file.read_text(encoding="utf-8"))
        if got.get("proxy") is None or Path(got["proxy"]["path"]).is_file():
            got["cached"] = True
            got["elapsed_s"] = round(time.perf_counter() - t0, 4)
            return got
    except (OSError, ValueError, KeyError, TypeError):
        pass
    T, fmt_name, parts = _triangles32(p, fmt)
    if not len(T):
        raise ValueError("The mesh holds no triangles.")
    if not np.all(np.isfinite(T)):
        raise ValueError("The mesh has coordinates that are not finite numbers.")
    t_read = time.perf_counter() - t0
    V, F = _weld_exact(T)
    del T
    top = _edges(F, len(V))
    lo, hi = V.min(axis=0).astype(np.float64), V.max(axis=0).astype(np.float64)
    n = int(len(F))
    m = n / 1e6
    out = {"file": p.name, "path": str(p), "format": fmt_name, "bytes": p.stat().st_size, "triangles": n,
           "vertices": int(len(V)), "bbox": [lo.round(4).tolist(), hi.round(4).tolist()],
           "size_mm": (hi - lo).round(4).tolist(), "closed": top["boundary_edges"] == 0 and top["non_manifold_edges"] == 0,
           **top, "class": kind(n),
           "estimate_s": {k: round(v * m, 1) for k, v in RATE_S_PER_MTRI.items()},
           "estimate_note": "Seconds on an Apple M-series Mac, scaled from measured rates: read the file, and the weld "
                            "and topology every analysis starts with. Reconstruction takes longer. Estimates, not "
                            "measurements.",
           "evidence": "computed from the file (triangles, bounds, edges); times are estimates"}
    if parts:
        out["parts"] = parts
    if p.stat().st_size > WARN_BYTES:
        out["warning"] = quick(p).get("warning")
    out["proxy"] = None
    if proxy and n > PROXY_TRIANGLES:
        from .recon.mesh import write_stl
        PV, PF, h = decimate(V, F)
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / "proxy.stl"
        write_stl(dst, PV, PF, name="Form Studio display proxy")
        out["proxy"] = {"path": str(dst), "triangles": int(len(PF)), "cell_mm": round(h, 4),
                        "note": "For display only. The source file is unchanged, and it is what every analysis, "
                                "reconstruction and import uses."}
    out["read_s"] = round(t_read, 3)
    out["elapsed_s"] = round(time.perf_counter() - t0, 3)
    out["cached"] = False
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "preflight.json.tmp"
    tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    os.replace(tmp, rec_file)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: form mesh-preflight FILE [--no-proxy]   (STL, OBJ or 3MF)")
        return 0 if argv else 2
    try:
        out = preflight(Path(argv[0]), proxy="--no-proxy" not in argv)
    except (OSError, ValueError) as e:
        print(json.dumps({"error": {"message": str(e)}}))
        return 2
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
