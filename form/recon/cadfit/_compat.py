"""What the vendored CADFit modules (vendor/) need from their environment, without its optional extras.

CADFit was written as a set of command-line scripts with a process pool each, progress bars and plots. Inside Form
Studio it runs in one child process with a hard deadline (cadfit/__init__.py), so:

    pool(n)       a process pool when n > 1, else the same map/imap run in this process (Form Studio passes 1)
    tqdm          the real one when installed, else a pass-through
    plt           matplotlib.pyplot when installed (Agg), else None: plots are only drawn with save_plots, never here
    Polygon/Point shapely's when installed, else the small numpy subset below that CADFit's loop grouping uses

Part of the CADFit folder: see PERMISSION.md for the terms that cover it.
"""
from __future__ import annotations

import numpy as np


class _SeqPool:
    def __init__(self, n=1):
        self.n = n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, it):
        return [fn(x) for x in it]

    def imap(self, fn, it):
        for x in it:
            yield fn(x)


def pool(n=1):
    if int(n or 1) > 1:
        import multiprocessing as mp
        return mp.Pool(int(n))
    return _SeqPool(1)


try:                                                    # noqa: SIM105
    from tqdm import tqdm                               # type: ignore
except ImportError:                                     # pragma: no cover - depends on the environment
    def tqdm(it=None, *a, **k):
        return it


try:
    import matplotlib                                   # type: ignore
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt                     # type: ignore
except ImportError:                                     # pragma: no cover - depends on the environment
    plt = None


def _ring(coords):
    P = np.asarray(coords, dtype=float).reshape(-1, 2)
    if len(P) > 1 and np.allclose(P[0], P[-1]):
        P = P[:-1]
    return P


def _inside(P, q):
    """Even-odd point-in-polygon for points q (k, 2) against ring P (n, 2)."""
    q = np.atleast_2d(np.asarray(q, dtype=float))
    x, y = q[:, 0:1], q[:, 1:2]
    a, b = P, np.roll(P, -1, axis=0)
    cond = (a[:, 1] > y) != (b[:, 1] > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xs = a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return np.count_nonzero(cond & (x < xs), axis=1) % 2 == 1


class TopologicalError(Exception):
    pass


class Point:
    def __init__(self, *p):
        self.xy = np.asarray(p[0] if len(p) == 1 else p, dtype=float).reshape(1, 2)


class Polygon:
    """The part of shapely.geometry.Polygon CADFit's loop grouping reads: area, validity, containment and an
    approximate intersection area (by sampling). A ring is taken as given (buffer(0) does not repair it)."""

    def __init__(self, coords=()):
        self.P = _ring(coords)

    @property
    def is_empty(self):
        return len(self.P) < 3

    @property
    def is_valid(self):
        return not self.is_empty

    def buffer(self, _d):
        return self

    @property
    def area(self):
        if self.is_empty:
            return 0.0
        x, y = self.P[:, 0], self.P[:, 1]
        return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)

    def contains(self, other):
        if self.is_empty:
            return False
        q = other.xy if isinstance(other, Point) else other.P
        return bool(len(q) and _inside(self.P, q).all())

    covers = contains

    def intersection(self, other):
        """An approximate intersection: a polygon-like object whose area is estimated on a grid over self."""
        return _Area(self._shared_area(other))

    def _shared_area(self, other, n=64):
        if self.is_empty or other.is_empty:
            return 0.0
        lo, hi = self.P.min(axis=0), self.P.max(axis=0)
        gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], n), np.linspace(lo[1], hi[1], n))
        q = np.c_[gx.ravel(), gy.ravel()]
        both = _inside(self.P, q) & _inside(other.P, q)
        cell = float(np.prod(np.maximum(hi - lo, 1e-12))) / (n * n)
        return float(both.sum()) * cell


class _Area:
    def __init__(self, a):
        self.area = a


try:
    from shapely.errors import TopologicalError        # type: ignore  # noqa: F811
    from shapely.geometry import Point, Polygon         # type: ignore  # noqa: F811
except ImportError:                                     # pragma: no cover - depends on the environment
    pass


def polygons_full(planar):
    """trimesh's Path2D.polygons_full needs shapely: without it the caller reads the path's entities instead."""
    try:
        return planar.polygons_full
    except Exception:                                   # noqa: BLE001
        return []
