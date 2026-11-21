"""A learned model's CadQuery plan (cq.py) as a Form Studio recipe, placed and snapped onto the mesh.

1. Placement: the model works in its own normalised units. The plan's bounding box is mapped onto the mesh's by one
   scale and one translation; a plan whose proportions do not match the mesh's (more than PROPORTION apart on an axis)
   is refused rather than stretched.
2. Snapping to the mesh: every level (where an extrusion starts or ends) and every outline edge moves to the nearest
   height or coordinate where the mesh has vertices, within SNAP of the part's size; a circle is refitted to the mesh
   vertices on it (centre and diameter) when enough of them lie on one circle. What finds nothing to snap to keeps the
   model's value.
3. Params: the values are pooled the way the program route pools them (program.Pool: equal within a quarter of the
   tolerance -> one Param, round numbers, standard hole sizes, mirrored about the centre): levels (Level), rectangle
   sides (Length) and circle diameters are dimensions; sketch positions (U, W) are positions.

The recipe is then built and verified by the caller like every other candidate. Kernel worker only.
"""
from __future__ import annotations

import numpy as np

from . import cq

PROPORTION = 0.25          # largest relative difference between the plan's and the mesh's extents on any axis
SNAP = 0.02                # snap radius, as a share of the part's largest extent


def _bbox(plan: cq.Solid):
    """The bounding box of the material the plan adds (its added extrusions), in the plan's units."""
    pts = []
    for e in plan.extrusions():
        u, v = e.plane.x, e.plane.y
        for it in e.items:
            if it.mode != "a":
                continue
            if it.kind == "rect":
                loc = [(it.c[0] + sx * it.w / 2, it.c[1] + sy * it.h / 2) for sx in (-1, 1) for sy in (-1, 1)]
            elif it.kind == "circle":
                loc = [(it.c[0] + sx * it.r, it.c[1] + sy * it.r) for sx in (-1, 1) for sy in (-1, 1)]
            else:
                loc = [p for sg in it.segs for p in sg[1:]]
            for x, y in loc:
                for d in (e.d0, e.d1):
                    pts.append(e.plane.origin + x * u + y * v + d * e.plane.n)
    if not pts:
        raise cq.Unsupported("the plan adds no material")
    P = np.array(pts)
    return P.min(axis=0), P.max(axis=0)


def placement(plan: cq.Solid, V) -> tuple[float, np.ndarray]:
    """(scale, translation) mapping the plan onto the mesh: world = scale * plan + translation."""
    lo, hi = _bbox(plan)
    mlo, mhi = V.min(axis=0), V.max(axis=0)
    ext, mext = hi - lo, mhi - mlo
    if float(ext.max()) <= 0:
        raise cq.Unsupported("the plan has no size")
    s = float(mext.max() / ext.max())
    rel = np.abs(s * ext - mext) / max(float(mext.max()), 1e-9)
    if float(rel.max()) > PROPORTION:
        raise cq.Unsupported(f"the plan's proportions differ from the mesh's by {100 * float(rel.max()):.0f}% of its size")
    t = (mlo + mhi) / 2 - s * (lo + hi) / 2
    return s, t


class Snapper:
    """The mesh's own heights and coordinates along each world axis, to snap the plan's values onto."""

    def __init__(self, V, tol):
        self.V, self.tol = V, tol
        self.size = float(np.ptp(V, axis=0).max()) or 1.0
        self.r = max(SNAP * self.size, 3 * tol)
        self.levels = []
        for k in range(3):
            x = np.sort(V[:, k])
            br = np.r_[True, np.diff(x) > tol / 4]
            gid = np.cumsum(br) - 1
            cnt = np.bincount(gid)
            reps = np.bincount(gid, weights=x) / cnt
            self.levels.append((reps, cnt))

    def axis(self, x: float, k: int) -> float:
        """x snapped to the nearest height along world axis k where at least three mesh vertices sit."""
        reps, cnt = self.levels[k]
        ok = cnt >= 3
        if not ok.any():
            return x
        r = reps[ok]
        j = int(np.argmin(np.abs(r - x)))
        return float(r[j]) if abs(float(r[j]) - x) <= self.r else x

    def circle(self, c3, n, r, d0, d1):
        """(centre, radius) refitted to the mesh vertices on this circle's wall between levels d0 and d1 along n, or
        None when fewer than eight lie on one circle."""
        V = self.V
        h = V @ n
        lo, hi = min(d0, d1), max(d0, d1)
        rel = V - c3
        rel = rel - np.outer(rel @ n, n)
        rad = np.linalg.norm(rel, axis=1)
        pick = (h >= lo - self.tol) & (h <= hi + self.tol) & (np.abs(rad - r) <= self.r)
        if pick.sum() < 8:
            return None
        P = V[pick]
        k = int(np.argmax(np.abs(n)))
        a, b = [i for i in range(3) if i != k]
        x, y = P[:, a], P[:, b]
        A = np.c_[2 * x, 2 * y, np.ones(len(x))]
        sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
        cx, cy = sol[0], sol[1]
        rr = float(np.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0)))
        res = np.abs(np.hypot(x - cx, y - cy) - rr)
        if float(res.max()) > max(2 * self.tol, 1e-3) or rr <= 0:
            return None
        out = np.array(c3, dtype=float)
        out[a], out[b] = cx, cy
        return out, rr


def _fmt(x):
    from ..program import _fmt as f
    return f(x)


def source(plan: cq.Solid, V, tol: float, name: str = "part") -> tuple[str, dict]:
    """The recipe text for a plan, placed and snapped on the mesh (V). Returns (text, info)."""
    from ..program import Pool
    s, t = placement(plan, V)
    sn = Snapper(V, tol)
    pool = Pool(tol)
    exts = plan.extrusions()
    info = {"scale": s, "extrusions": len(exts), "snapped": 0, "refitted_circles": 0}
    eid = {id(e): f"e{i + 1}" for i, e in enumerate(exts)}
    handles = {}
    for e in exts:
        fid = eid[id(e)]
        n = e.plane.n
        u = e.plane.x
        w = e.plane.y
        o = s * e.plane.origin + t                       # the plane's origin on the mesh
        lv0 = float(o @ n) + s * e.d0                    # levels: signed distance along n from the world origin
        lv1 = float(o @ n) + s * e.d1
        k = int(np.argmax(np.abs(n)))
        sg = float(np.sign(n[k]))
        z0, z1 = sg * sn.axis(sg * lv0, k), sg * sn.axis(sg * lv1, k)
        info["snapped"] += int(abs(z0 - lv0) > 1e-9) + int(abs(z1 - lv1) > 1e-9)
        if z1 - z0 < tol:
            z0, z1 = lv0, lv1
        ku, kw = int(np.argmax(np.abs(u))), int(np.argmax(np.abs(w)))
        su, sw = float(np.sign(u[ku])), float(np.sign(w[kw]))
        ou, ow = float(o @ u), float(o @ w)

        def snap_u(x):
            return su * sn.axis(su * x, ku)

        def snap_w(y):
            return sw * sn.axis(sw * y, kw)
        items = []
        for it in e.items:
            if it.kind == "rect":
                cx, cy, W, H = ou + s * it.c[0], ow + s * it.c[1], s * it.w, s * it.h
                x0, x1 = snap_u(cx - W / 2), snap_u(cx + W / 2)
                y0, y1 = snap_w(cy - H / 2), snap_w(cy + H / 2)
                if x1 - x0 > tol and y1 - y0 > tol:
                    cx, cy, W, H = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
                    info["snapped"] += 1
                items.append(("rect", it.mode, (pool.add("U", cx, fid), pool.add("W", cy, fid),
                                                pool.add("L", W, fid), pool.add("L", H, fid))))
            elif it.kind == "circle":
                cx, cy, R = ou + s * it.c[0], ow + s * it.c[1], s * it.r
                c3 = cx * u + cy * w
                got = sn.circle(c3, n, R, min(z0, z1), max(z0, z1))
                if got is not None:
                    c3, R = got
                    cx, cy = float(c3 @ u), float(c3 @ w)
                    info["refitted_circles"] += 1
                items.append(("circle", it.mode, (pool.add("U", cx, fid), pool.add("W", cy, fid),
                                                  pool.add("d", 2 * R, fid))))
            else:
                pts = [(snap_u(ou + s * p[0]), snap_w(ow + s * p[1])) for sg_ in it.segs for p in sg_[1:]]
                if not pts:
                    continue
                k_ = 0
                segs = []
                start = (pool.add("U", pts[0][0], fid), pool.add("W", pts[0][1], fid))
                for sg_ in it.segs:
                    if sg_[0] == "line":
                        p1 = pts[k_ + 1]
                        segs.append(("line", (pool.add("U", p1[0], fid), pool.add("W", p1[1], fid))))
                        k_ += 2
                    else:
                        pm, p1 = pts[k_ + 1], pts[k_ + 2]
                        segs.append(("arc", (pool.add("U", pm[0], fid), pool.add("W", pm[1], fid)),
                                     (pool.add("U", p1[0], fid), pool.add("W", p1[1], fid))))
                        k_ += 3
                items.append(("path", it.mode, (start, segs)))
        handles[fid] = (u, n, pool.add("H", min(z0, z1), fid), pool.add("H", max(z0, z1), fid), items)
    labels = {f: f"Extrusion {f[1:]}" for f in handles}
    pool.solve(lambda f: labels.get(f, f))
    c = pool.code
    L = []
    for fid, (u, n, h0, h1, items) in handles.items():
        L.append(f"# {labels[fid]}")
        L.append(f"pl = Plane(origin=(0, 0, 0), x_dir=({_fmt(u[0])}, {_fmt(u[1])}, {_fmt(u[2])}), "
                 f"z_dir=({_fmt(n[0])}, {_fmt(n[1])}, {_fmt(n[2])}))")
        L.append(f"at = pl.offset({c(h0)})")
        expr = None
        for kind, mode, h in items:
            if kind == "rect":
                f_ = f"rect(at, {c(h[0])}, {c(h[1])}, {c(h[2])}, {c(h[3])})"
            elif kind == "circle":
                f_ = f"disc(at, {c(h[0])}, {c(h[1])}, {c(h[2])})"
            else:
                st, segs = h
                parts = [f"('line', ({c(sg_[1][0])}, {c(sg_[1][1])}))" if sg_[0] == "line" else
                         f"('arc', ({c(sg_[1][0])}, {c(sg_[1][1])}), ({c(sg_[2][0])}, {c(sg_[2][1])}))" for sg_ in segs]
                f_ = f"outline(at, ({c(st[0])}, {c(st[1])}), [{', '.join(parts)}])"
            expr = f_ if expr is None else f"({expr}) {'+' if mode == 'a' else '-'} {f_}"
        if expr is None:
            raise cq.Unsupported("an extrusion with nothing to extrude")
        L.append(f"{fid} = slab({expr}, {c(h0)}, {c(h1)})")
    body = []

    def walk(node):
        if node[0] == "extrude":
            return eid[id(node[1])]
        a, b = walk(node[1].node), walk(node[2].node)
        body.append((a, b, node[0]))
        return f"({a} {'+' if node[0] == 'union' else '-'} {b})"
    expr = walk(plan.node)
    L.append(f"body = {expr}")
    L.append("stages.append(Stage('body', body))")
    params = [f"        Param({p['key']!r}, {p['label']!r}, {_fmt(p['value'])}, {_fmt(p['lo'])}, {_fmt(p['hi'])}, 0.01, "
              f"'mm', 'form', 'body', {p['note']!r}, provenance='mesh'),"
              for p in pool.params]
    doc = (f"{name}: reconstructed from a mesh by Form Studio with the optional learned engine (CAD-Recode, "
           f"non-commercial licence), {len(exts)} sketch extrusions placed and snapped on the mesh; every level, side "
           "and diameter is a Param.")
    text = "\n".join([
        '"""' + doc + '\n"""',
        "from build123d import Plane",
        "",
        "from form.recipes.base import Feature, Param, Recipe, Stage",
        "from form.recon.ops import disc, outline, rect, slab",
        "",
        "",
        "class Design(Recipe):",
        f"    title = {(name + ' (reconstructed)')!r}",
        "    summary = 'Rebuilt from a mesh with the learned engine; sketches extruded between levels, snapped to the mesh.'",
        "    params = [",
        *params,
        "    ]",
        "    features = [",
        "        Feature('body', 'Body', 'structure', 'Sketch extrusions read by the learned engine, snapped to the mesh.'),",
        "    ]",
        "",
        "    def build(self, v):",
        "        stages = []",
        *["        " + x for x in L],
        "        return stages",
    ]) + "\n"
    info["params"] = len(pool.params)
    info["_pool"] = pool
    return text, info
