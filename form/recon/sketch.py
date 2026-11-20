"""Closed section loops as sketches a designer would draw: lines, arcs and rounded corners. numpy only.

A loop comes from cutting the mesh with a plane, so its points lie on the mesh. It is split into runs that one line or
one circle holds within the tolerance, and then made exact the way a sketch is:

- every line is fitted through all of its points (least squares), and its direction is snapped to a multiple of
  15 degrees when that moves its ends by less than a quarter of the tolerance (most edges are 0, 45 or 90);
- every arc is fitted as a circle through all of its points;
- a corner is the intersection of its two neighbours (line-line, line-circle, circle-circle), not a point of the
  polyline, so a corner sits where the two surfaces of the solid meet;
- an arc tangent to the two lines either side of it is a rounded corner: the sharp corner plus a radius.

The result is a list of nodes (corner points, each with a corner radius, 0 when sharp) joined by lines or arcs (radius
and side), or a full circle. form/recon/ops.py turns it back into a build123d face (`profile`, `disc`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MAX_RADIUS_FACTOR = 4.0        # an arc with a radius over this many loop sizes is a line in all but name


@dataclass
class Node:
    p: np.ndarray                  # corner point (2,)
    r: float = 0.0                 # corner radius (a tangent arc between two lines), 0 when sharp


@dataclass
class Edge:
    kind: str                      # "line" | "arc"
    R: float = 0.0                 # arc radius
    ccw: bool = True               # arc turns counter-clockwise from its start to its end
    large: bool = False            # arc sweeps more than 180 degrees
    c: np.ndarray | None = None    # arc centre as fitted (for reporting)


@dataclass
class Loop:
    kind: str                      # "circle" | "path"
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)      # edges[i] joins nodes[i] and nodes[i + 1]
    c: np.ndarray | None = None    # circle centre
    r: float = 0.0                 # circle radius
    err: float = 0.0               # largest distance from the input points to the sketch


def _area2(L):
    x, y = L[:, 0], L[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _circle_fit(P):
    m = P.mean(axis=0)                                  # centred, for conditioning; normal equations: a 3x3 solve
    x, y = P[:, 0] - m[0], P[:, 1] - m[1]
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    try:
        sol = np.linalg.solve(A.T @ A, A.T @ (x * x + y * y))
    except np.linalg.LinAlgError:
        return m, 0.0, np.inf
    c = sol[:2]
    r = math.sqrt(max(sol[2] + c @ c, 0.0))
    c = c + m
    x, y = P[:, 0], P[:, 1]
    return c, r, float(np.abs(np.hypot(x - c[0], y - c[1]) - r).max()) if r > 0 else np.inf


def _circle_fit_lstsq(P):
    x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    c = sol[:2]
    r = math.sqrt(max(sol[2] + c @ c, 0.0))
    return c, r, float(np.abs(np.hypot(x - c[0], y - c[1]) - r).max()) if r > 0 else np.inf


def _line_fit(P):
    """(point, unit direction, largest distance) of the least-squares line through P."""
    m = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - m, full_matrices=False)
    t = vt[0]
    n = np.array([-t[1], t[0]])
    return m, t, float(np.abs((P - m) @ n).max())


def _chord_dev(P):
    a, b = P[0], P[-1]
    ab = b - a
    n = np.linalg.norm(ab)
    if n < 1e-12:                                       # the ends meet: a point (repeated), or a closed run
        return float(np.linalg.norm(P - a, axis=1).max()) if len(P) <= 3 else np.inf
    return float(np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])).max() / n)


def _dense(P, c, step_deg=30.0):
    a = np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0])
    d = np.abs((np.diff(a) + np.pi) % (2 * np.pi) - np.pi)
    return bool(np.degrees(d).max() <= step_deg)


def _dedupe(L, eps):
    keep = np.r_[True, np.linalg.norm(np.diff(L, axis=0), axis=1) > eps]
    L = L[keep]
    if len(L) > 1 and np.linalg.norm(L[0] - L[-1]) <= eps:
        L = L[:-1]
    return L


def _holds(Q, i, j, tol, rmax):
    """"line", "arc" or None: what holds the points Q[i..j] within tol."""
    seg = Q[i:j + 1]
    if _chord_dev(seg) <= tol:
        return "line"
    if len(seg) >= 3:                                   # three points: an arc so far (it must grow to stay one)
        c, r, dev = _circle_fit(seg)
        if dev <= tol and r < rmax and _dense(seg, c):
            return "arc"
    return None


def _runs(Q, tol, rmax):
    """Greedy split of the closed point list Q (first point repeated at the end) into line and arc runs:
    [(i, j, kind)] with points Q[i..j]. Each run is grown by doubling, then bisection, so a loop of n points costs
    about n log n instead of n squared."""
    out, i, m = [], 0, len(Q)
    while i < m - 1:
        good, kind = i + 1, "line"
        step = 1
        bad = None
        while True:
            j = min(good + step, m - 1)
            if j == good:
                break
            k = _holds(Q, i, j, tol, rmax)
            if k is None:
                bad = j
                break
            good, kind = j, k
            step *= 2
        while bad is not None and bad - good > 1:
            j = (good + bad) // 2
            k = _holds(Q, i, j, tol, rmax)
            if k is None:
                bad = j
            else:
                good, kind = j, k
        kind = _holds(Q, i, good, tol, rmax) or "line"
        if kind == "arc" and good - i < 3:
            kind = "line"
        out.append([i, good, kind])
        i = good
    return out


def _merge(Q, runs, tol, rmax):
    """Neighbouring runs one line or one circle holds become one run; a short line between two arcs of one circle
    joins them."""
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k in range(len(runs) - 1):
            a, b = runs[k], runs[k + 1]
            seg = Q[a[0]:b[1] + 1]
            if a[2] == b[2] == "line" and _line_fit(seg)[2] <= tol:
                runs[k] = [a[0], b[1], "line"]
            elif "arc" in (a[2], b[2]) and len(seg) >= 4:
                c, r, dev = _circle_fit(seg)
                if not (dev <= tol and r < rmax and _dense(seg, c)):
                    continue
                runs[k] = [a[0], b[1], "arc"]
            else:
                continue
            del runs[k + 1]
            changed = True
            break
    return runs


def _dev(Q, i, j, kind):
    P = Q[i:j + 1]
    if len(P) < 2:
        return np.inf
    if kind == "line":
        return _line_fit(P)[2]
    if len(P) < 4:
        return np.inf
    return _circle_fit(P)[2]


def _settle(Q, runs, tol, rmax, reach=5):
    """Move each boundary between two runs to where both fit best (a greedy arc swallows the start of the line after
    it while it stays within the tolerance; the corner belongs where the curve really turns)."""
    for _ in range(1):
        moved = False
        for k in range(len(runs) - 1):
            a, b = runs[k], runs[k + 1]
            if a[2] == b[2] == "line":
                continue
            best, at = max(_dev(Q, a[0], a[1], a[2]), _dev(Q, b[0], b[1], b[2])), a[1]
            for m in range(max(a[0] + 1, a[1] - reach), min(b[1] - 1, a[1] + reach) + 1):
                c = max(_dev(Q, a[0], m, a[2]), _dev(Q, m, b[1], b[2]))
                if c < best - 1e-12:
                    best, at = c, m
            if at != a[1] and best <= tol:
                a[1], b[0] = at, at
                moved = True
        if not moved:
            break
    return runs


def _snap_dir(t, P, tol):
    """t snapped to a multiple of 15 degrees when that keeps every point of P within tol of the line."""
    ang = math.atan2(t[1], t[0])
    step = math.radians(15)
    best = round(ang / step) * step
    ts = np.array([math.cos(best), math.sin(best)])
    m = P.mean(axis=0)
    n = np.array([-ts[1], ts[0]])
    if float(np.abs((P - m) @ n).max()) <= tol:
        return ts
    return t


def _isect(a, b, near, tol=0.0):
    """The intersection of primitives a and b nearest `near`, or None. A primitive is ("line", point, dir) or
    ("arc", centre, radius). Where the two touch (tangent within tol) the tangent point is returned: crossing two
    nearly tangent curves is ill-conditioned, and a sketch's tangent joint belongs at the tangent point."""
    if a[0] == "line" and b[0] == "line":
        p, t, q, s = a[1], a[2], b[1], b[2]
        den = t[0] * s[1] - t[1] * s[0]
        if abs(den) < math.sin(math.radians(1.0)):
            return None
        w = q - p
        k = (w[0] * s[1] - w[1] * s[0]) / den
        return p + k * t
    if a[0] == "arc" and b[0] == "line":
        a, b = b, a
    if a[0] == "line" and b[0] == "arc":
        p, t, c, r = a[1], a[2], b[1], b[2]
        f = p - c
        B = f @ t
        C = f @ f - r * r
        disc = B * B - C
        foot = p - B * t                                 # the point of the line nearest the centre
        if tol > 0 and abs(math.sqrt(max(C - B * B + r * r, 0.0)) - r) <= tol:
            return foot                                  # the line touches the circle there
        if disc < 0:
            return None
        s = math.sqrt(disc)
        cands = [p + (-B - s) * t, p + (-B + s) * t]
        return min(cands, key=lambda x: np.linalg.norm(x - near))
    c0, r0, c1, r1 = a[1], a[2], b[1], b[2]
    d = float(np.linalg.norm(c1 - c0))
    if tol > 0 and d > 1e-12:
        e = (c1 - c0) / d
        if abs(d - (r0 + r1)) <= tol:                    # touching from outside
            return c0 + r0 * e
        if abs(d - abs(r0 - r1)) <= tol:                 # touching from inside
            return c0 + (r0 if r0 >= r1 else -r0) * e
    if d < 1e-12 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    x = (d * d + r0 * r0 - r1 * r1) / (2 * d)
    h = math.sqrt(max(r0 * r0 - x * x, 0.0))
    e = (c1 - c0) / d
    m = c0 + x * e
    nrm = np.array([-e[1], e[0]])
    return min([m + h * nrm, m - h * nrm], key=lambda q: np.linalg.norm(q - near))


def _tangent(line, arc, tol):
    """Is the circle tangent to the line (its centre at distance r from it, within tol)?"""
    p, t = line[1], line[2]
    n = np.array([-t[1], t[0]])
    return abs(abs((arc[1] - p) @ n) - arc[2]) <= tol


def fit(L: np.ndarray, tol: float, size: float | None = None) -> Loop | None:
    """The sketch of the closed loop L ((n, 2) points), or None when it does not hold together within tol."""
    L = np.asarray(L, dtype=np.float64)
    size = size or float(np.ptp(L, axis=0).max())
    L = _dedupe(L, max(1e-9, 1e-7 * size))
    if len(L) < 3:
        return None
    if _area2(L) < 0:
        L = L[::-1]
    rmax = MAX_RADIUS_FACTOR * max(size, 1e-6)
    if len(L) >= 8:
        c, r, dev = _circle_fit(L)
        if dev <= tol and _dense(L, c, 40.0) and r < rmax:
            return Loop("circle", c=c, r=r, err=dev)
    a_ = L - np.roll(L, 1, axis=0)
    b_ = np.roll(L, -1, axis=0) - L
    turn = np.abs(np.arctan2(a_[:, 0] * b_[:, 1] - a_[:, 1] * b_[:, 0], np.einsum("ij,ij->i", a_, b_)))
    s = int(np.argmax(turn))
    Q = np.vstack([L[s:], L[:s], L[s:s + 1]])
    runs = _merge(Q, _runs(Q, tol, rmax), tol, rmax)
    # start again in the middle of the longest straight run, so no arc is cut in two by the start
    lines = [(float(np.linalg.norm(Q[j] - Q[i])), i, j) for i, j, k in runs if k == "line"]
    if lines and (turn[s] < math.radians(30) or len(runs) > 1):
        _, i, j = max(lines)
        s2 = (s + ((i + j) // 2 if j - i >= 2 else i)) % len(L)     # its middle, or its start
        if s2 != s:
            Q = np.vstack([L[s2:], L[:s2], L[s2:s2 + 1]])
            runs = _merge(Q, _runs(Q, tol, rmax), tol, rmax)
    runs = _settle(Q, runs, tol, rmax)
    if len(runs) > 1 and runs[0][2] == "arc" and runs[-1][2] == "arc":         # the start fell inside an arc
        seg = np.vstack([Q[runs[-1][0]:-1], Q[:runs[0][1] + 1]])
        c, r, dev = _circle_fit(seg)
        if dev <= tol and _dense(seg, c):
            Q = np.vstack([Q[runs[-1][0]:-1], Q[:runs[-1][0] + 1]])
            k0 = runs[-1][1] - runs[-1][0]
            nr = [[0, k0 + runs[0][1], "arc"]] + [[a + k0, b + k0, kd] for a, b, kd in runs[1:-1]]
            runs = nr
    return _assemble(Q, runs, L, tol, size)


def _holds2(QA, QB, i, j, tol, rmax):
    a = _holds(QA, i, j, tol, rmax)
    if a is None:
        return None
    b = _holds(QB, i, j, tol, rmax)
    if a == b:
        return a
    if a == "arc" and b == "line" and _holds(QB, i, j, tol, rmax * 1e6) is None:
        return None
    return None if b is None else ("line" if "line" in (a, b) and _chord_dev(QA[i:j + 1]) <= tol and _chord_dev(QB[i:j + 1]) <= tol else None)


def fit_pair(LA: np.ndarray, LB: np.ndarray, tol: float, size: float | None = None):
    """Sketches of two loops whose points correspond one to one (the two ends of one slab of a mesh: the same mesh
    edges cut at two heights), split at the same points so they have the same structure: (loop A, loop B) or None."""
    LA, LB = np.asarray(LA, dtype=np.float64), np.asarray(LB, dtype=np.float64)
    size = size or float(max(np.ptp(LA, axis=0).max(), np.ptp(LB, axis=0).max()))
    if len(LA) != len(LB) or len(LA) < 3:
        return None
    if _area2(LA) < 0:
        LA, LB = LA[::-1], LB[::-1]
    eps = max(1e-9, 1e-7 * size)
    keep = (np.linalg.norm(LA - np.roll(LA, 1, axis=0), axis=1) > eps) | (np.linalg.norm(LB - np.roll(LB, 1, axis=0), axis=1) > eps)
    LA, LB = LA[keep], LB[keep]
    if len(LA) < 3:
        return None
    rmax = MAX_RADIUS_FACTOR * max(size, 1e-6)
    if len(LA) >= 8:
        ca = fit(LA, tol, size)
        cb = fit(LB, tol, size)
        if ca is not None and cb is not None and ca.kind == cb.kind == "circle":
            return ca, cb
    a_ = LA - np.roll(LA, 1, axis=0)
    b_ = np.roll(LA, -1, axis=0) - LA
    turn = np.abs(np.arctan2(a_[:, 0] * b_[:, 1] - a_[:, 1] * b_[:, 0], np.einsum("ij,ij->i", a_, b_)))
    s0 = int(np.argmax(turn))

    def split(s):
        QA = np.vstack([LA[s:], LA[:s], LA[s:s + 1]])
        QB = np.vstack([LB[s:], LB[:s], LB[s:s + 1]])
        out, i, m = [], 0, len(QA)
        while i < m - 1:
            good, kind, step, bad = i + 1, "line", 1, None
            while True:
                j = min(good + step, m - 1)
                if j == good:
                    break
                k = _holds2(QA, QB, i, j, tol, rmax)
                if k is None:
                    bad = j
                    break
                good, kind = j, k
                step *= 2
            while bad is not None and bad - good > 1:
                j = (good + bad) // 2
                k = _holds2(QA, QB, i, j, tol, rmax)
                if k is None:
                    bad = j
                else:
                    good, kind = j, k
            kind = _holds2(QA, QB, i, good, tol, rmax) or "line"
            if kind == "arc" and good - i < 3:
                kind = "line"
            out.append([i, good, kind])
            i = good
        return QA, QB, out
    QA, QB, runs = split(s0)
    lines = [(float(np.linalg.norm(QA[j] - QA[i])), i, j) for i, j, k in runs if k == "line"]
    if lines:
        _, i, j = max(lines)
        QA, QB, runs = split((s0 + ((i + j) // 2 if j - i >= 2 else i)) % len(LA))
    if len(runs) < 2:
        return None
    a = _assemble(QA, [list(r) for r in runs], LA, tol, size)
    b = _assemble(QB, [list(r) for r in runs], LB, tol, size)
    if a is None or b is None:
        return None
    return a, b


def _assemble(Q, runs, L, tol, size):
    """The sketch from a split of the closed point list Q into runs."""
    rmax = MAX_RADIUS_FACTOR * max(size, 1e-6)
    for rn in runs:                                     # an arc a line holds as well is a line
        if rn[2] == "arc":
            P = Q[rn[0]:rn[1] + 1]
            if _line_fit(P)[2] <= tol or _circle_fit(P)[1] > rmax:
                rn[2] = "line"
    if len(runs) < 2:
        return None
    prims = []
    for i, j, kind in runs:
        P = Q[i:j + 1]
        if kind == "line":
            m, t, _ = _line_fit(P)
            if np.linalg.norm(P[-1] - P[0]) > 1e-12 and t @ (P[-1] - P[0]) < 0:
                t = -t
            t = _snap_dir(t, P, tol / 4)
            prims.append(("line", m, t, P))
        else:
            c, r, _ = _circle_fit(P)
            mid = P[len(P) // 2]
            ccw = ((P[0] - c)[0] * (mid - c)[1] - (P[0] - c)[1] * (mid - c)[0]) > 0
            prims.append(("arc", c, r, P, ccw))
    n = len(prims)
    # corners: where each primitive meets the next
    corner = []
    for k in range(n):
        a, b = prims[k], prims[(k + 1) % n]
        near = a[3][-1]
        q = _isect(a, b, near, tol)
        reach = 2 * tol + (0.05 * size if a[0] == b[0] == "line" else 0.0)
        if "arc" in (a[0], b[0]):                       # a tangent joint may sit where the greedy split was not
            reach = max(reach, 0.5 * min(p[2] for p in (a, b) if p[0] == "arc"))
        if q is None or np.linalg.norm(q - near) > reach:
            q = near
        corner.append(np.asarray(q, dtype=np.float64))
    # node k sits at the end of primitive k (the corner between k and k + 1); edges[k] joins corner k-1 to corner k
    skip_arc = set()
    for k in range(n):
        a = prims[k]
        if a[0] == "arc":
            prv, nxt = prims[k - 1], prims[(k + 1) % n]
            sweep = _sweep(a)
            if prv[0] == "line" and nxt[0] == "line" and sweep < math.radians(170) and _tangent(prv, a, tol) and _tangent(nxt, a, tol):
                skip_arc.add(k)
    out_nodes, out_edges = [], []
    # walk the primitives: a line ends at a corner node; a tangent arc between two lines becomes the radius of the
    # corner where those lines meet
    for k in range(n):
        a = prims[k]
        if k in skip_arc:
            continue
        nxt = (k + 1) % n
        if a[0] == "line":
            if nxt in skip_arc:
                arc = prims[nxt]
                after = prims[(nxt + 1) % n]
                q = _isect(a, after, arc[3][len(arc[3]) // 2])
                if q is None:
                    q = corner[k]
                out_nodes.append(Node(np.asarray(q, dtype=np.float64), float(arc[2])))
            else:
                out_nodes.append(Node(corner[k], 0.0))
            out_edges.append(Edge("line"))
        else:
            out_nodes.append(Node(corner[k], 0.0))
            out_edges.append(Edge("arc", float(a[2]), bool(a[4]), _sweep(a) > math.pi, a[1]))
    if len(out_nodes) < 2 or (len(out_nodes) == 2 and all(e.kind == "line" for e in out_edges)):
        return None
    # out_edges[i] runs from out_nodes[i-1] to out_nodes[i]: rotate so edges[i] joins nodes[i] and nodes[i+1]
    out_edges = out_edges[1:] + out_edges[:1]
    # a sharp node between two lines that go on straight is no corner: drop it (the two lines are one)
    k = 0
    while len(out_nodes) > 3 and k < len(out_nodes):
        m = len(out_nodes)
        if out_nodes[k].r == 0 and out_edges[k - 1].kind == "line" and out_edges[k].kind == "line":
            a, b, c = out_nodes[k - 1].p, out_nodes[k].p, out_nodes[(k + 1) % m].p
            u, w, ac = b - a, c - b, c - a
            lu, lw, lac = float(np.linalg.norm(u)), float(np.linalg.norm(w)), float(np.linalg.norm(ac))
            off = abs(float(ac[0] * u[1] - ac[1] * u[0])) / max(lac, 1e-300)     # b's distance from the line a-c
            if lu < 1e-9 or lw < 1e-9 or (float(u @ w) > 0 and off <= tol / 4):
                del out_nodes[k]
                del out_edges[k]                        # the edge into k now runs on to the next node
                k = max(k - 1, 0)
                continue
        k += 1
    lp = Loop("path", out_nodes, out_edges)
    try:
        lp.err = deviation(lp, L)
    except ValueError:                                  # rounded corners that do not fit their lines
        return None
    return lp


def _sweep(a) -> float:
    c, P = a[1], a[3]
    u, w = P[:-1] - c, P[1:] - c
    ang = np.arctan2(u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0], np.einsum("ij,ij->i", u, w))
    return abs(float(ang.sum()))


# ---- the sketch as points (to measure it, and to draw it) -------------------------------------------------------------

def _arc_centre(p0, p1, R, ccw, large):
    ch = p1 - p0
    L = float(np.linalg.norm(ch))
    R = max(R, L / 2)
    m = (p0 + p1) / 2
    h = math.sqrt(max(R * R - L * L / 4, 0.0))
    nrm = np.array([-ch[1], ch[0]]) / max(L, 1e-300)
    return m + (1.0 if ccw != large else -1.0) * h * nrm, R       # left of p0->p1 for a ccw minor arc


def _arc_pts(p0, p1, R, ccw, large, n=24):
    if float(np.linalg.norm(p1 - p0)) < 1e-12:
        return np.array([p0])
    c, R = _arc_centre(p0, p1, R, ccw, large)
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    if ccw:
        while a1 <= a0:
            a1 += 2 * math.pi
    else:
        while a1 >= a0:
            a1 -= 2 * math.pi
    t = np.linspace(a0, a1, n)
    return np.c_[c[0] + R * np.cos(t), c[1] + R * np.sin(t)]


def path(nodes, edges) -> list:
    """The pieces of a sketch: [("line", a, b) | ("arc", a, mid, b)] in 2-D, from nodes [(x, y, corner_radius)] and
    edges [None for a line | (R, ccw, large) for an arc], edges[i] joining nodes[i] and nodes[i + 1]. A corner radius
    rounds a corner between two lines (the tangent arc). Raises ValueError when a radius does not fit its corner."""
    P = [np.array([float(x), float(y)]) for x, y, _ in nodes]
    m = len(P)
    ins, outs, rounds = [], [], []
    for i in range(m):
        p, r = P[i], float(nodes[i][2] or 0.0)
        if r > 0 and edges[i - 1] is None and edges[i] is None:
            u_in, u_out = p - P[i - 1], P[(i + 1) % m] - p
            l_in, l_out = float(np.linalg.norm(u_in)), float(np.linalg.norm(u_out))
            u_in, u_out = u_in / max(l_in, 1e-300), u_out / max(l_out, 1e-300)
            th = math.acos(float(np.clip(-u_in @ u_out, -1, 1)))
            if th < 1e-6 or th > math.pi - 1e-6:
                ins.append(p)
                outs.append(p)
                rounds.append(None)
                continue
            t = r / math.tan(th / 2)
            if t > l_in * 1.001 or t > l_out * 1.001:
                raise ValueError(f"a corner radius of {r:g} does not fit the corner at ({p[0]:.3f}, {p[1]:.3f})")
            ins.append(p - u_in * t)
            outs.append(p + u_out * t)
            rounds.append((r, (u_in[0] * u_out[1] - u_in[1] * u_out[0]) > 0))
        else:
            ins.append(p)
            outs.append(p)
            rounds.append(None)
    for i in range(m):                                   # two rounded corners must not overlap on the line between
        j = (i + 1) % m
        if edges[i] is None:
            L = float(np.linalg.norm(P[j] - P[i]))
            used = float(np.linalg.norm(outs[i] - P[i])) + float(np.linalg.norm(ins[j] - P[j]))
            if used > L * 1.001 + 1e-9:
                raise ValueError(f"the corner radii at ({P[i][0]:.3f}, {P[i][1]:.3f}) and ({P[j][0]:.3f}, {P[j][1]:.3f}) "
                                 "overlap")
    out = []
    for i in range(m):
        if rounds[i] is not None:
            q = _arc_pts(ins[i], outs[i], rounds[i][0], rounds[i][1], False, 3)
            out.append(("arc", q[0], q[1], q[2]))
        j = (i + 1) % m
        a, b = outs[i], ins[j]
        if float(np.linalg.norm(b - a)) < 1e-9:
            continue
        if edges[i] is None:
            out.append(("line", a, b))
        else:
            R, ccw, large = edges[i]
            q = _arc_pts(a, b, float(R), bool(ccw), bool(large), 3)
            out.append(("arc", q[0], q[1], q[2]))
    return out


def spec(lp: Loop):
    """(nodes, edges) of a path loop, in the form `path` and ops.profile take."""
    return ([(float(n.p[0]), float(n.p[1]), float(n.r)) for n in lp.nodes],
            [None if e.kind == "line" else (float(e.R), bool(e.ccw), bool(e.large)) for e in lp.edges])


def points(lp: Loop, n: int = 24) -> np.ndarray:
    """The sketch as a dense closed polyline (for measuring and drawing)."""
    if lp.kind == "circle":
        t = np.linspace(0, 2 * math.pi, 4 * n, endpoint=False)
        return np.c_[lp.c[0] + lp.r * np.cos(t), lp.c[1] + lp.r * np.sin(t)]
    return polyline(*spec(lp), n=n)


def polyline(nodes, edges, n: int = 24) -> np.ndarray:
    out = []
    for pc in path(nodes, edges):
        if pc[0] == "line":
            out.append(np.array([pc[1]]))
        else:
            a, m, b = pc[1], pc[2], pc[3]
            c = _circ3(a, m, b)
            if c is None:
                out.append(np.array([a, m]))
                continue
            cen, R = c
            a0, a1, am = (math.atan2(q[1] - cen[1], q[0] - cen[0]) for q in (a, b, m))
            ccw = ((a - cen)[0] * (m - cen)[1] - (a - cen)[1] * (m - cen)[0]) > 0
            while ccw and a1 <= a0:
                a1 += 2 * math.pi
            while not ccw and a1 >= a0:
                a1 -= 2 * math.pi
            t = np.linspace(a0, a1, n)[:-1]
            out.append(np.c_[cen[0] + R * np.cos(t), cen[1] + R * np.sin(t)])
    return np.vstack(out) if out else np.zeros((0, 2))


def _circ3(a, m, b):
    ax, ay = a
    bx, by = m
    cx, cy = b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-14:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    c = np.array([ux, uy])
    return c, float(np.linalg.norm(a - c))


def _seg_brute(P, A, B):
    AB = B - A
    L2 = np.maximum((AB * AB).sum(1), 1e-300)
    best = np.full(len(P), np.inf)
    for s in range(0, len(A), 256):
        a, ab, l2 = A[s:s + 256], AB[s:s + 256], L2[s:s + 256]
        t = np.clip(((P[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
        q = a[None] + t[..., None] * ab[None]
        best = np.minimum(best, np.linalg.norm(P[:, None, :] - q, axis=2).min(axis=1))
    return best


def _seg_dist(P, A, B, k: int = 8):
    """Distance from each point of P to the segments A->B (exact for small inputs; for large ones the segments are cut
    to similar lengths and each point is measured against the k segments whose middles are nearest)."""
    P = np.asarray(P, dtype=np.float64)
    if len(P) * len(A) <= 40_000:
        return _seg_brute(P, A, B)
    from scipy.spatial import cKDTree
    L = np.linalg.norm(B - A, axis=1)
    h = max(float(np.median(L)), float(L.sum()) / (4 * len(L) + 1000), 1e-9)
    n = np.maximum(1, np.ceil(L / h).astype(np.int64))
    idx = np.repeat(np.arange(len(A)), n)
    j = np.concatenate([np.arange(m) for m in n])
    t0 = j / n[idx]
    t1 = (j + 1) / n[idx]
    A2 = A[idx] + t0[:, None] * (B - A)[idx]
    B2 = A[idx] + t1[:, None] * (B - A)[idx]
    tree = cKDTree((A2 + B2) / 2)
    kk = min(k, len(A2))
    _, nn = tree.query(P, k=kk)
    nn = nn.reshape(len(P), -1)
    a, b = A2[nn], B2[nn]
    ab = b - a
    t = np.clip(((P[:, None, :] - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-300), 0, 1)
    q = a + t[..., None] * ab
    return np.linalg.norm(P[:, None, :] - q, axis=2).min(axis=1)


def deviation(lp: Loop, L: np.ndarray) -> float:
    """Two-sided largest distance between the sketch and the loop's points."""
    S = points(lp, 48)
    d1 = _seg_dist(L, S, np.roll(S, -1, axis=0))
    d2 = _seg_dist(S, L, np.roll(L, -1, axis=0))
    return float(max(d1.max(), d2.max()))


def same(a: np.ndarray, b: np.ndarray, tol: float) -> bool:
    """Are two closed polylines the same curve within tol?"""
    if abs(abs(_area2(a)) - abs(_area2(b))) > 2 * tol * (np.ptp(a, axis=0).sum() + np.ptp(b, axis=0).sum()) + 1e-12:
        return False
    return max(_seg_dist(a, b, np.roll(b, -1, axis=0)).max(), _seg_dist(b, a, np.roll(a, -1, axis=0)).max()) <= tol
