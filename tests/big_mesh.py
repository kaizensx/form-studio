"""Large meshes generated at test time (never stored): a bumpy UV sphere, one closed connected surface like a scan."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

REC = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


def sphere(triangles: int, radius: float = 60.0) -> tuple[np.ndarray, np.ndarray]:
    """(V, F) of a closed UV sphere with about `triangles` triangles and a little relief."""
    rows = max(4, int(np.sqrt(triangles / 4)))
    cols = 2 * rows
    th = np.linspace(0, np.pi, rows + 1)[1:-1]                   # rings between the poles
    ph = np.linspace(0, 2 * np.pi, cols, endpoint=False)
    T, P = np.meshgrid(th, ph, indexing="ij")
    r = radius * (1 + 0.03 * np.sin(7 * T) * np.cos(5 * P))
    ring = np.stack([r * np.sin(T) * np.cos(P), r * np.sin(T) * np.sin(P), r * np.cos(T)], axis=-1).reshape(-1, 3)
    V = np.vstack([[0, 0, radius], ring, [0, 0, -radius]])
    top, bot = 0, len(V) - 1
    idx = 1 + np.arange((rows - 1) * cols).reshape(rows - 1, cols)
    nxt = np.roll(idx, -1, axis=1)
    F = [np.stack([np.full(cols, top), idx[0], nxt[0]], axis=1)]
    a, b, c, d = idx[:-1], nxt[:-1], idx[1:], nxt[1:]
    F.append(np.stack([a, c, b], axis=-1).reshape(-1, 3))
    F.append(np.stack([b, c, d], axis=-1).reshape(-1, 3))
    F.append(np.stack([np.full(cols, bot), nxt[-1], idx[-1]], axis=1))
    return V, np.concatenate(F).astype(np.int64)


def write_sphere_stl(path, megabytes: float | None = None, triangles: int | None = None) -> int:
    """A binary STL of about `megabytes` (or `triangles`), written in chunks. Returns the triangle count."""
    n = triangles if triangles else int((megabytes * 1e6 - 84) // 50)
    V, F = sphere(n)
    V = V.astype(np.float32)
    with open(Path(path), "wb") as f:
        f.write(b"Form Studio test sphere".ljust(80, b" ") + struct.pack("<I", len(F)))
        for s in range(0, len(F), 2_000_000):
            G = F[s:s + 2_000_000]
            rec = np.zeros(len(G), dtype=REC)
            rec["v"] = V[G]
            rec.tofile(f)
    return int(len(F))
