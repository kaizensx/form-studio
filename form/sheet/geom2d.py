"""Plane geometry for flat patterns and cut files (numpy only, no kernel): entities, closed loops, areas, holes,
gaps and crossings.

An entity is a dict: {"t": "line", "a": [x, y], "b": [x, y]}, {"t": "arc", "c": [x, y], "r": R, "a0": deg,
"a1": deg} (counter-clockwise from a0 to a1), {"t": "circle", "c", "r"} or {"t": "poly", "pts": [[x, y], ...]}.
Any other keys (layer, face, source handle) ride along.
"""
from __future__ import annotations

import math

import numpy as np

ARC_STEP_DEG = 3.0        # arcs become polylines at this angular step for areas, distances and crossings


def ends(e: dict) -> tuple[np.ndarray, np.ndarray] | None:
    t = e["t"]
    if t == "line":
        return np.asarray(e["a"], float), np.asarray(e["b"], float)
    if t == "arc":
        c, r = np.asarray(e["c"], float), float(e["r"])
        a0, a1 = math.radians(e["a0"]), math.radians(e["a1"])
        return c + r * np.array([math.cos(a0), math.sin(a0)]), c + r * np.array([math.cos(a1), math.sin(a1)])
    if t == "poly":
        p = np.asarray(e["pts"], float)
        if e.get("closed"):
            return None
        return p[0], p[-1]
    return None                                           # circle: closed by itself


def sweep(e: dict) -> float:
    """An arc's counter-clockwise sweep in degrees, in (0, 360]."""
    s = (float(e["a1"]) - float(e["a0"])) % 360.0
    return 360.0 if s < 1e-9 else s


def polyline(e: dict, step_deg: float = ARC_STEP_DEG) -> np.ndarray:
    """Points along the entity from its start to its end (a circle or closed poly: closed, first point repeated)."""
    t = e["t"]
    if t == "line":
        return np.array([e["a"], e["b"]], float)
    if t == "poly":
        p = np.asarray(e["pts"], float)
        return np.vstack([p, p[:1]]) if e.get("closed") else p
    c, r = np.asarray(e["c"], float), float(e["r"])
    if t == "circle":
        a0, sw = 0.0, 360.0
    else:
        a0, sw = float(e["a0"]), sweep(e)
    n = max(2, int(math.ceil(sw / step_deg)) + 1)
    a = np.radians(a0 + np.linspace(0.0, sw, n))
    return c + r * np.stack([np.cos(a), np.sin(a)], axis=1)


def end_tangents(e: dict, rev: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Unit directions of travel at the entity's start and end (exact for lines and arcs), traversed backwards when
    rev."""
    t = e["t"]
    if t == "arc":
        a0, a1 = math.radians(float(e["a0"])), math.radians(float(e["a1"]))
        s = np.array([-math.sin(a0), math.cos(a0)])
        f = np.array([-math.sin(a1), math.cos(a1)])
    else:
        P = polyline(e)
        s, f = P[1] - P[0], P[-1] - P[-2]
        s, f = s / max(np.linalg.norm(s), 1e-12), f / max(np.linalg.norm(f), 1e-12)
    return (-f, -s) if rev else (s, f)


def length(e: dict) -> float:
    t = e["t"]
    if t == "line":
        return float(np.linalg.norm(np.subtract(e["b"], e["a"])))
    if t == "arc":
        return math.radians(sweep(e)) * float(e["r"])
    if t == "circle":
        return 2 * math.pi * float(e["r"])
    p = polyline(e)
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


def chain(entities: list, tol: float = 1e-3) -> tuple[list, list]:
    """Closed loops from entities joined end to end within tol. Returns (loops, open_chains); a loop is
    {"items": [(entity index, reversed?)], "pts": closed polyline (first point repeated), "area": signed}; an open
    chain is {"items", "ends": [p, q]} with its two free ends."""
    loops, opens = [], []
    pending = []
    for i, e in enumerate(entities):
        if ends(e) is None:
            p = polyline(e)
            loops.append({"items": [(i, False)], "pts": p, "area": area(p)})
        else:
            pending.append(i)
    if not pending:
        return loops, opens
    E = {i: ends(entities[i]) for i in pending}
    pts = np.array([p for i in pending for p in E[i]])
    owner = [(i, k) for i in pending for k in (0, 1)]
    cell = max(tol, 1e-9)
    grid: dict = {}
    for j, p in enumerate(pts):
        grid.setdefault((int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))), []).append(j)

    def near(p, skip):
        gx, gy = int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))
        best, bd = None, tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if owner[j][0] in skip:
                        continue
                    d = float(np.hypot(*(pts[j] - p)))
                    if d <= bd:
                        best, bd = j, d
        return best

    used: set = set()
    for i in pending:
        if i in used:
            continue
        used.add(i)
        items = [(i, False)]
        head = E[i][1]
        start = E[i][0]
        closed = False
        while True:
            if float(np.hypot(*(head - start))) <= tol and len(items) > 1:
                closed = True
                break
            j = near(head, used)
            if j is None:
                break
            k, side = owner[j]
            used.add(k)
            items.append((k, side == 1))
            head = E[k][0] if side == 1 else E[k][1]
        if not closed:
            # walk back from the start too, so an open chain reports both of its free ends
            tail = start
            while True:
                j = near(tail, used)
                if j is None:
                    break
                k, side = owner[j]
                used.add(k)
                items.insert(0, (k, side == 0))
                tail = E[k][1] if side == 0 else E[k][0]
            if float(np.hypot(*(head - tail))) <= tol and len(items) > 1:
                closed = True
            else:
                opens.append({"items": items, "ends": [tail.tolist(), head.tolist()]})
                continue
        segs = []
        for k, rev in items:
            p = polyline(entities[k])
            segs.append(p[::-1] if rev else p)
        P = np.vstack([segs[0]] + [s[1:] for s in segs[1:]])
        if float(np.hypot(*(P[-1] - P[0]))) > 0:
            P = np.vstack([P, P[:1]])
        loops.append({"items": items, "pts": P, "area": area(P)})
    return loops, opens


def area(P: np.ndarray) -> float:
    P = np.asarray(P, float)
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def exact_area(loop: dict, entities: list) -> float:
    """The signed area of a loop with arcs counted exactly (the polyline area plus each arc's circular segment)."""
    a = area(loop["pts"])
    for k, rev in loop["items"]:
        e = entities[k]
        if e["t"] not in ("arc", "circle"):
            continue
        r = float(e["r"])
        th = math.radians(360.0 if e["t"] == "circle" else sweep(e))
        n = max(2, int(math.ceil(math.degrees(th) / ARC_STEP_DEG)) + 1)
        dth = th / (n - 1)
        seg = 0.5 * r * r * (dth - math.sin(dth)) * (n - 1)
        a += -seg if rev else seg
    return a


def inside(pt, P) -> bool:
    x, y = float(pt[0]), float(pt[1])
    P = np.asarray(P, float)
    xi, yi = P[:-1, 0], P[:-1, 1]
    xj, yj = P[1:, 0], P[1:, 1]
    c = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / np.where(yj - yi == 0, 1e-300, yj - yi) + xi)
    return bool(np.count_nonzero(c) % 2)


def nest(loops: list) -> list:
    """Each loop's depth (0 outer boundary, 1 hole, 2 a part inside a hole, ...) and parent, by containment."""
    order = sorted(range(len(loops)), key=lambda i: -abs(loops[i]["area"]))
    for i in order:
        loops[i]["parent"] = None
        loops[i]["depth"] = 0
    for a, i in enumerate(order):
        p = loops[i]["pts"][0]
        for j in reversed(order[:a]):
            if abs(loops[j]["area"]) > abs(loops[i]["area"]) and inside(p, loops[j]["pts"]):
                loops[i]["parent"] = j
                loops[i]["depth"] = loops[j]["depth"] + 1
                break
    return loops


def _segments(P) -> tuple[np.ndarray, np.ndarray]:
    P = np.asarray(P, float)
    return P[:-1], P[1:]


def seg_dist(P, Q) -> tuple[float, np.ndarray, np.ndarray]:
    """The smallest distance between two polylines, and the two nearest points (vertex to segment, both ways)."""
    best = (math.inf, None, None)
    for A, B in ((np.asarray(P, float), np.asarray(Q, float)), (np.asarray(Q, float), np.asarray(P, float))):
        if len(B) < 2:
            continue
        a, b = _segments(B)
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(axis=1), 1e-300)
        for k in range(0, len(A), 512):
            pts = A[k:k + 512]
            t = np.clip(((pts[:, None, :] - a[None]) * ab[None]).sum(axis=2) / L2[None], 0, 1)
            proj = a[None] + t[..., None] * ab[None]
            d = np.linalg.norm(pts[:, None, :] - proj, axis=2)
            i, j = np.unravel_index(int(np.argmin(d)), d.shape)
            if d[i, j] < best[0]:
                best = (float(d[i, j]), pts[i], proj[i, j])
    return best


def crossings(P, Q=None, tol: float = 1e-7) -> list:
    """Points where segments of P cross segments of Q (or P's own non-adjacent segments when Q is None)."""
    P = np.asarray(P, float)
    a0, a1 = _segments(P)
    if Q is None:
        b0, b1 = a0, a1
    else:
        Q = np.asarray(Q, float)
        b0, b1 = _segments(Q)
    out = []
    lo_a, hi_a = np.minimum(a0, a1), np.maximum(a0, a1)
    lo_b, hi_b = np.minimum(b0, b1), np.maximum(b0, b1)
    n = len(a0)
    for k in range(0, n, 256):
        sl = slice(k, k + 256)
        ov = ((lo_a[sl, None, 0] <= hi_b[None, :, 0] + tol) & (hi_a[sl, None, 0] >= lo_b[None, :, 0] - tol) &
              (lo_a[sl, None, 1] <= hi_b[None, :, 1] + tol) & (hi_a[sl, None, 1] >= lo_b[None, :, 1] - tol))
        for i, j in zip(*np.nonzero(ov)):
            i += k
            if Q is None and (abs(i - j) <= 1 or (i == 0 and j == n - 1) or (j == 0 and i == n - 1) or j < i):
                continue
            p, r = a0[i], a1[i] - a0[i]
            q, s = b0[j], b1[j] - b0[j]
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-14:
                continue
            t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
            u = ((q[0] - p[0]) * r[1] - (q[1] - p[1]) * r[0]) / den
            if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
                out.append((p + t * r).tolist())
    return out


def loop_width(loop: dict, entities: list) -> float:
    """A hole's narrowest width: a circle's diameter exactly, otherwise the narrowest strip of its polyline (arcs at
    ARC_STEP_DEG, so a slot's width is exact and a curved hole's is within the chord error)."""
    if len(loop["items"]) == 1 and entities[loop["items"][0][0]]["t"] == "circle":
        return 2.0 * float(entities[loop["items"][0][0]]["r"])
    return min_width(loop["pts"])


def min_width(P) -> float:
    """The width of the smallest-width enclosing strip of a closed polyline (rotating calipers on its hull): a
    circle's diameter, a slot's width."""
    return min_rect(P)[0]


def min_rect(P) -> tuple[float, float]:
    """(width, length) of the enclosing rectangle aligned with the smallest-width strip: a part's short and long
    side as a sheet would hold it."""
    pts = np.unique(np.round(np.asarray(P, float), 9), axis=0)
    if len(pts) < 3:
        return 0.0, 0.0
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    H = np.array(lower[:-1] + upper[:-1])
    best = (math.inf, 0.0)
    for i in range(len(H)):
        a, b = H[i], H[(i + 1) % len(H)]
        d = b - a
        L = float(np.hypot(*d))
        if L < 1e-12:
            continue
        nrm = np.array([-d[1], d[0]]) / L
        w = float(np.max(np.abs((H - a) @ nrm)))
        if w < best[0]:
            along = (H - a) @ (d / L)
            best = (w, float(along.max() - along.min()))
    return best


def bbox(entities: list) -> tuple[np.ndarray, np.ndarray]:
    P = np.vstack([polyline(e) for e in entities]) if entities else np.zeros((1, 2))
    return P.min(axis=0), P.max(axis=0)


def transform(e: dict, R: np.ndarray, t: np.ndarray) -> dict:
    """A rigid motion (R a proper 2x2 rotation) of one entity."""
    e = dict(e)
    ang = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    if e["t"] == "line":
        e["a"] = (R @ np.asarray(e["a"]) + t).tolist()
        e["b"] = (R @ np.asarray(e["b"]) + t).tolist()
    elif e["t"] in ("arc", "circle"):
        e["c"] = (R @ np.asarray(e["c"]) + t).tolist()
        if e["t"] == "arc":
            e["a0"] = (e["a0"] + ang) % 360.0
            e["a1"] = (e["a1"] + ang) % 360.0
    else:
        e["pts"] = (np.asarray(e["pts"]) @ R.T + t).tolist()
    return e
