"""Plane sections of a closed triangle mesh: closed loops in the plane, measured, simplified and drawn with dimensions.

A section is cut through the mesh's edges (each crossing edge gives one point, shared by its two triangles), so the
loops close exactly. Loops are classified as outlines (material inside) or openings (holes, pockets, slots) by how
many other loops contain them, and each is described the way a drawing would: a circle's diameter, a rectangle's
sides and corner radius, an outline's extent; the vector outline is simplified to within 0.01 mm.
"""
from __future__ import annotations

import math

import numpy as np

AXES = "xyz"
PLANE_UV = {0: (1, 2), 1: (0, 2), 2: (0, 1)}          # the in-plane coordinates of a section across X, Y, Z


def cut(V: np.ndarray, F: np.ndarray, axis: int, level: float) -> list[np.ndarray]:
    """Closed loops (each (n, 2), in the plane's u, v coordinates) where the plane `axis` = level cuts the mesh."""
    from ..recon.mesh import edges
    span = float(np.ptp(V[:, axis])) or 1.0
    d = V[:, axis] - level
    if np.any(np.abs(d) < 1e-9 * span):                 # a vertex exactly on the plane: move the plane off it
        level += 1e-6 * span
        d = V[:, axis] - level
    E, tri, eo, _ = edges(F)
    cross = (d[E[:, 0]] > 0) != (d[E[:, 1]] > 0)
    if not cross.any():
        return []
    a, b = E[:, 0], E[:, 1]
    t = d[a] / np.where(cross, d[a] - d[b], 1.0)
    P = V[a] + t[:, None] * (V[b] - V[a])
    u, v = PLANE_UV[axis]
    pts = P[:, [u, v]]
    # each triangle the plane crosses has exactly two crossing edges: they make one segment
    hit = cross[eo]
    rows = np.flatnonzero(hit)
    tri_h, e_h = tri[rows], eo[rows]
    o = np.argsort(tri_h, kind="stable")
    tri_h, e_h = tri_h[o], e_h[o]
    nb = {}
    for k in range(0, len(tri_h) - 1):
        if tri_h[k] == tri_h[k + 1] and (k == 0 or tri_h[k - 1] != tri_h[k]):
            e1, e2 = int(e_h[k]), int(e_h[k + 1])
            nb.setdefault(e1, []).append(e2)
            nb.setdefault(e2, []).append(e1)
    loops, seen = [], set()
    for s in nb:
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nxt = [x for x in nb[cur] if x != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            if cur == s or cur in seen:
                break
            seen.add(cur)
            loop.append(cur)
        if len(loop) >= 3:
            loops.append(pts[loop])
    return loops


def area2(L: np.ndarray) -> float:
    x, y = L[:, 0], L[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def inside(pt, L: np.ndarray) -> bool:
    x, y = L[:, 0], L[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = ((y > pt[1]) != (y2 > pt[1])) & (pt[0] < (x2 - x) * (pt[1] - y) / np.where(y2 != y, y2 - y, 1e-300) + x)
    return bool(np.count_nonzero(c) % 2)


def simplify(L: np.ndarray, eps: float) -> np.ndarray:
    """Douglas-Peucker on a closed loop (keeps the two points farthest apart)."""
    if len(L) < 4:
        return L
    i0 = 0
    i1 = int(np.argmax(np.linalg.norm(L - L[0], axis=1)))

    def dp(P):
        if len(P) < 3:
            return P
        a, b = P[0], P[-1]
        ab = b - a
        n = np.linalg.norm(ab)
        dd = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / n if n > 1e-12 else np.linalg.norm(P - a, axis=1)
        k = int(np.argmax(dd))
        if dd[k] <= eps:
            return np.array([a, b])
        return np.vstack([dp(P[:k + 1])[:-1], dp(P[k:])])
    A = dp(L[i0:i1 + 1])
    B = dp(np.vstack([L[i1:], L[:1]]))
    return np.vstack([A[:-1], B[:-1]])


def _circle(L):
    x, y = L[:, 0], L[:, 1]
    M = np.c_[x, y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(M, -(x * x + y * y), rcond=None)
    cx, cy = -sol[0] / 2, -sol[1] / 2
    r = math.sqrt(max(cx * cx + cy * cy - sol[2], 0.0))
    res = float(np.abs(np.hypot(x - cx, y - cy) - r).max())
    return (cx, cy), r, res


def describe(L: np.ndarray, tol: float = 0.02) -> dict:
    """What a loop is: circle, rectangle (with corner radius), slot (two half circles) or outline, with its sizes."""
    lo, hi = L.min(axis=0), L.max(axis=0)
    w, h = (hi - lo).tolist()
    out = {"size": [round(w, 3), round(h, 3)], "center": [round(float(x), 3) for x in (lo + hi) / 2],
           "area_mm2": round(abs(area2(L)), 3)}
    c, r, res = _circle(L)
    if len(L) >= 8 and res <= max(tol, 0.01 * r) * 2.5 + 0.01 and abs(w - 2 * r) < 0.05 * r + tol and abs(h - 2 * r) < 0.05 * r + tol:
        out.update(kind="circle", diameter=round(2 * r, 3), center=[round(float(c[0]), 3), round(float(c[1]), 3)])
        return out
    S = simplify(L, max(tol / 2, 0.005))
    for _ in range(3):                                  # a point in the middle of a straight side: drop it
        if len(S) < 4:
            break
        a_, b_ = S - np.roll(S, 1, axis=0), np.roll(S, -1, axis=0) - S
        turn = np.abs(a_[:, 0] * b_[:, 1] - a_[:, 1] * b_[:, 0]) / np.maximum(
            np.linalg.norm(a_, axis=1) * np.linalg.norm(b_, axis=1), 1e-300)
        straight = (turn < 2e-3) & (np.einsum("ij,ij->i", a_, b_) > 0)
        if not straight.any():
            break
        S = S[~straight]
    seg = np.roll(S, -1, axis=0) - S
    ln = np.linalg.norm(seg, axis=1)
    axis_al = (np.abs(seg[:, 0]) < 1e-3 * ln) | (np.abs(seg[:, 1]) < 1e-3 * ln)
    longs = (ln > 0.3 * min(w, h)) & axis_al
    A = abs(area2(L))
    if 2 <= longs.sum() <= 4 and min(w, h) > 0:
        # a rounded rectangle has area w*h - (4 - pi) r^2
        r_c = math.sqrt(max(w * h - A, 0.0) / (4 - math.pi))
        ideal = w * h - (4 - math.pi) * r_c * r_c
        if abs(ideal - A) < 0.02 * A and r_c <= min(w, h) / 2 + tol:
            if longs.sum() == 2 and abs(r_c - min(w, h) / 2) < max(tol * 3, 0.03 * min(w, h)):
                out.update(kind="slot", width=round(min(w, h), 3), length=round(max(w, h), 3))
                return out
            if longs.sum() == 4:
                out.update(kind="rectangle", corner_radius=round(r_c, 3) if r_c > tol else 0.0)
                return out
    out.update(kind="outline", vertices=int(len(S)))
    return out


def _fit_circle(P):
    x, y = P[:, 0], P[:, 1]
    M = np.c_[x, y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(M, -(x * x + y * y), rcond=None)
    cx, cy = -sol[0] / 2, -sol[1] / 2
    r = math.sqrt(max(cx * cx + cy * cy - sol[2], 0.0))
    return np.array([cx, cy]), r, float(np.abs(np.hypot(x - cx, y - cy) - r).max()) if r > 0 else np.inf


def _dense(P, c, step_deg: float = 25.0) -> bool:
    """Points that really trace an arc about c: no two in a row more than step_deg apart (three far-apart corners
    also lie on some circle)."""
    a = np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0])
    d = np.abs((np.diff(a) + np.pi) % (2 * np.pi) - np.pi)
    return bool(np.degrees(d).max() <= step_deg)


def _line_dev(P):
    a, b = P[0], P[-1]
    ab = b - a
    n = np.linalg.norm(ab)
    if n < 1e-12:
        return np.inf
    return float(np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])).max() / n)


def segments(L: np.ndarray, tol: float = 0.01, max_radius: float = 500.0) -> list:
    """A closed loop as a drawing would dimension it: straight lines and circular arcs (centre, radius, sweep), each
    within tol of the loop. Starts at the sharpest corner; grows each run while it stays a line, else an arc."""
    n = len(L)
    if n < 3:
        return []
    a_, b_ = L - np.roll(L, 1, axis=0), np.roll(L, -1, axis=0) - L
    turn = np.abs(np.arctan2(a_[:, 0] * b_[:, 1] - a_[:, 1] * b_[:, 0], np.einsum("ij,ij->i", a_, b_)))
    s = int(np.argmax(turn))
    Q = np.vstack([L[s:], L[:s], L[s:s + 1]])           # closed, starting and ending at the sharpest corner
    out, i = [], 0
    m = len(Q)
    while i < m - 1:
        j = i + 1
        kind = "line"
        best = None
        while j + 1 < m:
            seg = Q[i:j + 2]
            if _line_dev(seg) <= tol:
                j += 1
                kind = "line"
                continue
            if len(seg) >= 4:
                c, r, dev = _fit_circle(seg)
                if dev <= tol and r < max_radius and _dense(seg, c):
                    j += 1
                    kind, best = "arc", (c, r)
                    continue
            break
        seg = Q[i:j + 1]
        if kind == "arc" and len(seg) >= 4:
            c, r, _ = _fit_circle(seg)
            u, w = seg[:-1] - c, seg[1:] - c
            cross = u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]
            sweep = float(np.degrees(np.sum(np.arctan2(cross, np.einsum("ij,ij->i", u, w)))))
            out.append({"arc": {"center": [round(float(c[0]), 3), round(float(c[1]), 3)], "radius": round(r, 3),
                                "from": [round(float(seg[0][0]), 3), round(float(seg[0][1]), 3)],
                                "to": [round(float(seg[-1][0]), 3), round(float(seg[-1][1]), 3)],
                                "sweep_deg": round(sweep, 2)}})
        else:
            out.append({"line": [[round(float(seg[0][0]), 3), round(float(seg[0][1]), 3)],
                                 [round(float(seg[-1][0]), 3), round(float(seg[-1][1]), 3)]]})
        i = j
    if len(out) > 2 and "arc" in out[0] and "arc" in out[-1]:    # the start fell inside an arc: join its two halves
        a, b = out[-1]["arc"], out[0]["arc"]
        if abs(a["radius"] - b["radius"]) <= 2 * tol and math.dist(a["center"], b["center"]) <= 2 * tol:
            out[0] = {"arc": {**b, "from": a["from"], "sweep_deg": round(a["sweep_deg"] + b["sweep_deg"], 2)}}
            out.pop()
    return out


def analyse(V, F, axis: int, level: float, tol: float = 0.02, max_points: int = 160) -> dict:
    """One section: its loops (outlines and openings), each described and simplified."""
    loops = cut(V, F, axis, level)
    rows = []
    for i, L in enumerate(loops):
        depth = sum(1 for j, M in enumerate(loops) if j != i and inside(L[0], M))
        d = describe(L, tol)
        d["role"] = "outline" if depth % 2 == 0 else "opening"
        eps = tol / 2
        S = simplify(L, eps)
        while len(S) > max_points and eps < 1.0:
            eps *= 2
            S = simplify(L, eps)
        d["outline"] = [[round(float(a), 3), round(float(b), 3)] for a, b in S]
        d["outline_within_mm"] = round(eps, 4)
        sg = segments(L, max(tol / 2, 0.005))
        if len(sg) <= 60:                               # as a drawing would dimension it: lines and arcs
            d["segments"] = sg
        d["_loop"] = L
        rows.append(d)
    rows.sort(key=lambda r: (r["role"] != "outline", -r["area_mm2"]))
    u, v = PLANE_UV[axis]
    return {"plane": f"{AXES[axis]} = {level:g}", "axis": AXES[axis], "level": round(float(level), 4),
            "coords": [AXES[u], AXES[v]], "loops": rows}


def public(sec: dict) -> dict:
    return {**sec, "loops": [{k: v for k, v in r.items() if not k.startswith("_")} for r in sec["loops"]]}


# ---- drawing ---------------------------------------------------------------------------------------------------------

INK = (28, 27, 25)
MUTED = (140, 136, 128)
GRID = (226, 222, 214)
PAPER = (244, 241, 234)
OPEN = (196, 72, 38)
DIM = (38, 92, 150)


def draw(sections: list, title: str, width: int = 1100, bounds=None):
    """One picture of several sections across the same axis, stacked, each with dimension lines. Returns a PIL image."""
    from PIL import Image, ImageDraw
    from ..render import _font
    if not sections:
        return None
    pts = [r["_loop"] for s in sections for r in s["loops"]]
    if bounds is None:
        if not pts:
            return None
        allp = np.vstack(pts)
        lo, hi = allp.min(axis=0), allp.max(axis=0)
    else:
        lo, hi = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
    span = np.maximum(hi - lo, 1e-6)
    margin = 70
    sc = (width - 2 * margin) / span[0]
    panel_h = int(span[1] * sc + 2 * margin)
    if panel_h > 900:                                   # tall sections: fit the height instead
        sc = (900 - 2 * margin) / span[1]
        panel_h = 900
    f, fs, ft = _font(13), _font(11), _font(16)
    img = Image.new("RGB", (width, 36 + panel_h * len(sections)), PAPER)
    d = ImageDraw.Draw(img)
    d.text((12, 10), title, fill=INK, font=ft)
    for k, s in enumerate(sections):
        oy = 36 + k * panel_h
        X = lambda p: (margin + (p[0] - lo[0]) * sc, oy + panel_h - margin - (p[1] - lo[1]) * sc)
        step = 5.0 if span.max() < 120 else 10.0
        for g in np.arange(math.floor(lo[0] / step) * step, hi[0] + step, step):
            x = X((g, lo[1]))[0]
            d.line([(x, oy + margin - 20), (x, oy + panel_h - margin + 20)], fill=GRID)
        for g in np.arange(math.floor(lo[1] / step) * step, hi[1] + step, step):
            y = X((lo[0], g))[1]
            d.line([(margin - 20, y), (width - margin + 20, y)], fill=GRID)
        d.text((12, oy + 6), f"Section {s['plane']}  ({s['coords'][0]} across, {s['coords'][1]} up; grid {step:g} mm)",
               fill=INK, font=f)
        if k:
            d.line([(0, oy), (width, oy)], fill=MUTED)
        for r in s["loops"]:
            L = r["_loop"]
            col = INK if r["role"] == "outline" else OPEN
            d.line([X(p) for p in np.vstack([L, L[:1]])], fill=col, width=2)
        outs = [r for r in s["loops"] if r["role"] == "outline"]
        if outs:                                        # overall dimensions of the section
            A = np.vstack([r["_loop"] for r in outs])
            a, b = A.min(axis=0), A.max(axis=0)
            y = X((a[0], a[1]))[1] + 28
            x0, x1 = X((a[0], 0))[0], X((b[0], 0))[0]
            d.line([(x0, y), (x1, y)], fill=DIM, width=1)
            for xx in (x0, x1):
                d.line([(xx, y - 6), (xx, y + 6)], fill=DIM)
            d.text(((x0 + x1) / 2 - 22, y + 4), f"{b[0] - a[0]:.2f}", fill=DIM, font=f)
            x = X((b[0], 0))[0] + 26
            y0, y1 = X((0, a[1]))[1], X((0, b[1]))[1]
            d.line([(x, y0), (x, y1)], fill=DIM)
            for yy in (y0, y1):
                d.line([(x - 6, yy), (x + 6, yy)], fill=DIM)
            d.text((x + 6, (y0 + y1) / 2 - 6), f"{b[1] - a[1]:.2f}", fill=DIM, font=f)
            d.text((X((a[0], 0))[0], X((0, b[1]))[1] - 18), f"{s['coords'][0]} {a[0]:.2f}..{b[0]:.2f}  "
                   f"{s['coords'][1]} {a[1]:.2f}..{b[1]:.2f}", fill=MUTED, font=fs)
        for r in s["loops"][:40]:                       # label circles, slots, rectangles and openings with their sizes
            if r["kind"] == "circle":
                lab = f"dia {r['diameter']:.2f}"
            elif r["kind"] == "slot":
                lab = f"slot {r['width']:.2f} x {r['length']:.2f}"
            elif r["kind"] == "rectangle":
                lab = f"{r['size'][0]:.2f} x {r['size'][1]:.2f}" + (f" R{r['corner_radius']:.2f}" if r["corner_radius"] else "")
            elif r["role"] == "opening":
                lab = f"{r['size'][0]:.2f} x {r['size'][1]:.2f}"
            else:
                continue
            c = X(r["center"])
            d.text((c[0] + 4, c[1] - 6), lab, fill=OPEN if r["role"] == "opening" else DIM, font=fs)
    return img
