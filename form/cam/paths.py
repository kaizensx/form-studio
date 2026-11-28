"""Toolpaths for 3-axis milling, each written as program events (form/cam/motion.py).

    face        level passes over the top of the stock down to the part's top
    adaptive    clearing at constant engagement: at each level the cutter is steered so that the width of material
                it meets stays at the stepover asked for, entering from open stock or down a helix, never plunging
                into a full slot; a radial and an axial allowance are left for finishing
    finish      2.5D finishing with a flat or bull-nose tool: each level floor in rings, then the walls that stand
                on it along the exact boundary of where the tool can be (a waterline of the drop-cutter)
    contour     the part's outline cut through in depth steps, with holding tabs
    drill       drilling, pecking when the hole is deep; the depth is where the drill's own point meets the part
    bore        a hole wider than the cutter, down a helix and once around at the bottom
    chamfer     edges of level faces broken with a chamfer mill, by a width the plan declares
    raster      3D finishing in parallel passes; every point's height is the drop-cutter's
    waterline   3D finishing at constant heights along the drop-cutter's contours

A `Job` holds the part (triangles and its drop-cutter mesh), the stock as it stands while the plan is built (the
same height field the simulation uses, so every operation sees what the ones before it left), and the grid both
live on. Operations take the job, a tool, their parameters and their speeds and feeds, add their moves, and report
what they did.

What is exact and what is not: the heights of raster points and the place of every finishing contour come from
the drop-cutter on the tessellation (exact for it). Clearing is steered on the grid and keeps its allowance plus
three quarters of a cell away from the part. None of this is the proof: the stock simulation of the posted file is.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from . import dropcutter, motion, sim

VERSION = 1
RAMP_DEG = 3.0            # helix and ramp angle (a rule of thumb; stated in every plan as assumed)
SAFE_GAP = 1.0            # mm above standing stock where a rapid approach ends and the feed begins


def _disc(r_pix: float) -> np.ndarray:
    R = int(math.floor(r_pix))
    y, x = np.mgrid[-R:R + 1, -R:R + 1]
    return (x * x + y * y) <= r_pix * r_pix + 1e-9


def _count(mask: np.ndarray, disc: np.ndarray) -> np.ndarray:
    """How many set cells lie in the disc around every cell."""
    from scipy import signal
    return np.rint(signal.fftconvolve(mask.astype(np.float32), disc.astype(np.float32), mode="same")).astype(np.int32)


class Job:
    def __init__(self, tris, stock_box, cell: float, pad: float, holes: list | None = None, clearance: float = 5.0,
                 cutout: bool = False, through: float = 0.3, precut: list | None = None):
        self.tris = tuple(np.asarray(t, float) for t in tris)
        self.mesh = dropcutter.Mesh(self.tris)
        self.box = [float(v) for v in stock_box]          # x0, x1, y0, y1, z bottom, z top
        x0, x1, y0, y1, zb, zt = self.box
        self.zb, self.zt = zb, zt
        self.c = float(cell)
        self.lo = np.array([x0 - pad, y0 - pad])
        self.nx = int(math.ceil((x1 - x0 + 2 * pad) / self.c))
        self.ny = int(math.ceil((y1 - y0 + 2 * pad) / self.c))
        self.xc = self.lo[0] + (np.arange(self.nx) + 0.5) * self.c
        self.yc = self.lo[1] + (np.arange(self.ny) + 0.5) * self.c
        self.footprint = ((self.xc >= x0 - 1e-9) & (self.xc <= x1 + 1e-9))[:, None] & \
                         ((self.yc >= y0 - 1e-9) & (self.yc <= y1 + 1e-9))[None, :]
        self.T = sim.target_heights(self.tris, self.lo, self.c, (self.nx, self.ny))
        self.inside = np.isfinite(self.T)
        self.domain = sim.fill_outline(self.inside)
        self.Tn = np.where(self.inside, np.maximum(self.T, zb), zb)
        self.stock = sim.Stock(self.lo, self.c, (self.nx, self.ny), np.where(self.footprint, zt, zb), zb)
        sim.open_holes(self.stock, precut)             # holes an earlier setup drilled through
        self.zc = zt + float(clearance)
        self.holes = holes or []
        self.cutout = bool(cutout)
        self.through = float(through)
        self.part_top = float(self.T[self.inside].max()) if self.inside.any() else zt
        self._fields: dict = {}
        self.intended: list = []
        self.notes: list = []

    # ---- grid ---------------------------------------------------------------------------------------------
    def node(self, x, y):
        i = int(min(self.nx - 1, max(0, round((x - self.xc[0]) / self.c))))
        j = int(min(self.ny - 1, max(0, round((y - self.yc[0]) / self.c))))
        return i, j

    def nodes(self, xy):
        ij = np.rint((np.asarray(xy, float) - np.array([self.xc[0], self.yc[0]])) / self.c).astype(np.int64)
        return np.clip(ij[:, 0], 0, self.nx - 1), np.clip(ij[:, 1], 0, self.ny - 1)

    def approx_field(self, tool) -> np.ndarray:
        """The drop-cutter's tip height at every grid node, from the part's heights at the nodes alone: the tool's
        underside lowered onto the height field. Never above the true value; off by up to a cell's worth of slope
        beside a wall, which `level_field` puts right where it matters."""
        from scipy import ndimage
        k = (tool.kind, round(tool.d, 6), round(tool.corner_r, 6), round(tool.angle, 6), round(tool.tip_d, 6))
        if k not in self._fields:
            base = np.where(self.inside, self.T, -1e9)
            fp = _disc(tool.r / self.c)
            Rp = fp.shape[0] // 2
            y, x = np.mgrid[-Rp:Rp + 1, -Rp:Rp + 1]
            prof = tool.profile(np.minimum(np.hypot(x, y) * self.c, tool.r))
            if tool.kind == "flat":
                F = ndimage.maximum_filter(base, footprint=fp, mode="nearest")
            else:
                F = ndimage.grey_dilation(base, footprint=fp, structure=np.where(fp, -prof, 0.0), mode="nearest")
            self._fields[k] = (np.where(F < -1e8, -np.inf, F), np.full(F.shape, np.nan))
        return self._fields[k][0]

    def level_field(self, tool, z: float) -> np.ndarray:
        """The tip-height field with the exact drop-cutter value at every node within two cells of where the tool
        starts to touch at height z (so the boundary found on it is the true one)."""
        from scipy import ndimage
        Fa = self.approx_field(tool)
        k = (tool.kind, round(tool.d, 6), round(tool.corner_r, 6), round(tool.angle, 6), round(tool.tip_d, 6))
        Fx = self._fields[k][1]
        low = Fa <= z + 1e-6
        edge = np.zeros_like(low)
        edge[:-1, :] |= low[:-1, :] != low[1:, :]
        edge[1:, :] |= low[:-1, :] != low[1:, :]
        edge[:, :-1] |= low[:, :-1] != low[:, 1:]
        edge[:, 1:] |= low[:, :-1] != low[:, 1:]
        band = ndimage.binary_dilation(edge, iterations=2)
        need = band & np.isnan(Fx)
        if need.any():
            ii, jj = np.nonzero(need)
            Fx[ii, jj] = self.mesh.drop(tool, np.stack([self.xc[ii], self.yc[jj]], axis=1))
        return np.where(band, Fx, Fa)

    def stock_top(self, x, y, r) -> float:
        i0, i1, j0, j1 = self.stock.window(x - r, x + r, y - r, y + r)
        if i0 >= i1 or j0 >= j1:
            return self.zb
        return float(self.stock.Z[i0:i1, j0:j1].max())

    def floors(self, min_area: float) -> list:
        """Heights of the part's level faces seen from above, highest first (those of at least min_area mm²). A
        cell is level when its four neighbours are at its own height; a dome's rings of nearly equal height are
        not."""
        T = np.where(self.inside, self.T, np.nan)
        lvl = self.inside.copy()
        with np.errstate(invalid="ignore"):
            for ax, sl_a, sl_b in ((0, np.s_[:-1, :], np.s_[1:, :]), (1, np.s_[:, :-1], np.s_[:, 1:])):
                same = np.abs(np.diff(T, axis=ax)) < 1e-4
                near = np.zeros_like(lvl)
                near[sl_a] |= same
                near[sl_b] |= same
                lvl &= near
        v = np.round(self.T[lvl], 3)
        if not len(v):
            return []
        u, n = np.unique(v, return_counts=True)
        return [float(h) for h, k in sorted(zip(u, n), reverse=True) if k * self.c * self.c >= min_area]

    def apply(self, events, tools: dict) -> None:
        """Cut the job's stock with these moves, so the next operation sees what is left."""
        segs = motion.flatten(events)
        A, B = segs["a"], segs["b"]
        for i in np.nonzero(segs["kind"] == motion.FEED)[0]:
            t = tools.get(int(segs["tool"][i]))
            if t is not None:
                self.stock.sweep(t, A[i], B[i], cut=True, check="")


class Pen:
    """Writes moves, keeping track of where the tool is."""

    def __init__(self, job: Job, tool, fs: dict):
        self.job, self.tool, self.fs = job, tool, fs
        self.ev: list = []
        self.pos = None
        self.cut_mm = 0.0

    def up(self):
        if self.pos is not None and self.pos[2] < self.job.zc - 1e-9:
            self.ev.append(("rapid", self.pos[0], self.pos[1], self.job.zc))
            self.pos = (self.pos[0], self.pos[1], self.job.zc)

    def over(self, x, y):
        self.up()
        self.ev.append(("rapid", float(x), float(y), self.job.zc))
        self.pos = (float(x), float(y), self.job.zc)

    def down(self, z, feed=None):
        """Rapid to just above the standing stock, then feed to z."""
        x, y, _ = self.pos
        top = self.job.stock_top(x, y, self.tool.shank_r + self.job.c) + SAFE_GAP
        if top < self.pos[2] - 1e-9 and top > z:
            self.ev.append(("rapid", x, y, top))
        elif top <= z and self.pos[2] > z + 1e-9:
            self.ev.append(("rapid", x, y, z + SAFE_GAP))
        self.ev.append(("feed", x, y, float(z), feed or self.fs["plunge"]))
        self.pos = (x, y, float(z))

    def to(self, x, y, z=None, feed=None):
        z = self.pos[2] if z is None else z
        self.cut_mm += math.dist(self.pos, (x, y, z))
        self.ev.append(("feed", float(x), float(y), float(z), feed or self.fs["feed"]))
        self.pos = (float(x), float(y), float(z))

    def line(self, pts, z=None, feed=None):
        for p in pts:
            self.to(p[0], p[1], z if len(p) < 3 else p[2], feed)

    def arc(self, x, y, z, cx, cy, cw, feed=None):
        self.ev.append(("arc", float(x), float(y), float(z), float(cx), float(cy), bool(cw), feed or self.fs["feed"]))
        self.pos = (float(x), float(y), float(z))

    def helix(self, cx, cy, r, z0, z1, feed=None):
        """Down a helix about (cx, cy) from z0 to z1 in half turns (counter-clockwise: climb in a hole), then
        once around at the bottom. Starts at (cx + r, cy)."""
        pitch = max(2 * math.pi * r * math.tan(math.radians(RAMP_DEG)), 0.05)
        n = max(1, int(math.ceil((z0 - z1) / (pitch / 2))))
        z = z0
        for k in range(n):
            z = z0 + (z1 - z0) * (k + 1) / n
            sx = cx - r if k % 2 == 0 else cx + r
            self.arc(sx, cy, z, cx, cy, False, feed)
        end = self.pos[0]
        self.arc(cx - (end - cx), cy, z1, cx, cy, False, feed)
        self.arc(end, cy, z1, cx, cy, False, feed)


# ---- facing ----------------------------------------------------------------------------------------------------

def face(job: Job, tool, prm: dict, fs: dict) -> dict:
    x0, x1, y0, y1, _zb, zt = job.box
    z_end = float(prm.get("z", job.part_top))
    depth = zt - z_end
    if depth <= 1e-6:
        return {"events": [], "info": {"skipped": "the stock's top is the part's top"}}
    so = float(prm.get("stepover") or 0.7 * tool.d)
    ap = float(prm.get("stepdown") or min(tool.flute_l * 0.5, tool.d * 0.25, max(depth, 0.1)))
    nz = max(1, int(math.ceil(depth / ap - 1e-9)))
    pen = Pen(job, tool, fs)
    R = tool.r
    ny_ = max(1, int(math.ceil((y1 - y0) / so)))
    ys = y0 + (np.arange(ny_ + 1) / ny_) * (y1 - y0) if (y1 - y0) > so else np.array([(y0 + y1) / 2])
    xa, xb = x0 - R - 1.0, x1 + R + 1.0
    for k in range(nz):
        z = zt - depth * (k + 1) / nz
        pen.over(xa, ys[0])
        pen.down(z)
        for n, y in enumerate(ys):
            a, b = (xa, xb) if n % 2 == 0 else (xb, xa)
            if n:
                pen.to(a, y, z)
            pen.to(b, y, z)
    pen.up()
    return {"events": pen.ev, "info": {"levels": nz, "stepover_mm": round(so, 3), "stepdown_mm": round(depth / nz, 3),
                                       "z_mm": round(z_end, 3)}}


# ---- adaptive clearing -------------------------------------------------------------------------------------------

def _levels(job: Job, tool, ap: float, aa: float, floors: list) -> list:
    low = float(job.Tn[job.domain].min()) if job.domain.any() else job.zb
    special = sorted({round(h + aa, 4) for h in floors if h > job.zb + 1e-6 and h < job.zt - 1e-6}, reverse=True)
    bottom = low + aa
    if low <= job.zb + 1e-6:
        bottom = job.zb - job.through             # nothing of the part there: cut through
    special = [s for s in special if s > bottom + 0.05] + [round(bottom, 4)]
    out, z = [], job.zt
    for s in special:
        n = max(1, int(math.ceil((z - s) / ap - 1e-9)))
        out += [z - (z - s) * (k + 1) / n for k in range(n)]
        z = s
    return [round(v, 4) for v in out]


def adaptive(job: Job, tool, prm: dict, fs: dict) -> dict:
    from scipy import ndimage
    c, R = job.c, tool.r
    ae = float(prm.get("stepover") or 0.2 * tool.d)
    ap = float(prm.get("stepdown") or min(tool.flute_l * 0.9, tool.d))
    ar = float(prm.get("radial_allowance", 0.3))
    aa = float(prm.get("axial_allowance", 0.2))
    floors = job.floors(max(4.0, R * R))
    levels = prm.get("levels") or _levels(job, tool, ap, aa, floors)
    # where a tool of this radius, grown by the allowance and three quarters of a cell, clears the part plus the
    # axial allowance (a through region has nothing to stay clear of)
    part = np.where(job.inside & (job.Tn > job.zb + 1e-6), job.Tn + aa, -1e9)
    Fd = ndimage.maximum_filter(part, footprint=_disc((R + ar) / c + 0.75), mode="nearest")
    disc = _disc(R / c)
    Rp = disc.shape[0] // 2
    oi, oj = np.nonzero(disc)
    oi, oj = oi - Rp, oj - Rp
    ds = max(1.5 * c, R / 5)
    light_n = max(2, int(0.04 * disc.sum()))
    sliver = max(2, int(0.02 * disc.sum()))
    w_star = ae
    need_dom = ndimage.binary_dilation(job.domain, iterations=1) if job.cutout else np.ones_like(job.domain)
    pen = Pen(job, tool, fs)
    stats = {"levels": [], "max_engagement_mm": 0.0, "steps": 0, "entries": {"open": 0, "helix": 0, "plunge": 0}}
    eng_all = []
    tools_map = {tool.number: tool}
    deltas = np.radians(np.linspace(-70, 70, 15))
    ring = np.radians(np.arange(0, 360, 15))
    for z in levels:
        A = Fd <= z + 1e-6
        # nothing may stand higher than the flutes within the cutter's radius, nor reach the holder within its own
        A &= ndimage.maximum_filter(job.stock.Z, footprint=disc, mode="nearest") <= z + tool.flute_l + 1e-6
        if tool.holder_r > tool.shank_r + 1e-9:
            A &= ndimage.maximum_filter(job.stock.Z, footprint=_disc(tool.holder_r / c + 1), mode="nearest") <= z + tool.length + 1e-6
        Mreal = job.stock.Z > max(z, job.zb) + 1e-6       # under the stock there is nothing to cut
        reach = _count(A, disc) > 0
        Mneed = Mreal & need_dom & reach
        if int(Mneed.sum()) < 4:
            continue
        # padded copies so that a disc near the border needs no bounds checks
        M = np.zeros((job.nx + 2 * Rp, job.ny + 2 * Rp), bool)
        M[Rp:-Rp, Rp:-Rp] = Mreal
        N = np.zeros_like(M)
        N[Rp:-Rp, Rp:-Rp] = Mneed
        dead = np.zeros_like(A)
        mark = len(pen.ev)
        pos, head = None, 0.0
        budget = int(6 * Mreal.sum() * c * c / (max(ae, c) * ds)) + 2000
        level_eng = []
        guard = 0
        while budget > 0 and guard < 4000:
            guard += 1
            cnt = _count(M[Rp:-Rp, Rp:-Rp], disc)
            cneed = _count(N[Rp:-Rp, Rp:-Rp], disc)
            todo = A & (cneed >= sliver) & ~dead         # less than a sliver is left for the finishing pass
            if not todo.any():
                break
            free = A & (cnt <= light_n)                    # where the cutter stands in next to nothing
            front = free & ndimage.binary_dilation(todo, iterations=3) & ~dead
            if front.any():
                fi, fj = np.nonzero(front)
                if pos is None:
                    k = int(np.argmax(cneed[fi, fj]))
                else:
                    k = int(np.argmin((job.xc[fi] - pos[0]) ** 2 + (job.yc[fj] - pos[1]) ** 2))
                si, sj = int(fi[k]), int(fj[k])
                start = (float(job.xc[si]), float(job.yc[sj]))
                link = False
                if pos is not None:
                    n = max(2, int(math.dist(pos, start) / c) + 1)
                    lx = np.linspace(pos[0], start[0], n)
                    ly = np.linspace(pos[1], start[1], n)
                    li, lj = job.nodes(np.stack([lx, ly], axis=1))
                    link = bool(free[li, lj].all()) and math.dist(pos, start) < 12 * tool.d
                if link:
                    pen.to(start[0], start[1], z)
                else:
                    pen.over(*start)
                    pen.down(z)
                    stats["entries"]["open"] += 1
                pos = start
                # the material's side: steer so that it stays on the right (climb milling)
                wi = np.clip(si + oi * 2, 0, job.nx - 1)
                wj = np.clip(sj + oj * 2, 0, job.ny - 1)
                mm = Mreal[wi, wj] & M[wi + Rp, wj + Rp]
                if mm.any():
                    g = np.array([(job.xc[wi[mm]] - pos[0]).mean(), (job.yc[wj[mm]] - pos[1]).mean()])
                    head = math.atan2(g[0], -g[1])        # g turned a quarter turn counter-clockwise
                cands = head + ring
            else:
                # no cleared ground to start from: go down a helix where there is the most room
                edt = ndimage.distance_transform_edt(A) * c
                room = np.where(todo, edt, -1.0)
                si, sj = np.unravel_index(int(np.argmax(room)), room.shape)
                cx, cy = float(job.xc[si]), float(job.yc[sj])
                rh = min(0.8 * R, float(room[si, sj]) - c)
                top = job.stock_top(cx, cy, R + max(rh, 0)) + 0.5
                if rh >= 0.15 * R:
                    pen.over(cx + rh, cy)
                    pen.down(max(top, z), fs["plunge"])
                    pen.helix(cx, cy, rh, max(top, z), z, fs["plunge"])
                    stats["entries"]["helix"] += 1
                    rr = _disc((rh + R) / c)
                else:
                    rh = 0.0
                    pen.over(cx, cy)
                    pen.down(z)
                    stats["entries"]["plunge"] += 1
                    rr = disc
                hi_, hj_ = np.nonzero(rr)
                hp = rr.shape[0] // 2
                wi = np.clip(si + hi_ - hp, 0, job.nx - 1) + Rp
                wj = np.clip(sj + hj_ - hp, 0, job.ny - 1) + Rp
                M[wi, wj] = False
                N[wi, wj] = False
                pos = (cx + rh, cy)
                dead[si, sj] = True                      # this spot has been entered: never chosen again
                continue
            # steer
            run = [pos]
            moved = False
            while budget > 0:
                budget -= 1
                px = pos[0] + ds * np.cos(cands)
                py = pos[1] + ds * np.sin(cands)
                ci, cj = job.nodes(np.stack([px, py], axis=1))
                ok = A[ci, cj]
                got = M[(ci[:, None] + oi[None, :]) + Rp, (cj[:, None] + oj[None, :]) + Rp].sum(axis=1)
                w = got * c * c / ds
                ok &= got > 0
                if not ok.any():
                    break
                turn = np.abs(np.angle(np.exp(1j * (cands - head))))
                score = np.abs(w - w_star) + 0.02 * w_star * turn
                score = np.where(w > 1.5 * w_star, 10 * w_star + w, score)       # too wide a bite only if nothing else
                score = np.where(ok, score, np.inf)
                k = int(np.argmin(score))
                pos = (float(px[k]), float(py[k]))
                head = float(cands[k])
                M[ci[k] + oi + Rp, cj[k] + oj + Rp] = False
                N[ci[k] + oi + Rp, cj[k] + oj + Rp] = False
                run.append(pos)
                level_eng.append(float(w[k]))
                moved = True
                cands = head + deltas
            if moved:
                pts = dropcutter.simplify(np.array(run), 0.02)
                pen.line(pts[1:], z)
                stats["steps"] += len(run) - 1
            else:
                dead[si, sj] = True
        if len(pen.ev) > mark:
            pen.up()
            job.apply([("tool", tool.number)] + pen.ev[mark:], tools_map)
            if level_eng:
                e = np.array(level_eng)
                stats["levels"].append({"z_mm": z, "mean_engagement_mm": round(float(e.mean()), 3),
                                        "p95_engagement_mm": round(float(np.percentile(e, 95)), 3),
                                        "max_engagement_mm": round(float(e.max()), 3)})
                eng_all.append(e)
    if eng_all:
        e = np.concatenate(eng_all)
        stats["mean_engagement_mm"] = round(float(e.mean()), 3)
        stats["p95_engagement_mm"] = round(float(np.percentile(e, 95)), 3)
        stats["max_engagement_mm"] = round(float(e.max()), 3)
        stats["engagement_angle_deg"] = round(math.degrees(math.acos(max(-1.0, 1 - 2 * min(float(np.percentile(e, 95)), tool.d) / tool.d))), 1)
    stats.update({"stepover_mm": ae, "stepdown_mm": ap, "radial_allowance_mm": ar, "axial_allowance_mm": aa,
                  "step_mm": round(ds, 3), "applied": True,
                  "engagement": "the width of material the cutter meets per step, counted on the plan's grid "
                                f"({c:g} mm cells); the first move out of an entry cuts a full slot"})
    return {"events": pen.ev, "info": stats}


# ---- 2.5D finishing ----------------------------------------------------------------------------------------------

def _keep_where(line: np.ndarray, flag: np.ndarray) -> list:
    """The stretches of a polyline whose points are flagged (with one point of margin each side)."""
    if flag.all():
        return [line]
    grow = flag.copy()
    grow[:-1] |= flag[1:]
    grow[1:] |= flag[:-1]
    out, start = [], None
    for i, f in enumerate(grow):
        if f and start is None:
            start = i
        if (not f or i == len(grow) - 1) and start is not None:
            end = i + 1 if f else i
            if end - start >= 2:
                out.append(line[start:end])
            start = None
    if len(out) >= 2 and dropcutter.closed(line) and grow[0] and grow[-1]:
        out[0] = np.concatenate([out[-1], out[0][1:]])
        out.pop()
    return out


def _order(lines: list, start=None) -> list:
    """Nearest-first order of polylines (closed ones may start anywhere; kept as they are)."""
    left = list(lines)
    out, at = [], start
    while left:
        if at is None:
            k = 0
        else:
            k = int(np.argmin([min(np.linalg.norm(l[0] - at), np.linalg.norm(l[-1] - at)) for l in left]))
        l = left.pop(k)
        if dropcutter.closed(l) and at is not None:
            j = int(np.argmin(np.linalg.norm(l[:-1] - at, axis=1)))
            l = np.concatenate([l[j:-1], l[:j + 1]])
        out.append(l)
        at = l[-1]
    return out


def finish(job: Job, tool, prm: dict, fs: dict) -> dict:
    from scipy import ndimage
    c, R = job.c, tool.r
    so = float(prm.get("stepover") or 0.5 * tool.d)
    floors = [h for h in job.floors(max(1.0, 0.25 * R * R)) if h < job.zt + 1e-6]
    levels = sorted({round(h, 4) for h in floors if h > job.zb + 1e-6}, reverse=True)
    through = bool((job.domain & (job.Tn <= job.zb + 1e-6)).any())
    if through:
        levels.append(round(job.zb - job.through, 4))
    if prm.get("levels"):
        levels = [float(v) for v in prm["levels"]]
    # a wall taller than the flutes is finished in steps from the top, each along its own boundary
    step = 0.8 * tool.flute_l
    full = []
    for z in levels:
        n = int(math.ceil((job.zt - z) / step - 1e-9)) - 1 if step > 0 else 0
        full += [(round(z + k * step, 4), False) for k in range(max(n, 0), 0, -1)] + [(z, True)]
    pen = Pen(job, tool, fs)
    info = {"levels": [], "stepover_mm": so}
    disc = _disc((R + c) / c)
    tools_map = {tool.number: tool}
    for z, is_floor in full:
        mat = job.stock.Z > max(z, job.zb) + 1e-4
        if job.cutout:
            mat &= ndimage.binary_dilation(job.domain, iterations=1)
        near = _count(mat, disc) > 0                              # cells where a tool standing there meets material
        if not near.any():
            continue
        F = job.level_field(tool, z)
        A = F <= z + 1e-6
        mark = len(pen.ev)
        lines = []
        # the floor, in rings parallel to the walls, the innermost first
        if is_floor and z > job.zb - 1e-9 and so > 0:
            edt = ndimage.distance_transform_edt(A) * c
            k = 1
            rings = []
            while k * so < float(edt.max()):
                rings.append(dropcutter.contours(-edt, -k * so, (job.xc[0], job.yc[0]), c, min_len=2 * c))
                k += 1
            # the middle of each region, where the last ring is more than a cutter's reach from the far side
            lab, nlab = ndimage.label(A & near)
            if nlab:
                mx = ndimage.maximum(edt, lab, np.arange(1, nlab + 1))
                for q, m in enumerate(np.atleast_1d(mx), 1):
                    last = math.floor((m - 1e-9) / so) * so
                    if m - last > 0.85 * R and m > 0.85 * R:
                        sub = np.where(lab == q, edt, 0.0)
                        rings.insert(0, dropcutter.contours(-sub, -(m - 0.85 * R), (job.xc[0], job.yc[0]), c, min_len=0.0))
            for r in reversed(rings):
                lines += r
        walls = dropcutter.waterline(job.mesh, tool, z, (job.xc[0], job.yc[0]), c, (job.nx, job.ny), F=F, min_len=2 * c)
        cut = []
        for group, exact in ((lines, False), (walls, True)):
            part = []
            for l in group:
                li, lj = job.nodes(l)
                part += _keep_where(l, near[li, lj])
            cut.append(part)
        n_floor, n_wall = len(cut[0]), len(cut[1])
        at = None
        for part in cut:
            for l in _order(part, at):
                l = dropcutter.simplify(l, 0.003)
                if pen.pos is not None and pen.pos[2] <= z + 1e-9 and math.dist(pen.pos[:2], l[0]) < 1.5 * so + c:
                    pen.to(l[0][0], l[0][1], z)
                else:
                    pen.over(*l[0])
                    pen.down(z)
                pen.line(l[1:], z)
                at = l[-1]
        if len(pen.ev) > mark:
            pen.up()
            job.apply([("tool", tool.number)] + pen.ev[mark:], tools_map)
            info["levels"].append({"z_mm": z, "floor_passes": n_floor, "wall_passes": n_wall})
    info["applied"] = True
    info["method"] = "walls along the drop-cutter's boundary at each level (exact for the tessellation at every grid " \
                     f"crossing, {c:g} mm apart); floors in rings {so:g} mm apart"
    return {"events": pen.ev, "info": info}


# ---- contour with tabs -------------------------------------------------------------------------------------------

def contour(job: Job, tool, prm: dict, fs: dict) -> dict:
    c = job.c
    F = job.level_field(tool, job.zb)
    z_end = job.zb - job.through
    lines = dropcutter.waterline(job.mesh, tool, job.zb, (job.xc[0], job.yc[0]), c, (job.nx, job.ny), F=F, min_len=4 * c)
    outer = []
    for l in lines:
        li, lj = job.nodes(l)
        if dropcutter.closed(l) and not job.domain[li, lj].any():
            outer.append(l)
    if not outer:
        return {"events": [], "info": {"skipped": "no closed outline to cut around"}}
    ap = float(prm.get("stepdown") or 0.5 * tool.d)
    n_tabs = int(prm.get("tabs", 4))
    tab_w = float(prm.get("tab_width") or 6.0)
    tab_h = float(prm.get("tab_height") or 1.5)
    depth = job.zt - z_end
    nz = max(1, int(math.ceil(depth / ap - 1e-9)))
    pen = Pen(job, tool, fs)
    tabs_out = []
    for l in outer:
        l = dropcutter.simplify(l, 0.003)
        seg = np.linalg.norm(np.diff(l, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        L = float(s[-1])
        spans = []
        if n_tabs > 0 and L > 2 * n_tabs * (tab_w + tool.d):
            for k in range(n_tabs):
                mid = (k + 0.5) * L / n_tabs
                spans.append((mid - (tab_w + tool.d) / 2, mid + (tab_w + tool.d) / 2))
                tabs_out.append([round(float(np.interp(mid, s, l[:, 0])), 3), round(float(np.interp(mid, s, l[:, 1])), 3)])
        # the outline with a point at every tab end
        cuts = sorted({v for a, b in spans for v in (a, b)})
        ss = np.unique(np.concatenate([s, cuts]))
        pts = np.stack([np.interp(ss, s, l[:, 0]), np.interp(ss, s, l[:, 1])], axis=1)
        in_tab = np.zeros(len(ss), bool)
        for a, b in spans:
            in_tab |= (ss >= a - 1e-9) & (ss <= b + 1e-9)
        pen.over(*pts[0])
        for k in range(nz):
            z = job.zt - depth * (k + 1) / nz
            zt_ = job.zb + tab_h
            pen.down(z) if k == 0 else pen.to(pts[0][0], pts[0][1], max(z, zt_) if in_tab[0] else z, fs["plunge"])
            for i in range(1, len(pts)):
                both = in_tab[i] and in_tab[i - 1]
                zz = max(z, zt_) if both else z
                if abs(pen.pos[2] - zz) > 1e-9:               # onto or off a tab: straight up or down
                    pen.to(pen.pos[0], pen.pos[1], zz, fs["plunge"])
                pen.to(pts[i][0], pts[i][1], zz)
    pen.up()
    info = {"outlines": len(outer), "levels": nz, "stepdown_mm": round(depth / nz, 3), "z_mm": round(z_end, 3),
            "tabs": {"count": len(tabs_out), "width_mm": tab_w, "height_mm": tab_h, "at": tabs_out,
                     "note": "left standing to hold the part; cut by hand"} if tabs_out else None,
            "method": "the drop-cutter's boundary around the part at the stock's underside, a full-width slot"}
    return {"events": pen.ev, "info": info}


# ---- holes -------------------------------------------------------------------------------------------------------

def vertical_holes(job: Job) -> list:
    out = []
    for h in job.holes:
        ax = np.asarray(h["axis"], float)
        if abs(abs(ax[2]) - 1.0) > 1e-6:
            continue
        at = np.asarray(h["at"], float)
        top, bot = at[2] + h["depth"] / 2, at[2] - h["depth"] / 2
        i, j = job.node(at[0], at[1])
        if job.T[i, j] > bot + 1e-3 and np.isfinite(job.T[i, j]) and job.T[i, j] > top - 1e-3:
            continue                                    # closed from above: not reachable in this setup
        out.append({"x": float(at[0]), "y": float(at[1]), "d": float(h["d"]), "top": float(top), "bottom": float(bot),
                    "through": bool(bot <= job.zb + 1e-4)})
    return out


def drill(job: Job, tool, prm: dict, fs: dict) -> dict:
    holes = prm.get("holes")
    if holes is None:
        holes = [h for h in vertical_holes(job) if abs(h["d"] - tool.d) <= float(prm.get("match", 0.011))]
    if not holes:
        return {"events": [], "info": {"skipped": f"no vertical hole of Ø{tool.d:g} mm"}}
    peck_at = float(prm.get("peck_over", 3.0))
    ev, done = [], []
    pos = None
    for h in sorted(holes, key=lambda q: (round(q["y"], 3), q["x"])):
        x, y = h["x"], h["y"]
        # where the drill's point meets the part: asked of a drill 0.1 mm smaller, since one exactly the hole's
        # size touches the hole's own rim
        probe = replace(tool, d=max(tool.d - 0.1, 0.5 * tool.d))
        zdrop = float(job.mesh.drop(probe, [[x, y]])[0]) - (tool.cone_h - probe.cone_h)
        z = max(zdrop, job.zb - tool.cone_h - job.through) if np.isfinite(zdrop) else job.zb - tool.cone_h - job.through
        z = float(prm.get("z", z))
        r = job.stock_top(x, y, tool.r) + SAFE_GAP
        depth = r - z
        q = float(prm.get("peck") or (tool.d if depth > peck_at * tool.d else 0.0))
        if pos is None:
            ev.append(("rapid", x, y, job.zc))
        ev.append(("rapid", x, y, job.zc))
        ev.append(("drill", x, y, z, r, q, fs["feed"]))
        pos = (x, y)
        done.append({"at": [round(x, 3), round(y, 3)], "d": h["d"], "z_mm": round(z, 3), "peck_mm": q,
                     "through": bool(h.get("through")),
                     "full_diameter_to_mm": round(z + tool.cone_h, 3),
                     "note": ("through" if h.get("through") else "the point stops where it meets the part: a flat-bottomed "
                              "hole keeps a cone of material the drill cannot take") if "through" in h else ""})
    return {"events": ev, "info": {"holes": done, "peck_rule": f"peck by one diameter when deeper than {peck_at:g} × d (assumed)"}}


def bore(job: Job, tool, prm: dict, fs: dict) -> dict:
    holes = prm.get("holes")
    if holes is None:
        holes = [h for h in vertical_holes(job) if tool.d * 1.05 <= h["d"] <= tool.d * 1.9]
    if not holes:
        return {"events": [], "info": {"skipped": "no hole between 1.05 and 1.9 cutter diameters"}}
    pen = Pen(job, tool, fs)
    done = []
    for h in holes:
        x, y = h["x"], h["y"]
        rc = h["d"] / 2 - tool.r
        ang = np.linspace(0, 2 * math.pi, 49)[:-1]
        probe = replace(tool, d=tool.d - 0.04)           # a cutter exactly on the wall touches the hole's own rim
        zd = job.mesh.drop(probe, np.stack([x + rc * np.cos(ang), y + rc * np.sin(ang)], axis=1))
        zd = zd[np.isfinite(zd)]
        z = float(zd.max()) if len(zd) else job.zb - job.through
        z = max(z, job.zb - job.through)
        top = job.stock_top(x, y, h["d"] / 2) + 0.5
        pen.over(x + rc, y)
        pen.down(top, fs["plunge"])
        pen.helix(x, y, rc, top, z, fs["plunge"])
        pen.to(x, y, z)                                 # off the wall before leaving
        pen.up()
        done.append({"at": [round(x, 3), round(y, 3)], "d": h["d"], "z_mm": round(z, 3), "helix_radius_mm": round(rc, 4),
                     "through": bool(h.get("through"))})
    return {"events": pen.ev, "info": {"holes": done, "ramp_deg": RAMP_DEG}}


# ---- chamfer -----------------------------------------------------------------------------------------------------

def chamfer(job: Job, tool, prm: dict, fs: dict) -> dict:
    """Break the edges of level faces by `width` (the chamfer's height and, at 45°, its leg). The tool's cone
    passes through the edge's wall `width` below the face; the axis runs beside the edge at the offset that keeps
    the tip off the wall. On a model whose edge is sharp this cuts into the model by design, which the plan
    declares and the simulation reports as an edge break."""
    from . import tools as tools_mod
    c = job.c
    w = float(prm.get("width", 0.5))
    ta = math.tan(tool.half_angle)
    rt = tool.tip_d / 2
    e = float(prm.get("offset") or max(rt, min(tool.r - w * ta - 0.2, max(0.25 * tool.r, rt))))
    if e + w * ta > tool.r + 1e-9 or e < rt - 1e-9:
        return {"events": [], "info": {"skipped": f"a Ø{tool.d:g} mm chamfer mill cannot cut a {w:g} mm chamfer"}}
    probe = tools_mod.make({"kind": "flat", "d": max(2 * e, 2 * c), "flute_l": 1, "length": 1})
    levels = prm.get("levels") or [h for h in job.floors(max(1.0, tool.r ** 2 * 0.25)) if h > job.zb + w + 1e-6]
    pen = Pen(job, tool, fs)
    edges = 0.0
    for h in levels:
        z_tip = h - w - (e - rt) / ta
        # the axis's path: where a pin of radius e just clears everything standing at this face's height or above
        F = job.level_field(probe, h - 1e-4)
        lines = dropcutter.waterline(job.mesh, probe, h - 1e-4, (job.xc[0], job.yc[0]), c, (job.nx, job.ny), F=F, min_len=4 * c)
        for l in lines:
            # keep the stretches with room below for the tip and beside for the cone
            zd = job.mesh.drop(tools_mod.make({"kind": "flat", "d": max(2 * rt, 0.2), "flute_l": 1, "length": 1}), l)
            ok = ~(zd > z_tip + 0.05)
            # only the edges of the face at this height: the part is on the right of the path, and what stands
            # just inside the edge there must be this face (not a wall that goes on up)
            d = np.gradient(l, axis=0)
            nrm = np.stack([d[:, 1], -d[:, 0]], axis=1)
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]
            qi, qj = job.nodes(l + nrm * (e + 1.5 * c))
            ok &= np.abs(job.Tn[qi, qj] - h) < 1e-3
            for part in _keep_where(l, ok):
                part = dropcutter.simplify(part, 0.003)
                if len(part) < 2:
                    continue
                pen.over(*part[0])
                pen.down(z_tip)
                pen.line(part[1:], z_tip)
                edges += float(np.linalg.norm(np.diff(part, axis=0), axis=1).sum())
                job.intended.append({"line": part.tolist(), "z": float(h), "w": e + w * ta, "h": w,
                                     "depth": w * math.sin(tool.half_angle) if abs(ta - 1) < 1e-9 else w * max(math.sin(tool.half_angle), math.cos(tool.half_angle))})
    pen.up()
    if not edges:
        return {"events": [], "info": {"skipped": "no edge with room for the tool"}}
    return {"events": pen.ev, "info": {"width_mm": w, "edge_mm": round(edges, 2), "axis_offset_mm": round(e, 3),
                                       "declared": "an edge break of this width on the edges of the level faces; on a "
                                                   "sharp modelled edge it is cut into the model on purpose"}}


# ---- 3D finishing ------------------------------------------------------------------------------------------------

def freeform(job: Job, lo_slope: float = 0.02, hi_slope: float = 12.0) -> tuple[np.ndarray, np.ndarray]:
    """Cells of the part that are neither level nor a wall: (mask, slope as rise over run). A cell counts when the
    surface rises through it at about the same rate on both sides (a step between two levels does not: there the
    height changes on one side only)."""
    T = np.where(job.inside, job.T, np.nan)
    c = job.c

    def both(axis):
        f = np.full(T.shape, np.nan)
        b = np.full(T.shape, np.nan)
        d = np.diff(T, axis=axis) / c
        if axis == 0:
            f[:-1, :], b[1:, :] = d, d
        else:
            f[:, :-1], b[:, 1:] = d, d
        return f, b
    xf, xb = both(0)
    yf, yb = both(1)
    with np.errstate(invalid="ignore"):
        smooth = (np.abs(xf - xb) <= 0.35 * np.maximum(np.abs(xf), np.abs(xb)) + 0.02) & \
                 (np.abs(yf - yb) <= 0.35 * np.maximum(np.abs(yf), np.abs(yb)) + 0.02)
        s = np.hypot((xf + xb) / 2, (yf + yb) / 2)
        ok = np.isfinite(s) & smooth
        return ok & (s > lo_slope) & (s < hi_slope), np.where(ok, s, 0.0)


def scallop_stepover(r: float, height: float) -> float:
    """The stepover that leaves cusps of the given height between passes of a ball of radius r on a level
    surface: 2·sqrt(h·(2r − h))."""
    return 2.0 * math.sqrt(max(height * (2 * r - height), 0.0))


def scallop_height(r: float, stepover: float) -> float:
    """Cusp height between passes a stepover apart with a ball of radius r on a level surface:
    r − sqrt(r² − (s/2)²)."""
    return r - math.sqrt(max(r * r - (stepover / 2) ** 2, 0.0))


def raster(job: Job, tool, prm: dict, fs: dict) -> dict:
    from scipy import ndimage
    c = job.c
    so = float(prm.get("stepover") or scallop_stepover(tool.r if tool.kind == "ball" else max(tool.corner_r, 0.2 * tool.r),
                                                          float(prm.get("scallop", 0.01))))
    step = float(prm.get("step") or max(c, 0.25))
    region = prm.get("region")
    if region is None:
        mask, _ = freeform(job)
        if prm.get("all"):
            mask = job.inside.copy()
        mask = ndimage.binary_dilation(mask, structure=_disc(tool.r / c + 1))
    else:
        mask = np.asarray(region, bool)
    if not mask.any():
        return {"events": [], "info": {"skipped": "no sloped or curved surface seen from above"}}
    along_y = str(prm.get("direction", "x")).lower() == "y"
    ii, jj = np.nonzero(mask)
    xr = (float(job.xc[ii.min()]), float(job.xc[ii.max()]))
    yr = (float(job.yc[jj.min()]), float(job.yc[jj.max()]))
    (u0, u1), (v0, v1) = (yr, xr) if along_y else (xr, yr)
    nv = max(1, int(math.ceil((v1 - v0) / so)))
    vs = v0 + (np.arange(nv + 1) / nv) * (v1 - v0)
    us = np.arange(u0, u1 + step / 2, step)
    U, V = np.meshgrid(us, vs, indexing="ij")
    X, Y = (V, U) if along_y else (U, V)
    pts = np.stack([X.ravel(), Y.ravel()], axis=1)
    li, lj = job.nodes(pts)
    keep = mask[li, lj]
    Z = np.full(len(pts), np.nan)
    floor = float(prm.get("floor", job.zb))
    if keep.any():
        z = job.mesh.drop(tool, pts[keep])
        Z[keep] = np.where(np.isfinite(z), np.maximum(z, floor), np.nan)      # only where the tool touches the part
    Z = Z.reshape(U.shape)
    chord = float(prm.get("chord", 0.003))
    pen = Pen(job, tool, fs)
    passes, npts = 0, 0
    for k in range(len(vs)):
        col = Z[:, k]
        order = np.arange(len(us)) if k % 2 == 0 else np.arange(len(us))[::-1]
        run = []
        for i in list(order) + [None]:
            if i is not None and np.isfinite(col[i]):
                x, y = (vs[k], us[i]) if along_y else (us[i], vs[k])
                run.append((x, y, float(col[i])))
                continue
            if len(run) >= 2:
                run_a = _simplify3(_refine_run(job, tool, np.array(run), chord, floor), 0.002)
                near = pen.pos is not None and pen.pos[2] < job.zc - 1e-9 and math.dist(pen.pos[:2], run_a[0][:2]) <= 1.5 * so
                if near:
                    pen.to(*run_a[0])
                else:
                    pen.over(run_a[0][0], run_a[0][1])
                    pen.down(run_a[0][2])
                pen.line(run_a[1:])
                passes += 1
                npts += len(run)
            run = []
    pen.up()
    r_eff = tool.r if tool.kind == "ball" else tool.corner_r
    return {"events": pen.ev, "info": {"passes": passes, "points": npts, "stepover_mm": round(so, 4), "step_mm": step,
                                       "direction": "y" if along_y else "x",
                                       "scallop_mm": round(scallop_height(r_eff, so), 5) if r_eff > 0 else None,
                                       "scallop_formula": "r − sqrt(r² − (stepover / 2)²) on a level surface; more on a slope across the passes",
                                       "method": "every point's height from the drop-cutter on the tessellation (exact for it)"}}


def _refine_run(job: Job, tool, run: np.ndarray, tol: float, floor: float, depth: int = 9) -> np.ndarray:
    """Add points where the tool's true height between two points leaves their chord by more than tol (the
    drop-cutter at each midpoint, again until it holds or the points are 1/512 of the step apart). Where a pass
    rolls over an edge the height falls faster than any fixed step follows."""
    for _ in range(depth):
        mid = (run[:-1] + run[1:]) / 2
        z = job.mesh.drop(tool, mid[:, :2])
        z = np.where(np.isfinite(z), np.maximum(z, floor), mid[:, 2])
        bad = np.abs(z - mid[:, 2]) > tol
        if not bad.any():
            break
        mid[:, 2] = z
        out = np.empty((len(run) + int(bad.sum()), 3))
        idx = np.arange(len(run)) + np.concatenate([[0], np.cumsum(bad)])
        out[idx] = run
        out[idx[:-1][bad] + 1] = mid[bad]
        run = out
    return run


def _simplify3(pts: np.ndarray, tol: float) -> np.ndarray:
    n = len(pts)
    if n < 3:
        return pts
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, ab = pts[i], pts[j] - pts[i]
        L2 = float(ab @ ab)
        p = pts[i + 1:j]
        t = np.clip(((p - a) @ ab) / max(L2, 1e-30), 0.0, 1.0)
        d = np.linalg.norm(p - (a + t[:, None] * ab), axis=1)
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


def waterline(job: Job, tool, prm: dict, fs: dict) -> dict:
    from scipy import ndimage
    c = job.c
    dz = float(prm.get("stepdown") or 0.1 * tool.d)
    region = prm.get("region")
    if region is None:
        mask, slope = freeform(job)
        mask &= slope >= float(prm.get("min_slope", 0.8))
        mask = ndimage.binary_dilation(mask, structure=_disc(tool.r / c + 1))
    else:
        mask = np.asarray(region, bool)
    if prm.get("all"):
        mask = np.ones_like(job.inside)
    if not mask.any():
        return {"events": [], "info": {"skipped": "no steep curved surface"}}
    top = float(prm.get("top", job.part_top))
    bottom = float(prm.get("bottom", max(job.zb, float(job.Tn[job.inside].min()) if job.inside.any() else job.zb)))
    n = max(1, int(math.ceil((top - bottom) / dz)))
    pen = Pen(job, tool, fs)
    passes = 0
    for k in range(1, n + 1):
        z = top - (top - bottom) * k / n
        at = None
        parts = []
        F = job.level_field(tool, z)
        for l in dropcutter.waterline(job.mesh, tool, z, (job.xc[0], job.yc[0]), c, (job.nx, job.ny), F=F, min_len=4 * c):
            li, lj = job.nodes(l)
            parts += _keep_where(l, mask[li, lj])
        for l in _order(parts, at):
            l = dropcutter.simplify(l, 0.003)
            pen.over(*l[0])
            pen.down(z)
            pen.line(l[1:], z)
            at = l[-1]
            passes += 1
    pen.up()
    return {"events": pen.ev, "info": {"levels": n, "passes": passes, "stepdown_mm": round((top - bottom) / n, 4),
                                       "method": "the drop-cutter's boundary at each height (exact at every grid crossing)"}}


OPS = {"face": face, "adaptive": adaptive, "finish": finish, "contour": contour, "drill": drill, "bore": bore,
       "chamfer": chamfer, "raster": raster, "waterline": waterline}
KINDS = {"face": ("flat", "bull"), "adaptive": ("flat", "bull"), "finish": ("flat", "bull"), "contour": ("flat", "bull"),
         "drill": ("drill",), "bore": ("flat", "bull"), "chamfer": ("chamfer",), "raster": ("ball", "bull"),
         "waterline": ("ball", "bull", "flat")}
LABELS = {"face": "Facing", "adaptive": "Adaptive clearing", "finish": "Finish floors and walls", "contour": "Contour with tabs",
          "drill": "Drilling", "bore": "Helical boring", "chamfer": "Chamfer", "raster": "3D finish, parallel",
          "waterline": "3D finish, waterline"}
