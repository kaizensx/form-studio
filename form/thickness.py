"""Wall thickness of a solid, measured once and everywhere: every thin region in one answer.

A ThicknessField is the opposing-wall distance at every vertex of the kernel's tessellation (the 0.05 mm one the
checks use), with long triangles split so no sample is more than H_COARSE apart, and split again to `h_fine` wherever
a sample is under twice the floor. Each sample casts the ray `analysis.wall_hit` casts (inward along the surface
normal, the nearest face it meets, discarded when that face is not within 30° of parallel: a wedge, not a wall), here
on the triangles, through a uniform grid, so the whole surface is measured in about a second. The samples under the
limit are clustered into regions; the B-rep ray itself (analysis.wall_hit, the same call the old random-ray check
made) is cast from each region's thinnest samples and its answer is the region's minimum. Nothing is random: the same
solid gives the same field and the same regions, every time.

    regions(key_or_model_or_shape, floor)   -> {"regions": [...], "thinnest": {...}, "samples": n, ...}

`floor` is the wall a design must not go under (two perimeters: 2 × nozzle); regions are reported up to `upto`
(default 1.5 × floor, three perimeters, the checks' "marginal" band). The field is cached in memory and, when a
directory is known, in <data>/.cache/thickness/<key>.npz. When the previous field of a similar solid is in memory, a
sample whose ray only passes through grid cells where no triangle changed keeps its earlier answer (exactly the
answer it would get again: same origin, same direction, same triangles), so a revision that changes one feature
recomputes only around it.

Region kinds (a description for people and agents, never a verdict; the checks compare `min` to their thresholds):
  wall        the two faces are within 10° of parallel: a plate or rib of nearly constant thickness
  knife_edge  the faces converge and meet at an edge: material tapering to nothing (a feather edge, a sharp lip)
  crest       the faces converge but do not meet: the top of a ridge (a truncated thread crest, a tooth tip)
  sliver      no longer than twice the floor in any direction: a speck of material, often what a boolean left

Runs in the kernel worker (it needs the B-rep for the arbitrating rays); the grid caster itself is plain numpy.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

VERSION = 1
H_COARSE = 5.0           # mm: long triangle edges are split to this, everywhere (curved faces are already finer)
CELL = 0.75              # mm: grid cell, and the step a ray is marched by
CAP = 6.0                # mm: rays look this far; when nothing at all is found within it, they look across the part
WALL_PARALLEL = 0.866    # cos 30°: analysis.WALL_PARALLEL, the same rule
PARALLEL_WALL = 0.985    # cos 10°: a "wall" region, not a converging one
FALLBACK_RAYS = 64      # B-rep rays at most, from the thinnest samples up, for the thinnest wall of a part with no thin region
ARBITERS = 8             # B-rep rays per region, from its thinnest samples
SPREAD = 0.1            # mm: corners of a triangle closer than this in thickness need no finer samples (the
                         # 0.05 mm tessellation alone moves a curved wall's samples by up to about this)
EPS_T = 1e-3             # a hit closer than this is the start face itself (wall_hit's rule)
INSET = 0.02             # mm: samples sit this far inside their face, so a ray from an edge does not run along the next face

_mem: dict = {}          # (key, tol) -> ThicknessField, a few kept, the last one first


def _mix(words: np.ndarray) -> np.ndarray:
    """A 64-bit hash per row of a uint64 array (splitmix-style), the same for the same bytes on any run."""
    h = np.full(len(words), 0x9E3779B97F4A7C15, dtype=np.uint64)
    with np.errstate(over="ignore"):
        for j in range(words.shape[1]):
            x = words[:, j] ^ (h >> np.uint64(29))
            x = x * np.uint64(0xBF58476D1CE4E5B9)
            x ^= x >> np.uint64(31)
            h = (h ^ x) * np.uint64(0x94D049BB133111EB)
            h ^= h >> np.uint64(32)
    return h


def _rows_hash(*arrays) -> np.ndarray:
    a = np.concatenate([np.ascontiguousarray(x, dtype=np.float64).reshape(len(x), -1) for x in arrays], axis=1)
    return _mix(np.ascontiguousarray(a).view(np.uint64))


def _refine(P, T, h):
    from .analysis import refine
    return refine(P, T, h)


def _vertex_normals_and_samples(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    tri_area = np.linalg.norm(n, axis=1) / 2
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, T[:, k], n)                        # area-weighted (|n| = 2 × area)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-300)
    cen = (a + b + c) / 3
    acc, cnt, area = np.zeros_like(P), np.zeros(len(P)), np.zeros(len(P))
    for k in range(3):
        np.add.at(acc, T[:, k], cen)
        np.add.at(cnt, T[:, k], 1)
        np.add.at(area, T[:, k], tri_area / 3)
    inward = acc / np.maximum(cnt, 1)[:, None] - P
    inward -= np.einsum("ij,ij->i", inward, N)[:, None] * N    # along the surface: on a hole the triangles' centres
    ln = np.linalg.norm(inward, axis=1, keepdims=True)         # lie in the air, and a ray from there meets its own face
    S = P + inward / np.maximum(ln, 1e-12) * np.minimum(ln, INSET)
    used = cnt > 0
    return S, N, area, used


class _Grid:
    """Triangles in cells of CELL mm, each one inflated by half a cell: the sample of a ray nearest a point it crosses is
    then in a cell that holds the triangle it crosses, so marching the ray cell by cell misses nothing."""

    def __init__(self, A, B, C, sid):
        g = CELL
        lo = np.floor((np.minimum(np.minimum(A, B), C) - g / 2 - 1e-9) / g).astype(np.int64)
        hi = np.floor((np.maximum(np.maximum(A, B), C) + g / 2 + 1e-9) / g).astype(np.int64)
        self.origin = lo.min(axis=0) if len(lo) else np.zeros(3, dtype=np.int64)
        self.dims = (hi.max(axis=0) - self.origin + 1) if len(hi) else np.ones(3, dtype=np.int64)
        span = hi - lo + 1
        cnt = span.prod(axis=1)
        tri = np.repeat(np.arange(len(A)), cnt)
        start = np.repeat(np.cumsum(cnt) - cnt, cnt)
        r = np.arange(len(tri)) - start
        sy, sz = span[tri, 1], span[tri, 2]
        ix = lo[tri, 0] + r // (sy * sz)
        iy = lo[tri, 1] + (r // sz) % sy
        iz = lo[tri, 2] + r % sz
        keys = self.key(np.stack([ix, iy, iz], axis=1), sid[tri])
        packed = np.sort(keys * len(A) + tri if len(A) else keys)   # by cell, then triangle: one sort of plain integers
        self.keys, self.tri = (packed // len(A), packed % len(A)) if len(A) else (keys, tri)
        self.lo, self.hi = lo, hi                         # each triangle's cells (inflated), for telling what changed

    def key(self, ijk, sid):
        d = self.dims
        q = ijk - self.origin
        inside = np.all((q >= 0) & (q < d), axis=1)
        k = ((sid.astype(np.int64) * d[0] + q[:, 0]) * d[1] + q[:, 1]) * d[2] + q[:, 2]
        return np.where(inside, k, -1)

    def cell_ijk(self, X):
        return np.floor(X / CELL).astype(np.int64)

    def candidates(self, ray, X, sid):
        """(ray index, triangle index) for every triangle in the cell of each point X[i] (ray[i] owns X[i])."""
        k = self.key(self.cell_ijk(X), sid)
        a = np.searchsorted(self.keys, k, "left")
        b = np.searchsorted(self.keys, k, "right")
        cnt = np.where(k >= 0, b - a, 0)
        tot = int(cnt.sum())
        if not tot:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
        start = np.repeat(a - (np.cumsum(cnt) - cnt), cnt)
        return np.repeat(ray, cnt), self.tri[start + np.arange(tot)]


def _cast(O, D, sid, tris, grid, cap, skip=None):
    """Nearest hit along each ray up to `cap`: (t, hit triangle, last step marched). NaN/-1 where there is none.

    A ray is marched one cell at a time; after step k every crossing with t <= (k + ½)·CELL has been seen, so a ray
    stops as soon as its best hit is that close."""
    A, E1, E2, TN = tris
    n = len(O)
    best = np.full(n, np.inf)
    btri = np.full(n, -1, dtype=np.int64)
    kend = np.zeros(n, dtype=np.int64)
    active = np.arange(n) if skip is None else np.flatnonzero(~skip)
    steps = int(math.ceil(cap / CELL)) + 1
    for k in range(steps + 1):
        if not len(active):
            break
        X = O[active] + D[active] * (k * CELL)
        r, j = grid.candidates(active, X, sid[active])
        kend[active] = k
        if len(r):
            d, o = D[r], O[r]
            p = np.cross(d, E2[j])
            det = np.einsum("ij,ij->i", E1[j], p)
            ok = np.abs(det) > 1e-14
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            tv = o - A[j]
            u = np.einsum("ij,ij->i", tv, p) * inv
            q = np.cross(tv, E1[j])
            v = np.einsum("ij,ij->i", d, q) * inv
            t = np.einsum("ij,ij->i", E2[j], q) * inv
            ok &= (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > EPS_T) & (t <= cap)
            if ok.any():
                r, j, t = r[ok], j[ok], t[ok]
                prev = best.copy()
                np.minimum.at(best, r, t)                   # per ray: the nearest; ties go to the lowest triangle index
                at = t == best[r]
                big = np.iinfo(np.int64).max
                bt = np.where((btri >= 0) & (best == prev), btri, big)
                np.minimum.at(bt, r[at], j[at])
                btri = np.where(bt == big, -1, bt)
        done = best[active] <= (k + 0.5) * CELL
        active = active[~done]
    hit = btri >= 0
    opposed = np.full(n, -1.0)
    opposed[hit] = np.einsum("ij,ij->i", TN[btri[hit]], D[hit])        # D = −n: −(m·n) = m·D
    wall = hit & (opposed >= WALL_PARALLEL)
    t = np.where(wall, best + 1e-4, np.nan)            # from the surface point, not the origin nudged inside it
    return t, np.where(wall, btri, -1), kend, opposed


class ThicknessField:
    """Per-sample wall thickness of one built model. Arrays (one row per sample):
    S (origin, on the surface), N (outward normal), t (mm, NaN = no opposing wall within the cap), to (hit point),
    face (index into model["faces"]), area (surface each sample stands for, mm²), level (0 coarse, 1 fine)."""

    def __init__(self):
        self.meta = {}
        self.memo = {}

    # ---- building ---------------------------------------------------------------------------------------------
    @classmethod
    def build(cls, model, floor: float, base: "ThicknessField | None" = None) -> "ThicknessField":
        self = cls()
        faces = model["faces"]
        exempt = set(getattr(model.get("recipe"), "wall_exempt", ()) or ())
        Ps, Ts, fo, off = [], [], [], 0
        for i, f in enumerate(faces):
            P = np.asarray(f["P"], dtype=np.float64)
            T = np.asarray(f["T"], dtype=np.int64)
            Ps.append(P)
            Ts.append(T + off)
            fo.append(np.full(len(P), i, dtype=np.int64))
            off += len(P)
        P0 = np.concatenate(Ps) if Ps else np.zeros((0, 3))
        T0 = np.concatenate(Ts) if Ts else np.zeros((0, 3), dtype=np.int64)
        face_v0 = np.concatenate(fo) if fo else np.zeros(0, dtype=np.int64)
        face_t0 = face_v0[T0[:, 0]] if len(T0) else np.zeros(0, dtype=np.int64)
        Pc, Tc, parent = _refine(P0, T0, H_COARSE)
        face_t = face_t0[parent]
        face_v = np.full(len(Pc), -1, dtype=np.int64)
        face_v[:len(P0)] = face_v0
        for k in range(3):
            face_v[Tc[:, k]] = face_t                    # a new vertex belongs to the face of the triangles it splits
        solid_of_face = _solid_of_face(model)
        sid_t = solid_of_face[face_t]
        A, B, C = Pc[Tc[:, 0]], Pc[Tc[:, 1]], Pc[Tc[:, 2]]
        E1, E2 = B - A, C - A
        TN = np.cross(E1, E2)
        TN /= np.maximum(np.linalg.norm(TN, axis=1, keepdims=True), 1e-300)
        tris = (A, E1, E2, TN)
        grid = _Grid(A, B, C, sid_t)
        tri_hash = _rows_hash(A, B, C, sid_t.astype(np.float64)[:, None])
        bb = np.array(model["bbox"], dtype=np.float64)
        diag = float(np.linalg.norm(bb[1] - bb[0])) if bb.size == 6 else CAP
        feats = [f["feature"] for f in faces]
        skip_face = np.array([ft in exempt for ft in feats] + [False], dtype=bool)

        self._tri_hash_now = tri_hash
        dirty = None
        if base is not None and base.meta.get("tol") == model.get("tol"):
            dirty = _dirty_cells(base, tri_hash, grid)

        # coarse: every vertex, long edges split to H_COARSE
        S, N, area, used = _vertex_normals_and_samples(Pc, Tc)
        sid_v = solid_of_face[np.maximum(face_v, 0)]
        skip = ~used | skip_face[face_v]
        cap = CAP
        t, tri, kend, opp = self._cast_reusing(S, N, sid_v, tris, grid, cap, skip, base, dirty)
        if not np.isfinite(t).any() and diag > cap:     # nothing within the cap: a chunky part; look across it
            cap = diag + CELL
            t, tri, kend, opp = self._cast_reusing(S, N, sid_v, tris, grid, cap, skip, None, None)
        # fine: split again wherever a corner is under twice the floor
        h_fine = max(0.2, min(0.5, floor / 2))
        # (a wall of constant thickness is already measured: only where the corners disagree, or one sees no wall, is
        # there a minimum between them to find)
        tv = np.where(np.isfinite(t), t, np.inf)
        tc = tv[Tc]
        lo_c, hi_c = tc.min(axis=1), tc.max(axis=1)
        with np.errstate(invalid="ignore"):
            flag = (lo_c < 2 * floor) & ((hi_c == np.inf) | (hi_c - lo_c > SPREAD))
        level = np.zeros(len(Pc), dtype=np.int8)
        Tm, V = Tc, Pc
        if flag.any():
            Pf, Tf, _par = _refine(Pc, Tc[flag], h_fine)
            nf = len(Pf) - len(Pc)
            if nf:
                Tm = np.concatenate([Tc[~flag], Tf])
                ft = face_t[flag][_par]
                fv = np.concatenate([face_v, np.full(nf, -1, dtype=np.int64)])
                for k in range(3):
                    fv[Tf[:, k]] = np.where(fv[Tf[:, k]] < 0, ft, fv[Tf[:, k]])
                face_v, V = fv, Pf
                S2, N2, area2, used2 = _vertex_normals_and_samples(Pf, Tm)
                new = slice(len(Pc), len(Pf))
                sid_n = solid_of_face[np.maximum(face_v[new], 0)]
                skip_n = ~used2[new] | skip_face[face_v[new]]
                t2, tri2, kend2, opp2 = self._cast_reusing(S2[new], N2[new], sid_n, tris, grid, cap, skip_n, base, dirty)
                S = np.concatenate([S, S2[new]])
                N = np.concatenate([N, N2[new]])
                area = area2                              # every sample's share of the final mesh
                t, tri = np.concatenate([t, t2]), np.concatenate([tri, tri2])
                kend, opp = np.concatenate([kend, kend2]), np.concatenate([opp, opp2])
                level = np.concatenate([level, np.ones(nf, dtype=np.int8)])
        to = np.full_like(S, np.nan)
        ok = np.isfinite(t)
        to[ok] = S[ok] - N[ok] * t[ok, None]
        self.S, self.N, self.t, self.to, self.face, self.area, self.level = S, N, t, to, face_v, area, level
        self.kend, self.opposed = kend, opp
        self.T, self.V, self.Tc, self.hit = Tm, V, Tc, tri
        self.hit_hash = np.where(tri >= 0, tri_hash[np.maximum(tri, 0)], np.uint64(0))
        self.tri_hash = tri_hash
        self.tri_lo, self.tri_hi = grid.lo.astype(np.int32), grid.hi.astype(np.int32)
        self.sample_hash = _rows_hash(S, N)
        self.grid = None                                 # the cell index is rebuilt for the next solid, not kept
        self.features = feats
        self.meta = {"version": VERSION, "tol": model.get("tol"), "floor": float(floor), "cap": float(cap),
                     "h_coarse": H_COARSE, "h_fine": h_fine, "cell": CELL, "samples": int(len(S)),
                     "triangles": int(len(Tc)), "reused": int(self._reused)}
        return self

    def _cast_reusing(self, S, N, sid, tris, grid, cap, skip, base, dirty):
        O = S - N * 1e-4
        D = -N
        if not hasattr(self, "_reused"):
            self._reused = 0
        keep = None
        if base is not None and dirty is not None and base.meta.get("cap") == cap:
            keep = _reusable(base, S, N, dirty)
        if keep is None:
            t, tri, kend, opp = _cast(O, D, sid, tris, grid, cap, skip=skip)
            return t, tri, kend, opp
        hit_base, idx = keep
        todo = skip | hit_base
        t, tri, kend, opp = _cast(O, D, sid, tris, grid, cap, skip=todo)
        use = hit_base & ~skip
        t[use], kend[use], opp[use] = base.t[idx[use]], base.kend[idx[use]], base.opposed[idx[use]]
        hh = base.hit_hash[idx[use]]                     # the hit triangle, found again in this mesh by its hash
        th_ = getattr(self, "_tri_lookup", None)
        if th_ is None:
            o = np.argsort(self._tri_hash_now, kind="stable")
            th_ = self._tri_lookup = (self._tri_hash_now[o], o)
        p = np.minimum(np.searchsorted(th_[0], hh), max(len(o := th_[1]) - 1, 0))
        tri[use] = np.where((hh != 0) & (th_[0][p] == hh), o[p], -1)
        self._reused += int(use.sum())
        return t, tri, kend, opp

    # ---- regions ----------------------------------------------------------------------------------------------
    def regions(self, model, floor: float | None = None, upto: float | None = None) -> dict:
        floor = float(self.meta["floor"] if floor is None else floor)
        upto = float(1.5 * floor if upto is None else upto)
        memo = f"{floor:.4f}/{upto:.4f}"
        if memo in self.memo:
            return self.memo[memo]
        from . import analysis
        inter_for = analysis.wall_intersectors(model)
        faces = model["faces"]
        t = self.t
        thin = np.flatnonzero(np.isfinite(t) & (t < upto))
        regions = []
        if len(thin):
            lab = _cluster(self, thin, link=max(2.5 * self.meta["h_fine"], 1.0))
            for g in np.unique(lab):
                members = thin[lab == g]
                regions.append(self._region(members, model, faces, inter_for, floor, upto))
        regions = [r for r in regions if r is not None]
        regions.sort(key=lambda r: (r["min_mm"], r["at"]))
        thinnest = None
        if regions:
            r0 = regions[0]
            thinnest = {"t": r0["min_mm"], "at": r0["at"], "to": r0["to"], "feature": r0["feature"], "kind": r0["kind"]}
        else:                                            # nothing under `upto`: the thinnest sample the B-rep confirms
            fin = np.isfinite(t)
            clear = fin & (t >= upto) & (self.opposed >= WALL_PARALLEL + 0.01)   # not on the 30° border the B-rep may refuse
            ok = np.flatnonzero(clear) if clear.any() else np.flatnonzero(fin)
            if len(ok):
                order = ok[np.lexsort((ok, t[ok]))]
                for chunk in range(0, min(len(order), FALLBACK_RAYS), ARBITERS):
                    b = self._arbitrate(order[chunk:chunk + ARBITERS], model, faces, inter_for)
                    if b is not None:
                        thinnest = {"t": b["t"], "at": b["at"], "to": b["to"], "feature": faces[b["face"]]["feature"]}
                        break
                if thinnest is None:                     # the B-rep found no wall at the mesh's thinnest: say what the mesh saw
                    i = int(order[0])
                    thinnest = {"t": round(float(t[i]), 4), "at": _pt(self.S[i]), "to": _pt(self.to[i]),
                                "feature": faces[int(self.face[i])]["feature"], "evidence": "mesh"}
        out = {"version": VERSION, "evidence": "computed", "floor_mm": floor, "upto_mm": upto,
               "cap_mm": self.meta["cap"], "samples": self.meta["samples"],
               "samples_with_wall": int(np.isfinite(t).sum()),
               "regions": regions, "thinnest": thinnest,
               "method": (f"Every surface vertex (edges at most {self.meta['h_coarse']:g} mm, "
                          f"{self.meta['h_fine']:g} mm where under {2 * floor:.2f} mm) casts the wall ray on the mesh; "
                          f"each region's minimum is the B-rep ray from its {ARBITERS} thinnest samples.")}
        self.memo[memo] = out
        return out

    def _arbitrate(self, idx, model, faces, inter_for):
        from build123d import Vector
        from . import analysis
        best = None
        for i in idx:
            i = int(i)
            fi = int(self.face[i])
            if fi < 0:
                continue
            face = faces[fi]["face"]
            p = _on_face(face, self.S[i])               # the sample is on a triangle; the ray starts on the face itself
            try:
                n = face.normal_at(Vector(*p))
                n = (n.X, n.Y, n.Z)
            except Exception:
                n = tuple(float(x) for x in self.N[i])
            try:
                hit = analysis.wall_hit(inter_for(face), p, n, want_face=True)
            except Exception:
                hit = None
            if hit is None:
                continue
            w, q, hf = hit
            w += 1e-4                                    # wall_hit measures from 1e-4 inside; from the surface point
            if best is None or w < best["t"] - 1e-12:
                best = {"t": round(float(w), 4), "at": _pt(p), "to": _pt(q), "face": fi, "hit_face": hf, "n": n}
        return best

    def _region(self, members, model, faces, inter_for, floor, upto):
        t = self.t[members]
        order = members[np.lexsort((members, t))]
        b = self._arbitrate(order[:ARBITERS], model, faces, inter_for)
        if b is None or b["t"] >= upto:
            return None                                  # the B-rep does not see a wall this thin here
        area = float(self.area[members].sum())
        feats = {}
        for i in members:
            ft = faces[int(self.face[i])]["feature"]
            feats[ft] = feats.get(ft, 0.0) + float(self.area[i])
        lo, hi = self.S[members].min(axis=0), self.S[members].max(axis=0)
        kind = _kind(b, faces, float((hi - lo).max()), floor)
        return {"feature": faces[b["face"]]["feature"], "features": sorted(feats, key=lambda k: (-feats[k], k)),
                "kind": kind, "min_mm": b["t"], "area_mm2": round(area, 3), "samples": int(len(members)),
                "at": b["at"], "to": b["to"], "bbox": [_pt(lo), _pt(hi)],
                "mesh_min_mm": round(float(t.min()), 4)}

    # ---- disk ---------------------------------------------------------------------------------------------------
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, S=self.S, N=self.N.astype(np.float32), t=self.t, to=self.to, face=self.face, area=self.area, level=self.level,
                 kend=self.kend.astype(np.int32), opposed=self.opposed.astype(np.float32),
                 tri_hash=self.tri_hash, T=self.T.astype(np.int32), V=self.V.astype(np.float32),
                 Tc=self.Tc.astype(np.int32), hit=self.hit.astype(np.int32), hit_hash=self.hit_hash,
                 tri_lo=self.tri_lo, tri_hi=self.tri_hi, sample_hash=self.sample_hash, meta=np.array(json.dumps(self.meta)), memo=np.array(json.dumps(self.memo)),
                 features=np.array(json.dumps(self.features)))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "ThicknessField | None":
        try:
            z = np.load(path, allow_pickle=False)
            self = cls()
            self.meta = json.loads(str(z["meta"]))
            if self.meta.get("version") != VERSION:
                return None
            for k in ("S", "N", "t", "to", "face", "area", "level", "kend", "opposed", "tri_hash", "T", "V", "Tc", "hit",
                      "hit_hash", "tri_lo", "tri_hi", "sample_hash"):
                setattr(self, k, z[k])
            for k in ("kend", "T", "Tc", "hit"):
                setattr(self, k, getattr(self, k).astype(np.int64))
            self.memo = json.loads(str(z["memo"]))
            self.features = json.loads(str(z["features"]))
            self.grid = None
            return self
        except Exception:
            return None


def _on_face(face, p):
    """The point of a curved face nearest p (a triangle's point lies up to the tessellation tolerance inside it)."""
    try:
        if face.geom_type.name == "PLANE":
            return np.asarray(p, dtype=np.float64)
        from OCP.BRep import BRep_Tool
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.gp import gp_Pnt
        sa = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face.wrapped))
        q = sa.Value(sa.ValueOfUV(gp_Pnt(*map(float, p)), 1e-7))
        r = np.array([q.X(), q.Y(), q.Z()])
        return r if np.linalg.norm(r - p) < 0.2 else np.asarray(p, dtype=np.float64)
    except Exception:
        return np.asarray(p, dtype=np.float64)


def _pt(p):
    return [round(float(x), 4) for x in p]


def _solid_of_face(model) -> np.ndarray:
    """Index of the solid each face belongs to (a wall stays inside its own part: analysis.wall_intersectors)."""
    faces = model["faces"]
    out = np.zeros(len(faces) + 1, dtype=np.int64)
    try:
        solids = model["shape"].solids()
    except Exception:
        solids = []
    if len(solids) > 1:
        owner = {}
        for i, sol in enumerate(solids):
            for fc in sol.faces():
                owner[hash(fc.wrapped)] = i
        for i, f in enumerate(faces):
            out[i] = owner.get(hash(f["face"].wrapped), 0)
    return out


def _dirty_cells(base, tri_hash, grid):
    """Cells (i, j, k) where a triangle of the new mesh is not in the old one, or the other way round."""
    if getattr(base, "tri_lo", None) is None:
        return None
    new_set, old_set = np.unique(tri_hash), np.unique(base.tri_hash)
    gone = np.setdiff1d(old_set, new_set, assume_unique=True)
    came = np.setdiff1d(new_set, old_set, assume_unique=True)
    boxes = []
    if len(came):
        m = np.isin(tri_hash, came)
        boxes.append((grid.lo[m], grid.hi[m]))
    if len(gone):
        m = np.isin(base.tri_hash, gone)
        boxes.append((base.tri_lo[m].astype(np.int64), base.tri_hi[m].astype(np.int64)))
    cells = [_expand(lo, hi) for lo, hi in boxes]
    if not cells:
        return np.zeros((0, 3), dtype=np.int64)
    return np.unique(np.concatenate(cells), axis=0)


def _expand(lo, hi):
    span = hi - lo + 1
    cnt = span.prod(axis=1)
    tri = np.repeat(np.arange(len(lo)), cnt)
    r = np.arange(len(tri)) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    sy, sz = span[tri, 1], span[tri, 2]
    return np.stack([lo[tri, 0] + r // (sy * sz), lo[tri, 1] + (r // sz) % sy, lo[tri, 2] + r % sz], axis=1)


def _reusable(base, S, N, dirty):
    """(mask, index into base) of samples whose answer the base field already holds: the same origin and normal,
    and no cell the ray marched through holds a triangle that changed."""
    h_new = _rows_hash(S, N)
    h_old = base.sample_hash
    order = np.argsort(h_old, kind="stable")
    pos = np.searchsorted(h_old[order], h_new)
    pos = np.minimum(pos, len(order) - 1) if len(order) else pos
    if not len(order):
        return np.zeros(len(S), dtype=bool), np.zeros(len(S), dtype=np.int64)
    idx = order[pos]
    same = (h_old[idx] == h_new) & np.all(base.S[idx] == S, axis=1)        # same origin; the hash covers the normal
    if len(dirty) and same.any():
        dk = np.sort(((dirty[:, 0] * 1_000_003) + dirty[:, 1]) * 1_000_003 + dirty[:, 2])
        cand = np.flatnonzero(same)
        kmax = base.kend[idx[cand]]
        O, D = S[cand] - N[cand] * 1e-4, -N[cand]
        bad = np.zeros(len(cand), dtype=bool)
        for k in range(int(kmax.max()) + 1 if len(kmax) else 0):
            live = k <= kmax
            ijk = np.floor((O + D * (k * CELL)) / CELL).astype(np.int64)
            key = (ijk[:, 0] * 1_000_003 + ijk[:, 1]) * 1_000_003 + ijk[:, 2]
            p = np.minimum(np.searchsorted(dk, key), len(dk) - 1)
            bad |= live & (dk[p] == key)
        same[cand[bad]] = False
    return same, idx


def _cluster(f, thin, link: float) -> np.ndarray:
    """Connected components of the thin samples `thin`. Joined: corners of one triangle of the sampled mesh, samples at
    the same point on two faces (a B-rep edge), and a sample with the corners of the triangle its ray landed on (the
    two faces of one wall are one region); a ray that landed on no thin corner is joined to thin samples within `link`
    of where it landed."""
    n = len(thin)
    pos = np.full(len(f.t), -1, dtype=np.int64)
    pos[thin] = np.arange(n)
    a_l, b_l = [], []
    T = pos[f.T]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        ok = (T[:, i] >= 0) & (T[:, j] >= 0)
        a_l.append(T[ok, i])
        b_l.append(T[ok, j])
    q = np.round(f.V[thin] / 1e-5).astype(np.int64)                   # one point on two faces
    _u, w = np.unique(q, axis=0, return_inverse=True)
    w = w.reshape(-1)
    o = np.argsort(w, kind="stable")
    same = w[o][1:] == w[o][:-1]
    a_l.append(o[1:][same])
    b_l.append(o[:-1][same])
    hit = f.hit[thin]
    lonely = np.ones(n, dtype=bool)
    has = hit >= 0
    for k in range(3):
        c = np.full(n, -1, dtype=np.int64)
        c[has] = pos[f.Tc[hit[has], k]]
        ok = c >= 0
        a_l.append(np.flatnonzero(ok))
        b_l.append(c[ok])
        lonely &= ~ok
    li = np.flatnonzero(lonely & np.isfinite(f.t[thin]))
    if len(li):                                          # by distance: where the ray landed, to thin samples near it
        X = f.S[thin]
        cell = np.floor(X / link).astype(np.int64)
        key = (cell[:, 0] * 2_000_003 + cell[:, 1]) * 2_000_003 + cell[:, 2]
        order = np.argsort(key, kind="stable")
        ks = key[order]
        Y = f.to[thin][li]
        cy = np.floor(Y / link).astype(np.int64)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nk = ((cy[:, 0] + dx) * 2_000_003 + cy[:, 1] + dy) * 2_000_003 + cy[:, 2] + dz
                    lo = np.searchsorted(ks, nk, "left")
                    hi = np.searchsorted(ks, nk, "right")
                    cnt = hi - lo
                    tot = int(cnt.sum())
                    if not tot:
                        continue
                    i = np.repeat(np.arange(len(li)), cnt)
                    j = order[np.repeat(lo - (np.cumsum(cnt) - cnt), cnt) + np.arange(tot)]
                    keep = np.linalg.norm(Y[i] - X[j], axis=1) <= link
                    a_l.append(li[i[keep]])
                    b_l.append(j[keep])
    a, b = np.concatenate(a_l), np.concatenate(b_l)
    return _components(n, a, b)


def _components(n, a, b) -> np.ndarray:
    """Component label per node, numbered by each component's lowest node."""
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        g = coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n))
        _k, lab = connected_components(g, directed=False)
    except ImportError:                                  # plain union-find, the same components
        par = np.arange(n)

        def root(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for x, y in zip(a.tolist(), b.tolist()):
            rx, ry = root(x), root(y)
            if rx != ry:
                par[max(rx, ry)] = min(rx, ry)
        lab = np.array([root(x) for x in range(n)])
    first = np.full(n, n, dtype=np.int64)
    np.minimum.at(first, lab, np.arange(n))
    _u, comp = np.unique(first[lab], return_inverse=True)
    return comp.reshape(-1)


def _kind(b, faces, extent, floor) -> str:
    if extent < 2 * floor:
        return "sliver"
    from build123d import Face, Vector
    try:
        hf = Face(b["hit_face"])
        q = b["to"]
        m = hf.normal_at(Vector(*q))
        opposed = -(m.X * b["n"][0] + m.Y * b["n"][1] + m.Z * b["n"][2])
    except Exception:
        hf, opposed = None, 1.0
    if opposed >= PARALLEL_WALL:
        return "wall"
    start = faces[b["face"]]["face"]
    try:
        if hf is not None and (hf.wrapped.IsSame(start.wrapped) or any(
                e.wrapped.IsSame(o.wrapped) for e in start.edges() for o in hf.edges())):
            return "knife_edge"
    except Exception:
        pass
    return "crest"


# ---- the API ------------------------------------------------------------------------------------------------------

def cache_dir() -> Path | None:
    """<data>/.cache/thickness, from the FORM_SOURCES the Studio sets for the kernel worker (<data>/.sources)."""
    d = os.environ.get("FORM_THICKNESS_CACHE")
    if d:
        return Path(d)
    s = os.environ.get("FORM_SOURCES")
    return Path(s).parent / ".cache" / "thickness" if s else None


def _safe(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(key))[:120]


def model_of_shape(shape, tol: float = 0.05, feature: str = "body") -> dict:
    """A kernel-style model of a bare build123d solid (one feature), for measuring a shape that is not a design."""
    from .kernel import _tessellate
    faces = []
    for face in shape.faces():
        P, T = _tessellate(face, tol)
        if not len(T):
            continue
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        faces.append({"feature": feature, "P": P, "T": np.asarray(T, dtype=np.int64), "face": face,
                      "area": float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)})
    bb = shape.bounding_box()
    return {"recipe": None, "shape": shape, "faces": faces, "tol": tol,
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def field(model, key: str | None, floor: float, directory: Path | None = None, base=None) -> ThicknessField:
    """The field of a built model: from memory, from <directory>/<key>.npz, or measured (reusing `base`, else the
    last field measured in this process, where nothing changed)."""
    tol = model.get("tol")
    mk = (key, tol, round(float(floor), 4)) if key is not None else None
    if mk is not None and mk in _mem:
        return _mem[mk]
    path = (directory / f"{_safe(key)}-{_floor_code(floor, tol)}.npz") if (directory is not None and key is not None) else None
    if path is not None and path.is_file():
        f = ThicknessField.load(path)
        if f is not None and f.meta.get("tol") == tol and abs(f.meta.get("floor", -1) - floor) < 1e-9:
            _remember(mk, f)
            return f
    if base is None and _mem:
        cand = [v for v in _mem.values() if v.meta.get("tol") == tol and abs(v.meta.get("floor", -1) - floor) < 1e-9]
        base = cand[-1] if cand else None
    f = ThicknessField.build(model, floor, base=base)
    if mk is not None:
        _remember(mk, f)
    if path is not None:
        try:
            f.save(path)
        except OSError:
            pass
    return f


def _floor_code(floor, tol) -> str:
    return f"f{int(round(floor * 1000))}-t{int(round((tol or 0) * 1000))}"


def _remember(mk, f):
    if mk is None:
        return
    _mem.pop(mk, None)
    _mem[mk] = f
    while len(_mem) > 4:
        _mem.pop(next(iter(_mem)))


def regions(key_or_shape, floor: float, *, model=None, upto: float | None = None, directory: Path | None = None,
            tol: float = 0.05) -> dict:
    """Every region of the solid thinner than `upto` (default 1.5 × floor), thinnest first, and the thinnest wall.

    key_or_shape: a geometry key the kernel has built (its model is taken from the kernel's cache), a kernel model
    dict, or a build123d shape. Cached by key: a second call for the same key and floor reads the answer back."""
    key = None
    if isinstance(key_or_shape, str):
        key = key_or_shape
        if directory is None:
            directory = cache_dir()
        if model is None:
            path = (directory / f"{_safe(key)}-{_floor_code(floor, tol)}.npz") if directory is not None else None
            f = _mem.get((key, tol, round(float(floor), 4)))
            if f is None and path is not None and path.is_file():
                f = ThicknessField.load(path)
            up = float(1.5 * floor if upto is None else upto)
            if f is not None and f"{float(floor):.4f}/{up:.4f}" in f.memo:
                return f.memo[f"{float(floor):.4f}/{up:.4f}"]
            from . import kernel
            model = kernel._cache.get((key, tol)) or next((m for (k, _t), m in kernel._cache.items() if k == key), None)
            if model is None:
                raise KeyError(f"No built model for {key}: build it first (kernel._get).")
    elif isinstance(key_or_shape, dict):
        model = key_or_shape
    else:
        model = model_of_shape(key_or_shape, tol)
    f = field(model, key, floor, directory)
    before = len(f.memo)
    out = f.regions(model, floor, upto)
    if len(f.memo) != before and key is not None and directory is not None:
        try:
            f.save(directory / f"{_safe(key)}-{_floor_code(floor, model.get('tol'))}.npz")
        except OSError:
            pass
    return out


def sentence(res: dict, limit: int = 6) -> str:
    """The regions in one line for a check's detail: where each thin place is and how thin."""
    regs = res.get("regions") or []
    if not regs:
        return ""
    names = {"wall": "wall", "knife_edge": "knife edge", "crest": "crest", "sliver": "sliver"}
    parts = [f"{r['min_mm']:.2f} mm {names.get(r['kind'], r['kind'])} on {r['feature']}" for r in regs[:limit]]
    more = f" and {len(regs) - limit} more" if len(regs) > limit else ""
    return (f" {len(regs)} region{'s' if len(regs) != 1 else ''} under {res['upto_mm']:.2f} mm: "
            + "; ".join(parts) + more + ".")
