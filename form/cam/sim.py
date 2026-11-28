"""Stock simulation for 3-axis milling: the tool's real shape swept along the motion, and what that leaves.

The stock is a height field (one dexel per cell, along the tool axis): the top of the remaining material over every
cell centre of a grid whose cell size is stated with the result. A move lowers it to the underside of the tool
swept along the move:

* a level move (and a plunge) is exact at every cell centre: the swept underside of a tool of revolution moving
  level is its profile at the cell's distance from the path;
* a move that changes height while it travels (a ramp, a helix, a 3D pass) is sampled every half cell along its
  length, so the cut there is at most (slope × a quarter cell) too shallow.

What is measured, and how:

* **Gouge.** For every sample point on the part's surface (the part's tessellation, split to the sample spacing),
  the deepest it ever lies inside the cutter: the distance from the point to the tool's surface, exact for the
  tool's outline, taken at the closest approach of every cutting move. A gouge is a sample deeper than the
  tolerance. This does not depend on the grid. An edge break the plan declares (a chamfer on a sharp edge) is
  reported on its own and is not a gouge.
* **Leftover.** Where the stock still stands above the part: stock height minus part height at every cell centre
  inside the part's outline, its volume, and where it is (connected regions with their size). Material narrower
  than a cell beside a wall is not seen: the cell size is the resolution.
* **Collisions.** A rapid move whose tool (cutter, shank or holder) dips into the stock as it stands at that
  moment; a cutting move whose shank (above the flute length) or holder would have to pass through stock.
* **Removed volume** per operation, and the air a cutting move travels through.

Everything here is computed from the motion (form/cam/motion.py); the callers hand it the motion read back from
the posted G-code. It is a simulation: nothing is proven on a machine.
"""
from __future__ import annotations

import math

import numpy as np

from .motion import FEED, RAPID

VERSION = 1
EPS = 1e-6


class Stock:
    """Remaining material as heights over a grid. Cell (i, j) has its centre at lo + (i + ½, j + ½) × cell."""

    def __init__(self, lo, cell: float, shape, top, bottom: float):
        self.lo = np.asarray(lo, float)
        self.c = float(cell)
        self.nx, self.ny = int(shape[0]), int(shape[1])
        self.bottom = float(bottom)
        self.Z = np.full((self.nx, self.ny), float(top)) if np.isscalar(top) else np.array(top, float)
        self.zmax = float(self.Z.max()) if self.Z.size else float(bottom)   # the stock only ever gets lower
        self.xc = self.lo[0] + (np.arange(self.nx) + 0.5) * self.c
        self.yc = self.lo[1] + (np.arange(self.ny) + 0.5) * self.c

    def copy(self) -> "Stock":
        s = Stock(self.lo, self.c, (self.nx, self.ny), self.Z, self.bottom)
        return s

    def window(self, x0, x1, y0, y1):
        i0 = max(0, int(math.floor((x0 - self.lo[0]) / self.c)))
        i1 = min(self.nx, int(math.floor((x1 - self.lo[0]) / self.c)) + 1)
        j0 = max(0, int(math.floor((y0 - self.lo[1]) / self.c)))
        j1 = min(self.ny, int(math.floor((y1 - self.lo[1]) / self.c)) + 1)
        return i0, i1, j0, j1

    def sweep(self, tool, a, b, cut: bool = True, check: str = "noncut"):
        """Move the tool from a to b. cut: lower the stock under the cutter. check: "noncut" tests the shank and
        holder against the stock as it was before this move, "all" tests the whole tool (a rapid).
        Returns (removed volume mm³, collision depth mm, where [x, y, z, distance from the axis] or None)."""
        zlow = min(a[2], b[2])
        if check == "noncut" and zlow + tool.flute_l >= self.zmax - EPS:
            check = ""                                 # nothing stands as high as the top of the flutes
        if check and zlow + tool.length >= self.zmax - EPS:
            R = tool.shank_r                           # nothing stands as high as the holder
        else:
            R = tool.holder_r if check else tool.r
        i0, i1, j0, j1 = self.window(min(a[0], b[0]) - R, max(a[0], b[0]) + R, min(a[1], b[1]) - R, max(a[1], b[1]) + R)
        if i0 >= i1 or j0 >= j1:
            return 0.0, 0.0, None
        X = self.xc[i0:i1][:, None]
        Y = self.yc[j0:j1][None, :]
        Zb = self.Z[i0:i1, j0:j1]
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        Lxy = math.hypot(dx, dy)
        depth, where = 0.0, None
        new = None
        if abs(dz) < 1e-9 or Lxy < 1e-9:
            if Lxy < 1e-9:
                D = np.hypot(X - a[0], Y - a[1])
            else:
                t = np.clip(((X - a[0]) * dx + (Y - a[1]) * dy) / (Lxy * Lxy), 0.0, 1.0)
                D = np.hypot(X - (a[0] + t * dx), Y - (a[1] + t * dy))
            z = min(a[2], b[2])
            if check:
                env = tool.envelope(D) if check == "all" else tool.noncut(D)
                over = Zb - (z + env)
                m = float(over.max())
                if m > EPS:
                    k = np.unravel_index(int(np.argmax(over)), over.shape)
                    depth, where = m, [float(self.xc[i0 + k[0]]), float(self.yc[j0 + k[1]]), float(Zb[k]), float(D[k])]
            if cut:
                new = z + tool.profile(D)
        else:
            n = max(1, int(math.ceil(Lxy / (self.c / 2))))
            ts = np.arange(n + 1) / n
            per = max(1, int(2_000_000 // max(1, Zb.size)))
            new = np.full(Zb.shape, np.inf) if cut else None
            for k0 in range(0, n + 1, per):
                tt = ts[k0:k0 + per][:, None, None]
                D = np.hypot(X[None] - (a[0] + tt * dx), Y[None] - (a[1] + tt * dy))
                pz = a[2] + tt * dz
                if check:
                    env = tool.envelope(D) if check == "all" else tool.noncut(D)
                    over = Zb[None] - (pz + env)
                    m = float(over.max())
                    if m > max(depth, EPS):
                        k = np.unravel_index(int(np.argmax(over)), over.shape)
                        depth, where = m, [float(self.xc[i0 + k[1]]), float(self.yc[j0 + k[2]]), float(Zb[k[1], k[2]]), float(D[k])]
                if cut:
                    np.minimum(new, (pz + tool.profile(D)).min(axis=0), out=new)
        removed = 0.0
        if cut and new is not None:
            low = new < Zb
            if low.any():
                # material is what stands above the stock's underside; a cut below it is into the table
                removed = float((np.maximum(Zb, self.bottom) - np.maximum(new, self.bottom))[low].sum()) * self.c * self.c
                self.Z[i0:i1, j0:j1] = np.where(low, new, Zb)
        return removed, depth, where


def open_holes(stock: Stock, holes: list | None) -> None:
    """Start with these round holes already through the stock: [{"at": [x, y], "d": diameter}]."""
    for h in holes or []:
        r = float(h["d"]) / 2
        i0, i1, j0, j1 = stock.window(h["at"][0] - r, h["at"][0] + r, h["at"][1] - r, h["at"][1] + r)
        if i0 >= i1 or j0 >= j1:
            continue
        D = np.hypot(stock.xc[i0:i1][:, None] - h["at"][0], stock.yc[j0:j1][None, :] - h["at"][1])
        Z = stock.Z[i0:i1, j0:j1]
        stock.Z[i0:i1, j0:j1] = np.where(D < r - 1e-9, np.minimum(Z, stock.bottom), Z)


def target_heights(tris, lo, cell: float, shape) -> np.ndarray:
    """The part's top surface over every cell centre (−inf where there is no part), exact for the triangles:
    a ray down the tool axis through each cell centre (form/dfm/geom.py's projected rays)."""
    from ..dfm import geom

    class _S:
        pass
    s = _S()
    s.tri = tris
    pr = geom.Projection(s, (0.0, 0.0, 1.0), cells=200)
    nx, ny = shape
    gx, gy = np.meshgrid(lo[0] + (np.arange(nx) + 0.5) * cell, lo[1] + (np.arange(ny) + 0.5) * cell, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), np.zeros(nx * ny)], axis=1)
    q2 = np.stack([pts @ pr.u, pts @ pr.w], axis=1)
    H = np.full(len(q2), -np.inf)
    for i0 in range(0, len(q2), 60000):
        q = q2[i0:i0 + 60000]
        rid, tri = pr._cands(q)
        if not len(rid):
            continue
        z = pr._hits(q, rid, tri)
        ok = ~np.isnan(z)
        np.maximum.at(H, i0 + rid[ok], z[ok])
    return H.reshape(nx, ny)


def fill_outline(mask: np.ndarray) -> np.ndarray:
    """The mask with its holes filled: everything not connected to the outside of the grid."""
    from scipy import ndimage
    return ndimage.binary_fill_holes(mask)


def surface_samples(tris, spacing: float, max_samples: int = 80000):
    """Sample points on the part's surface: the triangles split until no edge is longer than the spacing; each
    sample is a small triangle's centroid, with its normal and the area it stands for."""
    from ..analysis import refine
    a, b, c = tris
    P = np.concatenate([a, b, c])
    n = len(a)
    T = np.stack([np.arange(n), np.arange(n) + n, np.arange(n) + 2 * n], axis=1)
    area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)
    h = max(spacing, math.sqrt(area / max_samples) * 2.0)
    P2, T2, _ = refine(P, T, h)
    p0, p1, p2 = P2[T2[:, 0]], P2[T2[:, 1]], P2[T2[:, 2]]
    nn = np.cross(p1 - p0, p2 - p0)
    aa = np.linalg.norm(nn, axis=1)
    keep = aa > 1e-14
    return ((p0 + p1 + p2) / 3)[keep], nn[keep] / aa[keep, None], aa[keep] / 2, h


class _Bins:
    def __init__(self, P, size: float):
        self.lo = P[:, :2].min(axis=0) - 1e-6
        self.g = float(size)
        ij = np.floor((P[:, :2] - self.lo) / self.g).astype(np.int64)
        self.nx, self.ny = (int(v) + 1 for v in ij.max(axis=0))
        key = ij[:, 0] * self.ny + ij[:, 1]
        self.order = np.argsort(key, kind="stable")
        ks = key[self.order]
        cells = np.arange(self.nx * self.ny)
        self.start = np.searchsorted(ks, cells)
        self.stop = np.searchsorted(ks, cells, side="right")

    def near(self, x0, x1, y0, y1) -> np.ndarray:
        i0 = max(0, int(math.floor((x0 - self.lo[0]) / self.g)))
        i1 = min(self.nx - 1, int(math.floor((x1 - self.lo[0]) / self.g)))
        j0 = max(0, int(math.floor((y0 - self.lo[1]) / self.g)))
        j1 = min(self.ny - 1, int(math.floor((y1 - self.lo[1]) / self.g)))
        if i0 > i1 or j0 > j1:
            return np.zeros(0, np.int64)
        parts = [self.order[self.start[i * self.ny + j0]:self.stop[i * self.ny + j1]] for i in range(i0, i1 + 1)]
        return parts[0] if len(parts) == 1 else np.concatenate(parts)


def penetration(P, segs: dict, tools: dict, step: float = 0.1):
    """For every surface sample, the deepest it lies inside a cutter during a cutting move: (depth mm per sample,
    the operation that did it per sample or −1)."""
    pen = np.zeros(len(P))
    who = np.full(len(P), -1, np.int32)
    if not len(P) or not len(segs["a"]):
        return pen, who
    rmax = max((t.r for t in tools.values()), default=1.0)
    bins = _Bins(P, max(2 * rmax, 1.0))
    A, B = segs["a"], segs["b"]
    for i in np.nonzero(segs["kind"] == FEED)[0]:
        tool = tools.get(int(segs["tool"][i]))
        if tool is None:
            continue
        a, b = A[i], B[i]
        R = tool.r
        idx = bins.near(min(a[0], b[0]) - R, max(a[0], b[0]) + R, min(a[1], b[1]) - R, max(a[1], b[1]) + R)
        if not len(idx):
            continue
        q = P[idx]
        zmin = min(a[2], b[2])
        idx = idx[q[:, 2] > zmin + 1e-9]              # a point under the tip is never inside
        if not len(idx):
            continue
        q = P[idx]
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        Lxy = math.hypot(dx, dy)
        if abs(dz) < 1e-9 or Lxy < 1e-9:
            if Lxy < 1e-9:
                D = np.hypot(q[:, 0] - a[0], q[:, 1] - a[1])
            else:
                t = np.clip(((q[:, 0] - a[0]) * dx + (q[:, 1] - a[1]) * dy) / (Lxy * Lxy), 0.0, 1.0)
                D = np.hypot(q[:, 0] - (a[0] + t * dx), q[:, 1] - (a[1] + t * dy))
            m = D < R - 1e-9
            if not m.any():
                continue
            d = tool.inside(D[m], q[m, 2] - zmin)
            sub = idx[m]
        else:
            n = max(1, int(math.ceil(math.sqrt(Lxy * Lxy + dz * dz) / step)))
            tt = (np.arange(n + 1) / n)[:, None]
            D = np.hypot(q[None, :, 0] - (a[0] + tt * dx), q[None, :, 1] - (a[1] + tt * dy))
            Hh = q[None, :, 2] - (a[2] + tt * dz)
            m = (D < R - 1e-9) & (Hh > 1e-9)
            if not m.any():
                continue
            col = m.any(axis=0)
            d = tool.inside(D[:, col], Hh[:, col]).max(axis=0)
            sub = idx[col]
        better = d > pen[sub]
        if better.any():
            pen[sub[better]] = d[better]
            who[sub[better]] = int(segs["op"][i])
    return pen, who


def _regions(mask, values, lo, cell, Z, limit: int = 20) -> list:
    from scipy import ndimage
    lab, n = ndimage.label(mask)
    if not n:
        return []
    idx = np.arange(1, n + 1)
    vol = ndimage.sum(values, lab, idx) * cell * cell
    area = ndimage.sum(mask, lab, idx) * cell * cell
    mx = ndimage.maximum(values, lab, idx)
    pos = ndimage.maximum_position(values, lab, idx)
    out = []
    for k in np.argsort(-vol)[:limit]:
        i, j = pos[k]
        out.append({"at": [round(float(lo[0] + (i + 0.5) * cell), 3), round(float(lo[1] + (j + 0.5) * cell), 3),
                           round(float(Z[i, j]), 3)],
                    "max_mm": round(float(mx[k]), 4), "volume_mm3": round(float(vol[k]), 3), "area_mm2": round(float(area[k]), 3)})
    return out


def simulate(segs: dict, tools: dict, stock: Stock, target: np.ndarray, samples=None, tol: float = 0.05,
             leftover_tol: float | None = None, intended: list | None = None, ops: list | None = None,
             through: float = 1.0) -> dict:
    """Run the motion on the stock and measure the result against the part.

    segs: motion.flatten(...). tools: {T number: Tool}. stock: the blank (changed in place). target: the part's
    heights on the stock's grid (−inf outside the part). samples: (points, normals, areas) on the part's surface
    for the gouge measurement. intended: declared edge breaks [{"line": (n, 2) XY, "z": top, "w": width,
    "depth": allowed}]. Returns the measurements; every one of them is simulated."""
    leftover_tol = tol if leftover_tol is None else leftover_tol
    start_vol = float(np.maximum(stock.Z - stock.bottom, 0).sum()) * stock.c ** 2
    nseg = len(segs["a"])
    removed = np.zeros(nseg)
    collisions: list = []
    rapid_hits = 0
    A, B = segs["a"], segs["b"]
    missing = set()
    for i in range(nseg):
        tool = tools.get(int(segs["tool"][i]))
        if tool is None:
            missing.add(int(segs["tool"][i]))
            continue
        if segs["kind"][i] == RAPID:
            _, depth, where = stock.sweep(tool, A[i], B[i], cut=False, check="all")
            if depth > 1e-4:
                rapid_hits += 1
                if len(collisions) < 200:
                    collisions.append({"kind": "rapid", "depth_mm": round(depth, 4), "at": [round(v, 3) for v in where[:3]],
                                       "op": int(segs["op"][i]), "segment": i, "tool": tool.id})
        else:
            removed[i], depth, where = stock.sweep(tool, A[i], B[i], cut=True, check="noncut")
            if depth > 1e-4 and len(collisions) < 200:
                collisions.append({"kind": "holder" if where[3] > tool.shank_r + 1e-9 else "shank",
                                   "depth_mm": round(depth, 4), "at": [round(v, 3) for v in where[:3]],
                                   "op": int(segs["op"][i]), "segment": i, "tool": tool.id})
    Z = stock.Z
    inside = np.isfinite(target)
    domain = fill_outline(inside)
    T = np.where(inside, target, stock.bottom)
    # leftover: stock above the part, inside the part's outline
    left = np.where(domain, np.maximum(Z - np.maximum(T, stock.bottom), 0.0), 0.0)
    lmask = left > leftover_tol
    # cut below the part's surface, seen along the tool axis (the exact measure is the samples' penetration)
    over = np.where(inside, np.maximum(T - Z, 0.0), 0.0)
    omask = over > tol
    below = float(max(0.0, stock.bottom - float(Z.min())))
    out = {"version": VERSION, "evidence": "simulated", "cell_mm": stock.c, "grid": [stock.nx, stock.ny],
           "tolerance_mm": tol, "leftover_tolerance_mm": leftover_tol,
           "segments": int(nseg), "stock_volume_mm3": round(start_vol, 2),
           "removed_mm3": round(float(removed.sum()), 2),
           "leftover": {"volume_mm3": round(float(left.sum()) * stock.c ** 2, 3),
                        "above_tolerance_mm3": round(float(left[lmask].sum()) * stock.c ** 2, 3),
                        "max_mm": round(float(left.max()) if left.size else 0.0, 4),
                        "area_mm2": round(float(lmask.sum()) * stock.c ** 2, 3),
                        "regions": _regions(lmask, left, stock.lo, stock.c, Z),
                        "method": f"stock height minus part height at every cell centre ({stock.c:g} mm cells) inside "
                                  "the part's outline; material narrower than a cell beside a wall is not seen"},
           "overcut_map": {"max_mm": round(float(over.max()) if over.size else 0.0, 4),
                           "volume_mm3": round(float(over.sum()) * stock.c ** 2, 3),
                           "regions": _regions(omask, over, stock.lo, stock.c, Z, 10),
                           "method": "part height minus stock height at every cell centre, along the tool axis: where "
                                     "the gouge is, not how deep (a sliver off a wall reads as the wall's height here)"},
           "below_stock_mm": round(below, 4),
           "collisions": collisions, "rapid_collisions": rapid_hits,
           "holder_collisions": sum(1 for c in collisions if c["kind"] in ("holder", "shank")),
           "air_mm": round(float(np.linalg.norm(B - A, axis=1)[(segs["kind"] == FEED) & (removed <= 1e-9)].sum()), 2) if nseg else 0.0}
    if missing:
        out["unknown_tools"] = sorted(missing)
    per = {}
    for o in np.unique(segs["op"]) if nseg else []:
        m = segs["op"] == o
        per[int(o)] = {"removed_mm3": round(float(removed[m].sum()), 2),
                       "feed_mm": round(float(np.linalg.norm(B - A, axis=1)[m & (segs["kind"] == FEED)].sum()), 2)}
    out["per_op"] = per
    # gouge: exact, on the surface samples
    if samples is not None and len(samples[0]):
        P, _N, Aa = samples[0], samples[1], samples[2]
        pen, who = penetration(P, segs, tools)
        tol_s = np.full(len(P), tol)
        brk = np.zeros(len(P), bool)
        for it in intended or []:
            line = np.asarray(it["line"], float).reshape(-1, 2)
            if len(line) < 2:
                continue
            near = _near_polyline(P[:, :2], line, float(it["w"]) + 2 * tol)
            band = near & (P[:, 2] <= it["z"] + tol) & (P[:, 2] >= it["z"] - float(it.get("h", it["w"])) - 2 * tol)
            tol_s = np.where(band, np.maximum(tol_s, float(it["depth"]) + tol), tol_s)
            brk |= band
        g = pen > tol_s
        marks = []
        for k in np.argsort(-np.where(g, pen, 0))[:20]:
            if not g[k]:
                break
            if all(np.linalg.norm(P[k] - np.array(mk["at"])) > 2.0 for mk in marks):
                marks.append({"at": [round(float(v), 3) for v in P[k]], "depth_mm": round(float(pen[k]), 4), "op": int(who[k])})
        out["gouge"] = {"max_mm": round(float(pen[~brk].max()) if (~brk).any() else 0.0, 4),
                        "samples": int(len(P)), "gouged_samples": int(g.sum()),
                        "area_mm2": round(float(Aa[g].sum()), 3), "marks": marks,
                        "by_op": {int(o): round(float(pen[g & (who == o)].max()), 4) for o in np.unique(who[g])},
                        "method": "distance from each surface sample to the cutter's surface where the sample lies "
                                  "inside the cutter, at the closest approach of every cutting move (exact for a level "
                                  "move and a plunge; sampled every 0.1 mm on a move that changes height)"}
        if brk.any():
            out["edge_break"] = {"max_mm": round(float(pen[brk].max()), 4), "samples": int((pen[brk] > tol).sum()),
                                 "declared": len(intended or []),
                                 "note": "cut on purpose by a chamfer the plan declares; not counted as gouge"}
        out["_pen"] = pen
    else:
        out["gouge"] = {"max_mm": None, "samples": 0, "method": "not measured: no surface samples"}
    gouged = bool(out["gouge"].get("gouged_samples"))
    fails = []
    if gouged:
        fails.append(f"gouge {out['gouge']['max_mm']:g} mm (tolerance {tol:g})")
    if rapid_hits:
        fails.append(f"{rapid_hits} rapid move(s) through stock")
    if out["holder_collisions"]:
        fails.append(f"{out['holder_collisions']} move(s) where the shank or holder meets stock")
    if below > through + 1e-6:
        fails.append(f"cuts {below:g} mm below the stock's underside (allowed {through:g})")
    if missing:
        fails.append("moves with a tool the plan does not have: T" + ", T".join(str(t) for t in sorted(missing)))
    out["verdict"] = "fail" if fails else "pass"
    out["fails"] = fails
    out["left"] = bool(lmask.any())
    out["_left"], out["_over"], out["_domain"] = left, over, domain
    return out


def _near_polyline(P2, line, dist: float) -> np.ndarray:
    lo, hi = line.min(axis=0) - dist, line.max(axis=0) + dist
    cand = np.nonzero((P2[:, 0] >= lo[0]) & (P2[:, 0] <= hi[0]) & (P2[:, 1] >= lo[1]) & (P2[:, 1] <= hi[1]))[0]
    out = np.zeros(len(P2), bool)
    if not len(cand):
        return out
    a, b = line[:-1], line[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(axis=1), 1e-30)
    best = np.full(len(cand), np.inf)
    for k0 in range(0, len(a), 256):
        aa, bb, ll = a[k0:k0 + 256], ab[k0:k0 + 256], L2[k0:k0 + 256]
        q = P2[cand][:, None, :]
        t = np.clip(((q - aa) * bb).sum(axis=2) / ll, 0.0, 1.0)
        d = np.linalg.norm(q - (aa + t[..., None] * bb), axis=2).min(axis=1)
        best = np.minimum(best, d)
    out[cand[best <= dist]] = True
    return out
