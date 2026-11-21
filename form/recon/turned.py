"""Turned bodies and patterns for the program route (program.py): what a lathe and a dividing head make.

revolve(plan, tol)   When every slab of the plan has one outer loop and at most one bore, all circles about one axis
                     along the direction, the part's body is a solid of revolution. Its half-section (radius against
                     level, outer side up, bore or axis down) is read off the slabs and fitted as a sketch of lines,
                     arcs and rounded corners (sketch.fit): steps, chamfers (lines), fillets and grooves (arcs and
                     rounded corners) become one revolved profile whose diameters, levels and radii are Params. Holes
                     that are not on the axis (bolt holes) stay the plan's own features. None otherwise.

polar(runs, tol)     Cut features that are the same circle between the same levels with their centres equally spaced
                     on one circle (three or more): one polar pattern, its pitch circle diameter a Param.

Both read only what the plan has measured on the mesh; the recipe is verified against the mesh like every other.
"""
from __future__ import annotations

import math

import numpy as np

from . import sketch as sk


def _circle(P):
    """(centre, radius, deviation) of the least-squares circle through the 2-D points P."""
    x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    c = sol[:2]
    r = float(np.sqrt(max(sol[2] + c @ c, 0.0)))
    return c, r, float(np.abs(np.linalg.norm(P - c, axis=1) - r).max())


def _radius(P, c, tol):
    """The radius of the closed polygon P about c, or None when P is not a circle there: its corners must lie on
    the circle within tol and the middles of its sides within 8 tol (a faceted circle's sides sag by its chord
    error; a square's corners lie on a circle too, but the middles of its sides are far inside it)."""
    if len(P) < 8:
        return None
    rr = np.linalg.norm(P - c, axis=1)
    m = float(rr.mean())
    if float(np.abs(rr - m).max()) > tol:
        return None
    mid = (P + np.roll(P, -1, axis=0)) / 2
    return m if float(np.abs(np.linalg.norm(mid - c, axis=1) - m).max()) <= 8 * tol else None


def _simplify(P, eps):
    """Consecutive duplicates and collinear middle points removed (closed polygon)."""
    Q = [P[0]]
    for p in P[1:]:
        if np.linalg.norm(p - Q[-1]) > eps:
            Q.append(p)
    if len(Q) > 1 and np.linalg.norm(Q[0] - Q[-1]) <= eps:
        Q.pop()
    changed = True
    while changed and len(Q) > 3:
        changed = False
        for i in range(len(Q)):
            a, b, c = Q[i - 1], Q[i], Q[(i + 1) % len(Q)]
            ab, ac = b - a, c - a
            L = float(np.linalg.norm(ac))
            if L > 0 and abs(ab[0] * ac[1] - ab[1] * ac[0]) / L <= eps and (ab @ ac) > 0 and (ab @ ab) < (ac @ ac):
                Q.pop(i)
                changed = True
                break
    return np.array(Q)


def revolve(plan, tol) -> dict | None:
    """The turned body of a plan (see the module), or None. Returns {"centre", "loop", "runs", "points"}."""
    subs, size = plan["subs"], plan["size"]
    if not subs:
        return None
    eps = tol / 4
    centre = None
    coax = set()
    prof_out, prof_in = [], []
    for a, b, loops in subs:
        outer = [lp for lp in loops if lp.depth == 0]
        if len(outer) != 1:
            return None
        lp = outer[0]
        if centre is None:
            centre, r0, dev = _circle(lp.bot)
            if dev > eps or r0 <= tol:
                return None
        rb, rt = _radius(lp.bot, centre, eps), _radius(lp.top, centre, eps)
        if rb is None or rt is None:
            return None
        coax.add(id(lp))
        prof_out += [(rb, a), (rt, b)]
        bores = []
        for q in loops:
            if q.depth != 1:
                continue
            qb, qt = _radius(q.bot, centre, eps), _radius(q.top, centre, eps)
            if qb is not None and qt is not None and float(np.linalg.norm(_circle(q.mid)[0] - centre)) <= eps:
                bores.append((q, qb, qt))
        if len(bores) > 1:
            return None
        if bores:
            q, qb, qt = bores[0]
            coax.add(id(q))
            prof_in.append(((qb, a), (qt, b)))
        else:
            prof_in.append(((0.0, a), (0.0, b)))
    runs = []
    for r in plan["runs"]:
        mine = [id(lp) in coax for _, lp in r.loops]
        if all(mine):
            runs.append(r)
        elif any(mine):
            return None                                  # a run that is partly turned: not one body of revolution
    P = np.array(prof_out + [p for pair in reversed(prof_in) for p in reversed(pair)], dtype=np.float64)
    P = _simplify(P, max(1e-9 * size, 1e-9))
    if len(P) < 3 or sk._area2(P) <= tol * tol:
        return None
    lp = None
    for ft in (tol / 2, tol / 3):
        lp = sk.fit(P, ft, size)
        if lp is not None and lp.err <= tol / 2 and lp.kind == "path":
            break
        lp = None
    if lp is None or len(lp.nodes) > 80:
        return None
    return {"centre": centre, "loop": lp, "runs": runs, "points": len(P)}


def polar(runs, tol) -> list[dict]:
    """Polar patterns among these cut runs: [{"runs", "centre", "pcd", "n", "phase_deg"}] (see the module)."""
    groups = {}
    for r in runs:
        if r.add or r.kind != "prism" or r.bot is None or r.bot.kind != "circle":
            continue
        key = (round(r.bot.r / max(tol / 4, 1e-6)), round(r.za / max(tol / 4, 1e-6)), round(r.zb / max(tol / 4, 1e-6)),
               r.depth)
        groups.setdefault(key, []).append(r)
    out = []
    for rs in groups.values():
        if len(rs) < 3:
            continue
        C = np.array([r.bot.c for r in rs], dtype=np.float64)
        c, R, dev = _circle(C)
        if dev > tol / 4 or R <= tol:
            continue
        ang = np.sort(np.mod(np.arctan2(C[:, 1] - c[1], C[:, 0] - c[0]), 2 * math.pi))
        n = len(rs)
        step = 2 * math.pi / n
        gaps = np.diff(np.r_[ang, ang[0] + 2 * math.pi])
        if float(np.abs(gaps - step).max()) * R > tol / 4:
            continue
        order = np.argsort(np.mod(np.arctan2(C[:, 1] - c[1], C[:, 0] - c[0]), 2 * math.pi))
        rs = [rs[i] for i in order]
        phase = math.degrees(float(ang[0]))
        out.append({"runs": rs, "centre": c, "pcd": 2 * R, "n": n, "phase_deg": round(phase, 4)})
    return out
