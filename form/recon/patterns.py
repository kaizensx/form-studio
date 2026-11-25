"""Patterns first: teeth, ribs and notches repeated round an axis, read off the mesh as one tooth and a pattern. Beta.

A toothed outline (a sector gear, a ratchet, a knurl) defeats every route that reads one surface at a time: each
flank is a small cylinder or a strip of facets, and a part made of them is left frozen however regular it is. Here
the repetition is found first, on sections of the mesh across a world axis:

1. Centres: the holes the section cuts (circular inner loops) are where a polar pattern turns.
2. Repetition: the outline is turned about each centre by every angle from 3 to 90 degrees; the angle that lays the
   most of its radially varying points (flanks, not arcs about the centre) back onto the outline within half the
   tolerance is the pitch. Points that land on the outline after a turn of +pitch or -pitch are the repeated run;
   at least MIN_COUNT pitches of it make a pattern.
3. The tooth: one pitch of the outline between two roots (the points of the run nearest the centre), closed along
   the root circle a little inside the band (so tooth and base overlap), fitted as lines and arcs (sketch.py). The
   band the teeth stand in (the annular sector from the root circle out past the tips, across the run) is cut from
   the base and the tooth is extruded and turned into place once per pitch.
4. Levels: the pattern holds across every slab of the part along the axis where each pitch's outline is within half
   the tolerance of the tooth; that range is the extrusion's, and outside it the teeth stay in the base.

numpy and scipy only (the sections come from form.remodel.sections); the pattern is built and verified in mixed.py.
"""
from __future__ import annotations

import math
import time

import numpy as np

MIN_COUNT = 3              # pitches of one tooth that make a pattern
PITCH_RANGE = (3.0, 90.0)  # degrees searched for the pitch
PITCH_STEP = 0.5           # degrees between the pitches tried, before the fine search (a tenth of it)
MIN_MATCHED = 0.08         # share of the outline's radially varying points a pitch must lay back onto it
SAMPLE_SLABS = 6           # sections tried along each axis
MAX_POINTS = 600           # flank points turned for each pitch tried
HOLD = 0.75                # a slab holds the pattern when each pitch is within this share of the tolerance of the tooth
PLANE_UV = {0: (1, 2), 1: (0, 2), 2: (0, 1)}


def frame(k: int):
    """(origin-free) plane axes for sections across world axis k: x_dir, z_dir and the sign of the section's second
    coordinate in the plane's own y (sections.cut gives (u, v) in world coordinates)."""
    u, v = PLANE_UV[k]
    x, z = np.eye(3)[u], np.eye(3)[k]
    y = np.cross(z, x)
    return x, z, float(np.sign(y @ np.eye(3)[v]))


def _resample(L, step):
    P = np.r_[L, L[:1]]
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.r_[0.0, np.cumsum(seg)]
    t = np.arange(0.0, s[-1], step)
    return np.c_[np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1])]


def _area2(L):
    x, y = L[:, 0], L[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _rot(P, c, a_deg):
    a = math.radians(a_deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return (P - c) @ R.T + c


def _levels(V, k, tol):
    """Distinct heights of the mesh's vertices along axis k (clustered within a fiftieth of the tolerance)."""
    h = np.sort(V[:, k])
    keep = np.r_[True, np.diff(h) > tol / 50]
    return h[keep]


def _pitch(P, c, tree, w, tol, lo=PITCH_RANGE[0], hi=PITCH_RANGE[1], step=PITCH_STEP):
    """(matched points, pitch in degrees) of the best turn about c, or (0, None)."""
    best = (0, None)
    Q = P[w]
    k = max(1, len(Q) // MAX_POINTS)                    # every k-th flank point: the count is a share, k times fewer
    Q = Q[::k]
    for a in np.arange(lo, hi + 1e-9, step):
        d, _ = tree.query(_rot(Q, c, a))
        n = int((d < tol / 2).sum()) * k
        if n > best[0]:
            best = (n, float(a))
    return best


def _refine(P, c, tree, w, tol, a):
    """The pitch near `a` (within one coarse step) that lays the flank points it matches closest onto the outline: the
    mean distance of those within the tolerance, least over a fine scan (the count saturates, the distance does not)."""
    Q = P[w]
    best = (math.inf, a)
    for b in np.arange(a - PITCH_STEP, a + PITCH_STEP + 1e-9, PITCH_STEP / 25):
        d, _ = tree.query(_rot(Q, c, b))
        m = d < tol
        if m.sum() < 0.5 * len(Q) * MIN_MATCHED:
            continue
        e = float(d[m].mean())
        if e < best[0]:
            best = (e, float(b))
    return best[1]


def find(V, F, tol, deadline=None, axes=(2, 0, 1)) -> dict | None:
    """The strongest polar pattern of the mesh's outline across a world axis, or None. Returns {"kind": "polar",
    "axis", "centre" (u, v), "pitch_deg", "count", "first_deg" (the first tooth's middle), "r_root", "r_cut", "r_out",
    "span_deg" (a0, a1), "tooth" ((n, 2) closed outline in the tooth's own frame: its middle on the +x axis, the centre
    at the origin), "level" (the section it was read on), "matched_pct"}."""
    from scipy.spatial import cKDTree
    from ..remodel import sections
    best = None
    for k in axes:
        if deadline is not None and time.perf_counter() > deadline:
            break
        lv = _levels(V, k, tol)
        if len(lv) < 2:
            continue
        gaps = np.diff(lv)
        order = np.argsort(-gaps)[:SAMPLE_SLABS]
        for i in order:
            if gaps[i] < tol or (deadline is not None and time.perf_counter() > deadline):
                continue
            h = float((lv[i] + lv[i + 1]) / 2)
            loops = [L for L in sections.cut(V, F, k, h) if len(L) >= 8]
            if not loops:
                continue
            centres = []
            for L in loops:
                c = L.mean(axis=0)
                r = np.linalg.norm(L - c, axis=1)
                if r.std() <= tol / 4 and r.mean() > tol:
                    centres.append(c)
            for L in loops:
                if abs(_area2(L)) < 1e-9:
                    continue
                P = _resample(L, tol / 2)
                if len(P) < 40:
                    continue
                tree = cKDTree(_resample(L, tol / 10))
                for c in centres:
                    r = np.linalg.norm(P - c, axis=1)
                    if np.all(r < tol * 4):
                        continue
                    w = np.abs(np.gradient(r)) / (tol / 2) > 0.15       # flanks, not arcs about the centre
                    if w.sum() < 20:
                        continue
                    n, a = _pitch(P, c, tree, w, tol)
                    if a is None or n < MIN_MATCHED * w.sum():
                        continue
                    a = _refine(P, c, tree, w, tol, a)
                    got = _pattern(P, L, c, a, tree, w, tol)
                    if got is None:
                        continue
                    got.update({"axis": int(k), "level": h, "matched_pct": round(100.0 * n / w.sum(), 1)})
                    score = got["count"] * got["tooth_len"]
                    if best is None or score > best[0]:
                        best = (score, got)
    return best[1] if best else None


def _pattern(P, L, c, pitch, tree, w, tol) -> dict | None:
    """The run of P that repeats by `pitch` about c, its count and its tooth."""
    dp, _ = tree.query(_rot(P, c, pitch))
    dm, _ = tree.query(_rot(P, c, -pitch))
    rep = ((dp < tol / 2) | (dm < tol / 2)) & w
    if rep.sum() < 10:
        return None
    th = np.degrees(np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0]))
    r = np.linalg.norm(P - c, axis=1)
    # the repeated points' angles, unwrapped about their circular mean, so a run across +-180 stays one run
    m = math.degrees(math.atan2(np.sin(np.radians(th[rep])).mean(), np.cos(np.radians(th[rep])).mean()))
    rel = (th - m + 180.0) % 360.0 - 180.0
    r = np.linalg.norm(P - c, axis=1)
    # roots: among the repeated points, those nearest the centre; the pattern's cells start at one of them
    root = float(r[rep].min())
    roots = np.flatnonzero(rep & (r <= root + tol / 2))
    b0 = float(rel[roots[0]])
    # cells of one pitch round the whole circle from that root; a cell repeats when every point of it, turned by
    # +pitch, lies on the outline and it has flanks. The pattern is the longest run of cells that repeat one after
    # another (n cells repeating make n + 1 teeth)
    ncell = int(math.floor(360.0 / pitch + 1e-9))
    cell_of = np.floor(((rel - b0) % 360.0) / pitch).astype(int)
    ok = np.zeros(ncell, dtype=bool)
    for jj in range(ncell):
        sel = cell_of == jj
        if sel.sum() < 4 or w[sel].mean() < 0.2:
            continue
        ok[jj] = bool(dp[sel].max() < tol / 2)
    best_run, cur, start = (0, 0), 0, 0
    for jj in range(2 * ncell):                          # twice round: a run may cross the cell where it started
        if ok[jj % ncell] and cur < ncell:
            if cur == 0:
                start = jj
            cur += 1
            if cur > best_run[0]:
                best_run = (cur, start)
        else:
            cur = 0
    count = best_run[0] + 1
    if count < MIN_COUNT or count > ncell:
        return None
    b0 = b0 + best_run[1] * pitch
    a0, a1 = b0, b0 + count * pitch
    off = (rel - a0) % 360.0
    sel = off <= a1 - a0
    r_out = float(r[sel].max())
    r_cut = float(r[sel].min()) - tol / 4
    if r_cut <= tol or r_out - r_cut < 2 * tol:
        return None
    # the tooth: the middle pitch of the outline, between its two roots, closed along the root circle (r_cut)
    j = count // 2
    t0 = a0 + j * pitch
    cell = np.flatnonzero((off >= j * pitch) & (off <= (j + 1) * pitch))
    if len(cell) < 6:
        return None
    # the cell's points in order along the outline (one contiguous piece of it)
    idx = np.sort(cell)
    gaps = np.flatnonzero(np.diff(idx) > 1)
    if len(gaps):                                        # it wraps past the start of the resampled outline
        idx = np.r_[idx[gaps[0] + 1:], idx[:gaps[0] + 1]]
    seg = P[idx]
    if ((rel[idx[-1]] - rel[idx[0]] + 180.0) % 360.0 - 180.0) < 0:     # runs clockwise: turn it round
        seg = seg[::-1]
    mid = math.radians(t0 + pitch / 2 + m)
    loc = _rot(seg, c, -math.degrees(mid)) - c
    ra, rb = math.radians(-pitch / 2), math.radians(pitch / 2)
    # closed a little inside the band's root circle, so the tooth overlaps the base it is fused to (no slit)
    r_in = r_cut - tol / 4
    arc = [(r_in * math.cos(t), r_in * math.sin(t)) for t in np.linspace(rb, ra, 9)]
    tooth = np.vstack([loc, np.array(arc)])
    if _area2(tooth) < 0:
        tooth = tooth[::-1]
    span = float(np.linalg.norm(np.diff(loc, axis=0), axis=1).sum())
    return {"kind": "polar", "centre": [float(c[0]), float(c[1])], "pitch_deg": float(pitch), "count": count,
            "first_deg": float(a0 + pitch / 2 + m), "r_root": root, "r_cut": r_cut, "r_out": r_out,
            "span_deg": [float(a0 + m), float(a1 + m)], "tooth": tooth, "tooth_flank": loc, "tooth_len": span}


def levels(V, F, pat, tol, deadline=None) -> tuple[float, float] | None:
    """The range along the pattern's axis over which every pitch's outline is within half the tolerance of the
    tooth: the slabs between neighbouring levels of the mesh, from the one it was read on outwards."""
    from scipy.spatial import cKDTree
    from ..remodel import sections
    k = pat["axis"]
    lv = _levels(V, k, tol)
    c = np.asarray(pat["centre"])
    flank = pat["tooth_flank"]
    ref = []
    for i in range(pat["count"]):
        a = pat["first_deg"] + i * pat["pitch_deg"]
        ref.append(_rot(flank + c, c, a))
    ref = np.vstack(ref)
    lo_i = int(np.searchsorted(lv, pat["level"]) - 1)

    def holds(i):
        if i < 0 or i >= len(lv) - 1:
            return False
        h = float((lv[i] + lv[i + 1]) / 2)
        loops = sections.cut(V, F, k, h)
        if not loops:
            return False
        tree = cKDTree(np.vstack([_resample(L, tol / 10) for L in loops if len(L) >= 3]))
        d, _ = tree.query(ref)
        return bool(d.max() <= HOLD * tol)

    if not holds(lo_i):
        return None
    a = b = lo_i
    while (deadline is None or time.perf_counter() < deadline) and holds(a - 1):
        a -= 1
    while (deadline is None or time.perf_counter() < deadline) and holds(b + 1):
        b += 1
    return float(lv[a]), float(lv[b + 1])
