"""Critics for a reconstruction, beside its distance to the mesh: is the material in the right place, is every opening
the right shape, and is every void still a void.

The distance to the mesh (verify.py) is dominated by the big surfaces. A round hole modelled square moves it by a
fraction of the hole's size, and a body whose faces all lie on the mesh can still put material where the part is
hollow (a loose block filling a cavity, its faces on the cavity's walls). These gates measure that directly:

- **Occupancy**: both meshes are filled on one voxel grid by the winding number of rays along Z (orientation counts,
  so a cavity bounded by faces that face the wrong way is filled, the way a CAD kernel reads it). The grid is then
  sliced along X, Y and Z: per slice, the IoU of the two filled areas; overall, the volume the candidate is missing and
  the volume it adds.
- **Openings**: plane sections through both meshes on each axis (form/remodel/sections.py). Every opening of the part
  (a loop inside material: a hole, a slot, a pocket) needs an opening in the candidate of the same kind (circle,
  rectangle, slot, outline) whose area overlaps it with IoU >= 0.85. Per loop, so a small hole is never diluted by a
  large part.
- **Voids**: per slice, the empty space the slice encloses (not reachable from outside the slice). Void the part has
  and the candidate fills solid is "missing void"; the reverse is "extra void".

Tolerances are relative to the part: `size_tolerance` is 0.15 % of the bounding-box diagonal with a floor, and a
volume difference is allowed when it is no more than a skin of that thickness over the part's surface.

The ideas (slice-occupancy IoU on three axes, a per-opening shape match, the internal-void gap and a size-relative
tolerance) come from nickpagz/stl2step (featurecheck.py, Apache-2.0, commit ae32fab). This is a new implementation on
numpy and scipy; no code was copied. See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import math
import time

import numpy as np

OPENING_IOU = 0.85
SIZE_FRAC = 0.0015
SIZE_FLOOR = 0.02
STATIONS = (0.12, 0.31, 0.5, 0.69, 0.88)
_JITTER = (0.000137, 0.000291)          # rays are moved this many voxels off the grid's centres (off shared edges)


def size_tolerance(V: np.ndarray, frac: float = SIZE_FRAC, floor: float = SIZE_FLOOR) -> float:
    """A tolerance that scales with the part: `frac` of the bounding-box diagonal, never below `floor` (mm)."""
    V = np.asarray(V, dtype=np.float64)
    diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0))) if len(V) else 0.0
    return max(float(floor), frac * diag)


def surface_area(V: np.ndarray, F: np.ndarray) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


# ---- occupancy on a voxel grid ---------------------------------------------------------------------------------------

def grid_for(*meshes, cells: int = 4_000_000, pad: int = 2, h: float | None = None):
    """One voxel grid (lo, h, n) that holds every (V, F) given, with `pad` empty voxels all round."""
    V = np.vstack([np.asarray(m[0], dtype=np.float64) for m in meshes])
    lo, hi = V.min(axis=0), V.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    if h is None:
        h = float(np.cbrt(np.prod(span) / cells))
        h = max(h, float(span.max()) / 2000)
    while np.prod(np.ceil(span / h) + 2 * pad) > cells:
        h *= 1.1
    n = (np.ceil(span / h).astype(int) + 2 * pad)
    return lo - pad * h, float(h), n


def occupancy(V: np.ndarray, F: np.ndarray, lo, h: float, n) -> np.ndarray:
    """Which voxels of the grid (lo, h, n) are inside the mesh, by the winding number of a ray along +Z through each
    column of voxel centres (non-zero rule). A face whose normal points down is entered, one pointing up is left."""
    V, F = np.asarray(V, dtype=np.float64), np.asarray(F, dtype=np.int64)
    n = np.asarray(n, dtype=int)
    if len(F) == 0:
        return np.zeros(tuple(n), dtype=bool)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    nz = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    keep = np.abs(nz) > 1e-14
    a, b, c, nz = a[keep], b[keep], c[keep], nz[keep]
    sign = np.where(nz < 0, 1, -1).astype(np.int16)    # +1 entering material on the way up, -1 leaving it
    ox, oy = lo[0] + (0.5 + _JITTER[0]) * h, lo[1] + (0.5 + _JITTER[1]) * h
    tlo = np.minimum(np.minimum(a, b), c)
    thi = np.maximum(np.maximum(a, b), c)
    i0 = np.clip(np.ceil((tlo[:, 0] - ox) / h).astype(int), 0, n[0])
    i1 = np.clip(np.floor((thi[:, 0] - ox) / h).astype(int), -1, n[0] - 1)
    j0 = np.clip(np.ceil((tlo[:, 1] - oy) / h).astype(int), 0, n[1])
    j1 = np.clip(np.floor((thi[:, 1] - oy) / h).astype(int), -1, n[1] - 1)
    ni, nj = np.maximum(i1 - i0 + 1, 0), np.maximum(j1 - j0 + 1, 0)
    cnt = ni * nj
    diff = np.zeros((int(n[0]) * int(n[1]), int(n[2]) + 1), dtype=np.int16)
    if cnt.sum() == 0:
        return np.zeros(tuple(n), dtype=bool)
    chunk = 4_000_000
    starts = np.r_[0, np.cumsum(cnt)]
    t_lo = 0
    while t_lo < len(cnt):                              # in chunks of triangles, so memory stays bounded
        t_hi = int(np.searchsorted(starts, starts[t_lo] + chunk, side="right"))
        t_hi = max(t_hi - 1, t_lo + 1)
        sl = slice(t_lo, t_hi)
        cc = cnt[sl]
        T = np.repeat(np.arange(t_lo, t_hi), cc)
        if len(T):
            off = np.arange(len(T)) - np.repeat(np.cumsum(cc) - cc, cc)
            I = i0[T] + off // np.maximum(nj[T], 1)
            J = j0[T] + off % np.maximum(nj[T], 1)
            px, py = ox + I * h, oy + J * h
            A, B, C = a[T], b[T], c[T]
            e1x, e1y = B[:, 0] - A[:, 0], B[:, 1] - A[:, 1]
            e2x, e2y = C[:, 0] - A[:, 0], C[:, 1] - A[:, 1]
            qx, qy = px - A[:, 0], py - A[:, 1]
            den = e1x * e2y - e2x * e1y
            s = (qx * e2y - e2x * qy) / den
            t = (e1x * qy - qx * e1y) / den
            hit = (s >= 0) & (t >= 0) & (s + t <= 1)
            z = A[hit, 2] + s[hit] * (B[hit, 2] - A[hit, 2]) + t[hit] * (C[hit, 2] - A[hit, 2])
            col = I[hit] * int(n[1]) + J[hit]
            sg = sign[T[hit]]
            # a ray through an edge two triangles share crosses both at one height, with one sign: count it once
            o = np.lexsort((sg, z, col))
            col, z, sg = col[o], z[o], sg[o]
            dup = np.r_[False, (col[1:] == col[:-1]) & (np.abs(z[1:] - z[:-1]) <= 1e-9) & (sg[1:] == sg[:-1])]
            col, z, sg = col[~dup], z[~dup], sg[~dup]
            k = np.clip(np.ceil((z - lo[2]) / h - 0.5).astype(int), 0, int(n[2]))
            np.add.at(diff, (col, k), sg)
        t_lo = t_hi
    wind = np.cumsum(diff, axis=1)[:, :int(n[2])]
    return (wind != 0).reshape(tuple(n))


def _enclosed(empty: np.ndarray, axis: int) -> np.ndarray:
    """Empty voxels that their own slice across `axis` encloses: not connected, within the slice, to its border."""
    from scipy import ndimage
    st = np.zeros((3, 3, 3), dtype=bool)
    idx = [slice(None)] * 3
    idx[axis] = 1
    st[tuple(idx)] = ndimage.generate_binary_structure(2, 1)
    lab, _ = ndimage.label(empty, structure=st)
    border = []
    for ax in range(3):
        if ax == axis:
            continue
        for end in (0, -1):
            s = [slice(None)] * 3
            s[ax] = end
            border.append(lab[tuple(s)].ravel())
    out = np.unique(np.concatenate(border))
    return empty & ~np.isin(lab, out[out > 0]) & (lab > 0)


def occupancy_gate(VA, FA, VB, FB, tol: float | None = None, cells: int = 4_000_000) -> dict:
    """Part (VA, FA) against candidate (VB, FB) on one voxel grid: volumes, the slice IoU on each axis, the missing and
    extra volume, the void the candidate fills and the void it adds, and whether each is within the allowance."""
    VA, VB = np.asarray(VA, dtype=np.float64), np.asarray(VB, dtype=np.float64)
    FA, FB = np.asarray(FA, dtype=np.int64), np.asarray(FB, dtype=np.int64)
    tol_s = max(size_tolerance(VA), float(tol or 0.0))
    lo, h, n = grid_for((VA, FA), (VB, FB), cells=cells)
    A = occupancy(VA, FA, lo, h, n)
    B = occupancy(VB, FB, lo, h, n)
    hv = h ** 3
    inter, union = np.count_nonzero(A & B), np.count_nonzero(A | B)
    missing, extra = np.count_nonzero(A & ~B), np.count_nonzero(B & ~A)
    axes = []
    for ax in range(3):
        other = tuple(i for i in range(3) if i != ax)
        ia = (A & B).sum(axis=other)
        ua = (A | B).sum(axis=other)
        live = ua > max(4, 0.02 * ua.max()) if ua.size else ua > 0
        iou = np.where(ua > 0, ia / np.maximum(ua, 1), 1.0)
        k = int(np.argmin(np.where(live, iou, 2.0))) if live.any() else 0
        axes.append({"axis": "xyz"[ax], "mean_iou": round(float(iou[live].mean()), 4) if live.any() else None,
                     "worst_iou": round(float(iou[k]), 4) if live.any() else None,
                     "worst_at_mm": round(float(lo[ax] + (k + 0.5) * h), 3)})
    # void the part's slices enclose that the candidate fills, and the reverse; the worst axis is the headline
    mv, ev = [], []
    for ax in range(3):
        mv.append(np.count_nonzero(_enclosed(~A, ax) & B))
        ev.append(np.count_nonzero(_enclosed(~B, ax) & A))
    area = surface_area(VA, FA)
    allow = 2.0 * area * tol_s + 8 * hv                 # a skin of the tolerance over the part's surface, both sides
    vol_a = np.count_nonzero(A) * hv
    out = {"grid_mm": round(h, 4), "cells": int(np.prod(n)), "tolerance_mm": round(tol_s, 4),
           "part_mm3": round(vol_a, 2), "candidate_mm3": round(np.count_nonzero(B) * hv, 2),
           "iou": round(inter / union, 4) if union else 1.0,
           "missing_mm3": round(missing * hv, 2), "extra_mm3": round(extra * hv, 2),
           "missing_void_mm3": round(max(mv) * hv, 2), "extra_void_mm3": round(max(ev) * hv, 2),
           "allowed_mm3": round(allow, 2), "axes": axes}
    out["occupancy_ok"] = bool(missing * hv <= allow and extra * hv <= allow)
    out["void_ok"] = bool(max(mv) * hv <= allow)
    return out


# ---- openings --------------------------------------------------------------------------------------------------------

def _mask(L: np.ndarray, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Even-odd inside test of the points (X, Y) against the closed loop L."""
    x, y = L[:, 0], L[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    P = np.c_[X.ravel(), Y.ravel()]
    inside = np.zeros(len(P), dtype=bool)
    for s in range(0, len(L), 256):                     # edges in blocks: points x edges stays small
        xa, ya, xb, yb = x[s:s + 256], y[s:s + 256], x2[s:s + 256], y2[s:s + 256]
        up = (ya[None, :] > P[:, 1:2]) != (yb[None, :] > P[:, 1:2])
        dy = np.where(yb != ya, yb - ya, 1e-300)
        xc = xa[None, :] + (P[:, 1:2] - ya[None, :]) * (xb - xa)[None, :] / dy[None, :]
        inside ^= (np.count_nonzero(up & (P[:, 0:1] < xc), axis=1) % 2).astype(bool)
    return inside.reshape(X.shape)


def loop_iou(L1: np.ndarray, L2: np.ndarray, px: int = 96) -> float:
    """IoU of the areas two closed loops enclose, on a raster of about px x px over both."""
    lo = np.minimum(L1.min(axis=0), L2.min(axis=0))
    hi = np.maximum(L1.max(axis=0), L2.max(axis=0))
    if np.any(L1.max(axis=0) < L2.min(axis=0)) or np.any(L2.max(axis=0) < L1.min(axis=0)):
        return 0.0
    step = float((hi - lo).max()) / px or 1e-6
    xs = lo[0] + (np.arange(int(math.ceil((hi[0] - lo[0]) / step)) + 1) + 0.5) * step - step
    ys = lo[1] + (np.arange(int(math.ceil((hi[1] - lo[1]) / step)) + 1) + 0.5) * step - step
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    a, b = _mask(L1, X, Y), _mask(L2, X, Y)
    u = np.count_nonzero(a | b)
    return float(np.count_nonzero(a & b) / u) if u else 0.0


def _openings(V, F, axis, level, tol):
    from ..remodel import sections
    loops = sections.cut(V, F, axis, level)
    out = []
    for i, L in enumerate(loops):
        depth = sum(1 for j, M in enumerate(loops) if j != i and sections.inside(L[0], M))
        if depth % 2 == 1:
            d = sections.describe(L, tol)
            d["_loop"] = L
            out.append(d)
    return out


def _label(d: dict) -> str:
    k = d.get("kind")
    if k == "circle":
        return f"circle Ø{d['diameter']:g}"
    if k in ("rectangle", "slot"):
        w, h = d["size"]
        return f"{k} {w:g} x {h:g}"
    return "outline"


def opening_gate(VA, FA, VB, FB, tol: float | None = None, stations=STATIONS, iou_min: float = OPENING_IOU) -> dict:
    """Every opening the part's sections show needs an opening in the candidate's section at the same plane, of the
    same kind, overlapping it with IoU >= iou_min (circles also within the tolerance in diameter). Candidate openings
    the part does not have are reported as extra."""
    from .mesh import weld
    VA, VB = np.asarray(VA, dtype=np.float64), np.asarray(VB, dtype=np.float64)
    # sections follow shared edges, so a tessellation with one vertex set per face is welded first
    VA, FA, _ = weld(VA[np.asarray(FA, dtype=np.int64)])
    VB, FB, _ = weld(VB[np.asarray(FB, dtype=np.int64)])
    tol_s = max(size_tolerance(VA), float(tol or 0.0))
    lo, hi = VA.min(axis=0), VA.max(axis=0)
    min_area = max(0.5, (4 * tol_s) ** 2)
    found, raw = 0, []
    for ax in range(3):
        for f in stations:
            level = float(lo[ax] + f * (hi[ax] - lo[ax]))
            ma = [o for o in _openings(VA, FA, ax, level, max(tol_s, 0.02)) if o["area_mm2"] >= min_area]
            cb = [o for o in _openings(VB, FB, ax, level, max(tol_s, 0.02)) if o["area_mm2"] >= min_area]
            used = set()
            for o in ma:
                found += 1
                best, bi = 0.0, None
                for k, c in enumerate(cb):
                    v = loop_iou(o["_loop"], c["_loop"])
                    if v > best:
                        best, bi = v, k
                rec = {"axis": "xyz"[ax], "at_mm": round(level, 3), "center": o["center"], "part": _label(o)}
                if bi is None or best < 0.05:
                    raw.append({**rec, "kind": "missing opening", "iou": 0.0})
                    continue
                used.add(bi)
                c = cb[bi]
                same = o.get("kind") == c.get("kind") or (o.get("kind") == "outline" and best >= iou_min)
                if o.get("kind") == "circle" and c.get("kind") == "circle":
                    same = same and abs(o["diameter"] - c["diameter"]) <= max(2 * tol_s, 0.01 * o["diameter"])
                if best < iou_min or not same:
                    raw.append({**rec, "kind": "wrong shape", "candidate": _label(c), "iou": round(best, 3)})
            for k, c in enumerate(cb):
                if k not in used and not any(loop_iou(c["_loop"], o["_loop"]) > 0.05 for o in ma):
                    raw.append({"axis": "xyz"[ax], "at_mm": round(level, 3), "center": c["center"],
                                "kind": "extra opening", "candidate": _label(c), "iou": 0.0})
    groups = {}
    for r in raw:                                       # one row per opening, however many stations saw it
        key = (r["axis"], r["kind"], tuple(round(x / max(tol_s * 10, 0.5)) for x in r["center"]))
        g = groups.get(key)
        if g is None:
            groups[key] = {**r, "stations": [r["at_mm"]]}
        else:
            g["stations"].append(r["at_mm"])
            g["iou"] = min(g["iou"], r["iou"])
    mism = sorted(groups.values(), key=lambda g: (g["kind"] != "wrong shape", g["iou"]))
    return {"openings_checked": found, "mismatches": mism[:12], "mismatch_count": len(mism),
            "openings_ok": not mism, "min_area_mm2": round(min_area, 3)}


# ---- all gates -------------------------------------------------------------------------------------------------------

def check(VA, FA, VB, FB, tol: float | None = None, cells: int = 4_000_000) -> dict:
    """All gates: the part (VA, FA) against a candidate (VB, FB). `verdict` is "pass" or the gates that failed."""
    t = time.perf_counter()
    occ = occupancy_gate(VA, FA, VB, FB, tol, cells=cells)
    opn = opening_gate(VA, FA, VB, FB, tol)
    failed = [k for k, ok in (("occupancy", occ["occupancy_ok"]), ("voids", occ["void_ok"]),
                              ("openings", opn["openings_ok"])) if not ok]
    return {"verdict": "pass" if not failed else "fail: " + ", ".join(failed), "passed": not failed,
            "failed": failed, "occupancy": occ, "openings": opn, "seconds": round(time.perf_counter() - t, 2)}
