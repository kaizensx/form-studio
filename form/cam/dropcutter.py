"""Drop-cutter on the part's tessellation: how low a tool can come at (x, y) before it touches the part.

Our own code (no opencamlib needed; see docs/CAM.md for why and for its licence). For a tool of revolution whose
underside is `profile(r)` (convex, level or rising outward), the lowest tip height over a triangle is the largest
value of  z(q) − profile(|q − c|)  over the points q of the triangle within the tool's radius of the tool axis c.
That function is concave on the triangle, so its maximum is one of:

* **in the facet**: where the tool's slope equals the plane's, at the radius `tool.contact_r(slope)` uphill of the
  axis (exact, closed form);
* **on an edge**: the maximum of a concave function of one variable along the part of the edge inside the tool's
  radius: at an end of that part for a flat tool (the height is linear there), the root of a quadratic for a ball,
  and a golden-section search to 2e-7 of the edge's length for a bull nose, a drill and a chamfer mill;
* **at a vertex**.

Exact for the tessellation, for flat, ball, bull-nose, drill and chamfer tools alike. The tessellation itself is
within its own tolerance of the B-rep (stated by the caller).

`field` gives the tip height over a grid; `waterline` the boundary of where the tool can stand at a given height,
by marching squares on that grid with every crossing then moved along its grid edge to the exact place the tool
starts to touch (bisection on `drop`, to 1/4096 of a cell). Between two crossings the path is a chord: on a curved
wall of radius ρ it is off by at most cell² / (8ρ), and a sharp inside corner is cut short by under a cell (the
simulation measures what that leaves).
"""
from __future__ import annotations

import math

import numpy as np

GOLD = (math.sqrt(5) - 1) / 2


class Mesh:
    """Triangles binned on an XY grid for drop-cutter queries."""

    def __init__(self, tris):
        a, b, c = (np.asarray(x, float) for x in tris)
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n, axis=1)
        ok = ln > 1e-14
        self.a, self.b, self.c = a[ok], b[ok], c[ok]
        n = n[ok] / ln[ok, None]
        self.n = np.where(n[:, 2:3] < 0, -n, n)                  # upward normals
        P = np.concatenate([self.a, self.b, self.c])
        self.lo, self.hi = P.min(axis=0), P.max(axis=0)
        self._bins: dict = {}
        # unique edges (as point pairs) so that an edge shared by two triangles is tested once
        E = np.concatenate([np.stack([self.a, self.b], 1), np.stack([self.b, self.c], 1), np.stack([self.c, self.a], 1)])
        key = np.round(E.reshape(len(E), 6) * 1e6).astype(np.int64)
        swap = (key[:, 0] > key[:, 3]) | ((key[:, 0] == key[:, 3]) & ((key[:, 1] > key[:, 4]) |
                                                                      ((key[:, 1] == key[:, 4]) & (key[:, 2] > key[:, 5]))))
        key[swap] = key[swap][:, [3, 4, 5, 0, 1, 2]]
        kv = np.ascontiguousarray(key).view([("", np.int64)] * 6).ravel()
        _, first = np.unique(kv, return_index=True)
        self.e0, self.e1 = E[first, 0], E[first, 1]
        vk = np.ascontiguousarray(np.round(P * 1e6).astype(np.int64)).view([("", np.int64)] * 3).ravel()
        _, vfirst = np.unique(vk, return_index=True)
        self.v = P[vfirst]                                         # unique vertices

    def _index(self, lo2, hi2, pad: float, g: float, nx: int, ny: int):
        """CSR of the items (boxes lo2..hi2 in XY) overlapping each grid cell grown by pad."""
        i0 = np.clip(np.floor((lo2 - pad - self.lo[:2]) / g).astype(np.int64), 0, [nx - 1, ny - 1])
        i1 = np.clip(np.floor((hi2 + pad - self.lo[:2]) / g).astype(np.int64), 0, [nx - 1, ny - 1])
        span = i1 - i0 + 1
        cnt = span[:, 0] * span[:, 1]
        tid = np.repeat(np.arange(len(cnt)), cnt)
        k = np.arange(len(tid)) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        sx = span[tid, 0]
        cell = (i0[tid, 0] + k % sx) * ny + (i0[tid, 1] + k // sx)
        order = np.argsort(cell, kind="stable")
        cell = cell[order]
        cells = np.arange(nx * ny)
        return tid[order], np.searchsorted(cell, cells), np.searchsorted(cell, cells, side="right")

    def _for(self, R: float):
        key = round(R, 6)
        if key not in self._bins:
            ext = float((self.hi[:2] - self.lo[:2]).max()) or 1.0
            g = max(ext / 128.0, R, 0.25)                # cells no smaller than the tool's radius
            nx, ny = (int(math.floor(v / g)) + 1 for v in (self.hi[:2] - self.lo[:2]))
            tl = np.minimum(np.minimum(self.a, self.b), self.c)[:, :2]
            th = np.maximum(np.maximum(self.a, self.b), self.c)[:, :2]
            el = np.minimum(self.e0, self.e1)[:, :2]
            eh = np.maximum(self.e0, self.e1)[:, :2]
            self._bins[key] = (g, nx, ny, self._index(tl, th, R, g, nx, ny), self._index(el, eh, R, g, nx, ny),
                               self._index(self.v[:, :2], self.v[:, :2], R, g, nx, ny))
        return self._bins[key]

    def _pairs(self, xy, grid, idx):
        g, nx, ny = grid
        items, start, stop = idx
        c = np.floor((xy - self.lo[:2]) / g).astype(np.int64)
        c = np.clip(c, 0, [nx - 1, ny - 1])                     # beyond the grid: the border cell's (padded) items
        cid = c[:, 0] * ny + c[:, 1]
        s, e = start[cid], stop[cid]
        cnt = e - s
        rid = np.repeat(np.arange(len(xy)), cnt)
        k = np.arange(len(rid)) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        return rid, items[np.repeat(s, cnt) + k]

    def drop(self, tool, xy, chunk: int = 2000) -> np.ndarray:
        """Tip height at which the tool, coming down at each (x, y), first touches the part (−inf: it never does)."""
        xy = np.asarray(xy, float).reshape(-1, 2)
        out = np.full(len(xy), -np.inf)
        b = self._for(tool.r)
        for i0 in range(0, len(xy), chunk):
            out[i0:i0 + chunk] = self._drop(tool, xy[i0:i0 + chunk], b)
        return out

    def _drop(self, tool, xy, b):
        R = tool.r
        grid, tri_idx, edge_idx, vert_idx = b[:3], b[3], b[4], b[5]
        best = np.full(len(xy), -np.inf)
        # vertices: cheap, and a floor under everything else
        rid, vi = self._pairs(xy, grid, vert_idx)
        if len(rid):
            v = self.v[vi]
            r = np.hypot(v[:, 0] - xy[rid, 0], v[:, 1] - xy[rid, 1])
            m = r <= R
            np.maximum.at(best, rid[m], v[m, 2] - tool.profile(r[m]))
        # facets
        rid, tri = self._pairs(xy, grid, tri_idx)
        if len(rid):
            n = self.n[tri]
            ok = n[:, 2] > 1e-9
            rid, tri, n = rid[ok], tri[ok], n[ok]
            nh = np.hypot(n[:, 0], n[:, 1])
            slope = nh / n[:, 2]
            rc = tool.contact_r(slope)
            up = np.where(nh[:, None] > 1e-12, -n[:, :2] / np.maximum(nh, 1e-12)[:, None], 0.0)
            q = xy[rid] + rc[:, None] * up
            level = nh <= 1e-12                         # a level facet: the axis point (the edges do the rest)
            q = np.where(level[:, None], xy[rid], q)
            rc = np.where(level, 0.0, rc)
            a, bb, c = self.a[tri], self.b[tri], self.c[tri]
            e1, e2, v = (bb - a)[:, :2], (c - a)[:, :2], q - a[:, :2]
            det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
            good = np.abs(det) > 1e-14
            inv = 1.0 / np.where(good, det, 1.0)
            s = (v[:, 0] * e2[:, 1] - v[:, 1] * e2[:, 0]) * inv
            t = (e1[:, 0] * v[:, 1] - e1[:, 1] * v[:, 0]) * inv
            inside = good & (s >= -1e-12) & (t >= -1e-12) & (s + t <= 1 + 1e-12)
            z = a[:, 2] + s * (bb[:, 2] - a[:, 2]) + t * (c[:, 2] - a[:, 2]) - tool.profile(rc)
            m = inside & np.isfinite(z)
            np.maximum.at(best, rid[m], z[m])
        # edges: only those that could still be higher than what is already found
        rid, ed = self._pairs(xy, grid, edge_idx)
        if len(rid):
            p0, p1 = self.e0[ed], self.e1[ed]
            keep = np.maximum(p0[:, 2], p1[:, 2]) > best[rid]
            rid, p0, p1 = rid[keep], p0[keep], p1[keep]
            c = xy[rid]
            d = (p1 - p0)[:, :2]
            f = p0[:, :2] - c
            A = (d * d).sum(axis=1)
            Bq = 2 * (f * d).sum(axis=1)
            C0 = (f * f).sum(axis=1)
            C = C0 - R * R
            point = A < 1e-18                             # a vertical edge: one point in XY, its ends are vertices
            disc = Bq * Bq - 4 * A * C
            sq = np.sqrt(np.maximum(disc, 0.0))
            A2 = np.where(point, 1.0, 2 * A)
            ta, tb = (-Bq - sq) / A2, (-Bq + sq) / A2
            hit = (~point) & (disc > 0) & (tb > 0) & (ta < 1)        # the part of the edge inside the radius
            # the closest the edge comes to the axis bounds what it can reach
            tm = np.clip(-Bq / A2, 0.0, 1.0)
            dmin = np.sqrt(np.maximum(A * tm * tm + Bq * tm + C0, 0.0))
            ub = np.maximum(p0[:, 2], p1[:, 2]) - tool.profile(np.minimum(dmin, R))
            hit &= ub > best[rid]
            rid, p0, p1, c = rid[hit], p0[hit], p1[hit], c[hit]
            t0, t1 = np.clip(ta[hit], 0.0, 1.0), np.clip(tb[hit], 0.0, 1.0)
            A, Bq, C0 = A[hit], Bq[hit], C0[hit]
            if len(rid):
                dd = p1 - p0

                def val(t):
                    r = np.sqrt(np.maximum(A * t * t + Bq * t + C0, 0.0))
                    return p0[:, 2] + t * dd[:, 2] - tool.profile(np.minimum(r, R))
                z = np.maximum(val(t0), val(t1))
                if tool.kind == "flat":
                    pass                                   # level underside: the height along the edge is linear
                elif tool.kind == "ball":
                    # d/dt [t·dz + sqrt(R² − (A t² + B t + C0))] = 0  →  a quadratic in t
                    dz = dd[:, 2]
                    qa = A * A + dz * dz * A
                    qb = A * Bq + dz * dz * Bq
                    qc = Bq * Bq / 4 + dz * dz * (C0 - R * R)
                    dq = np.sqrt(np.maximum(qb * qb - 4 * qa * qc, 0.0))
                    for sgn in (-1.0, 1.0):
                        t = np.clip((-qb + sgn * dq) / np.maximum(2 * qa, 1e-30), t0, t1)
                        z = np.maximum(z, val(t))
                else:
                    lo, hi = t0.copy(), t1.copy()
                    x1 = hi - GOLD * (hi - lo)
                    x2 = lo + GOLD * (hi - lo)
                    f1, f2 = val(x1), val(x2)
                    for _ in range(32):
                        left = f1 > f2
                        hi = np.where(left, x2, hi)
                        lo = np.where(left, lo, x1)
                        nx1 = np.where(left, hi - GOLD * (hi - lo), x2)
                        nx2 = np.where(left, x1, lo + GOLD * (hi - lo))
                        nf1 = np.where(left, val(nx1), f2)
                        nf2 = np.where(left, f1, val(nx2))
                        x1, x2, f1, f2 = nx1, nx2, nf1, nf2
                    z = np.maximum(z, np.maximum(f1, f2))
                np.maximum.at(best, rid, z)
        return best

    def field(self, tool, lo, cell: float, shape) -> np.ndarray:
        """Tip heights at the nodes lo + (i, j) × cell of a grid."""
        gx, gy = np.meshgrid(lo[0] + np.arange(shape[0]) * cell, lo[1] + np.arange(shape[1]) * cell, indexing="ij")
        return self.drop(tool, np.stack([gx.ravel(), gy.ravel()], axis=1)).reshape(shape)


# ---- contours on a grid ------------------------------------------------------------------------------------------

def contours(F: np.ndarray, level: float, lo, cell: float, refine=None, min_len: float = 0.0) -> list:
    """The boundary of {F <= level} on the node grid lo + (i, j) × cell, as polylines (closed ones repeat their
    first point) with the region F <= level on the left. refine(inside_pts, outside_pts) -> points moves each
    crossing along its grid edge to where the true field crosses the level."""
    nx, ny = F.shape
    low = F <= level
    # crossings on x-edges (between (i, j) and (i + 1, j)) and y-edges (between (i, j) and (i, j + 1))
    ex = low[:-1, :] != low[1:, :]
    ey = low[:, :-1] != low[:, 1:]

    def node(i, j):
        return np.stack([lo[0] + i * cell, lo[1] + j * cell], axis=1)

    def cross(i, j, di, dj, crossed):
        ii, jj = np.nonzero(crossed)
        a_in = low[ii, jj]
        p_in = node(np.where(a_in, ii, ii + di), np.where(a_in, jj, jj + dj))
        p_out = node(np.where(a_in, ii + di, ii), np.where(a_in, jj + dj, jj))
        if refine is not None and len(ii):
            pts = refine(p_in, p_out)
        else:
            f0 = F[ii, jj]
            f1 = F[ii + di, jj + dj]
            fin, fout = np.where(a_in, f0, f1), np.where(a_in, f1, f0)
            with np.errstate(invalid="ignore", divide="ignore"):
                t = np.where(np.isfinite(fin) & np.isfinite(fout) & (fout > fin), (level - fin) / (fout - fin), 0.5)
            pts = p_in + np.clip(t, 0.0, 1.0)[:, None] * (p_out - p_in)
        return ii, jj, pts
    xi, xj, xp = cross(None, None, 1, 0, ex)
    yi, yj, yp = cross(None, None, 0, 1, ey)
    xid = {(int(i), int(j)): k for k, (i, j) in enumerate(zip(xi, xj))}
    yid = {(int(i), int(j)): k + len(xi) for k, (i, j) in enumerate(zip(yi, yj))}
    P = np.concatenate([xp, yp]) if len(xp) or len(yp) else np.zeros((0, 2))
    # cells with a crossing: walk each cell's edges; segments run with the low region on the left
    nxt: dict = {}
    cells = set()
    for (i, j) in xid:
        if j < ny - 1:
            cells.add((i, j))
        if j > 0:
            cells.add((i, j - 1))
    for (i, j) in yid:
        if i < nx - 1:
            cells.add((i, j))
        if i > 0:
            cells.add((i - 1, j))
    for (i, j) in cells:
        c00, c10, c11, c01 = low[i, j], low[i + 1, j], low[i + 1, j + 1], low[i, j + 1]
        b, r, t, l = xid.get((i, j)), yid.get((i + 1, j)), xid.get((i, j + 1)), yid.get((i, j))
        # walking the cell's boundary counter-clockwise from the bottom-left node, a segment starts where the
        # walk leaves the low region and ends where it enters it again, so the low region stays on the left
        seq = [(c00, c10, b), (c10, c11, r), (c11, c01, t), (c01, c00, l)]
        outs = [e for (p, q, e) in seq if p and not q and e is not None]     # leaving low
        ins = [e for (p, q, e) in seq if (not p) and q and e is not None]    # entering low
        if len(outs) == 1 and len(ins) == 1:
            nxt[(outs[0], (i, j))] = ins[0]
        elif len(outs) == 2 and len(ins) == 2:
            # a saddle: the two low corners are taken as separate (never joins regions through a corner)
            order = [e for (p, q, e) in seq if p != q and e is not None]
            kinds = ["out" if (p and not q) else "in" for (p, q, e) in seq if p != q and e is not None]
            for k in range(4):
                if kinds[k] == "in":
                    nxt[(order[(k + 1) % 4], (i, j))] = order[k]
    # chain: each crossing is the end of one segment (in one cell) and the start of the next (in the other)
    follow: dict = {}
    for (start, _cell), end in nxt.items():
        follow.setdefault(start, []).append(end)
    used = set()
    lines = []
    starts = set(follow)
    ends = {e for v in follow.values() for e in v}
    order = [s for s in starts if s not in ends] + list(starts)
    for s in order:
        if s in used or s not in follow:
            continue
        chain = [s]
        used.add(s)
        cur = s
        while cur in follow and follow[cur]:
            nx_ = follow[cur].pop()
            chain.append(nx_)
            if nx_ in used:
                break
            used.add(nx_)
            cur = nx_
        if len(chain) >= 2:
            pts = P[chain]
            keep = np.concatenate([[True], np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9])
            pts = pts[keep]
            if len(pts) >= 2 and float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()) >= min_len:
                lines.append(pts)
    return lines


def waterline(mesh: Mesh, tool, z: float, lo, cell: float, shape, F: np.ndarray | None = None, iters: int = 12,
              min_len: float = 0.0) -> list:
    """Where the tool's axis can stand with its tip at height z: the boundary of {drop <= z}, each crossing exact
    to cell / 2^iters along its grid edge. The free side is on the left, so the part is on the right (climb
    milling with a clockwise spindle)."""
    if F is None:
        F = mesh.field(tool, lo, cell, shape)
    z = z + 1e-6                                      # a tool resting on a level face stands at that face's height

    def refine(p_in, p_out):
        a, b = p_in.copy(), p_out.copy()
        for _ in range(iters):
            m = (a + b) / 2
            ok = mesh.drop(tool, m) <= z
            a = np.where(ok[:, None], m, a)
            b = np.where(ok[:, None], b, m)
        return a
    return contours(F, z, lo, cell, refine, min_len)


def closed(line: np.ndarray, tol: float = 1e-6) -> bool:
    return len(line) > 2 and float(np.linalg.norm(line[0] - line[-1])) < tol


def simplify(line: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker: drop points that are within tol of the chord through their neighbours."""
    n = len(line)
    if n < 3 or tol <= 0:
        return line
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = line[i], line[j]
        ab = b - a
        L = float(np.linalg.norm(ab))
        p = line[i + 1:j]
        if L < 1e-12:
            d = np.linalg.norm(p - a, axis=1)
        else:
            t = np.clip(((p - a) @ ab) / (L * L), 0.0, 1.0)
            d = np.linalg.norm(p - (a + t[:, None] * ab), axis=1)
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return line[keep]
