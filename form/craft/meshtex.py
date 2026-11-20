"""Mesh textures: fine surface displacement for STL, GLB and renders, with numpy only (no kernel needed).

A design declares them; Form Studio applies them to the triangle mesh it exports and draws, never to the CAD solid:

    from form.craft import MeshTexture
    class Design(Recipe):
        def mesh_texture(self, v):
            return [MeshTexture("cells", amplitude=0.35, scale=4.0, features=["shell"])]

Every export and view of such a design carries LABEL ("mesh texture; STEP carries the smooth body"). The STEP is the
smooth B-rep; the STL, OBJ, GLB and the renders are the textured mesh.

How it works:
  1. the solid's tessellation (one mesh, edges shared between faces, every triangle tagged with its feature) is welded;
  2. edges longer than max_edge inside the textured features are split (watertight, decided per edge) until the mesh
     is fine enough to carry the pattern, up to a triangle budget;
  3. each vertex moves along its normal by amplitude x pattern(x) x weight, where the weight fades to 0 within
     edge_falloff of the region's border and of sharp creases, so seams stay closed and edges stay crisp.

Kinds (pattern values in 0..1, 1 = full amplitude):
  noise      fractal value noise (sand-cast, stone)            scale = wavelength
  cells      raised Voronoi tiles with grooves (pebble, carbon-like, reptile)   scale = cell size
  grain      leather grain: fine cells broken by noise          scale = grain size
  hex        hexagon tiles, projected triplanar                 scale = tile size
  weave      2x2 twill of rounded tows (a carbon-fibre look), triplanar   scale = tow width
  knurl      diamond knurl around `axis`                        scale = pitch
  ribs       ribs along `axis` (rings) or around it (flutes: direction="around")   scale = pitch
  heightmap  a grayscale image (PNG/JPEG path in `image`), projection planar | cylindrical | spherical
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

LABEL = "mesh texture; STEP carries the smooth body"
KINDS = ("noise", "cells", "grain", "hex", "weave", "knurl", "ribs", "heightmap")
EXPORT_BUDGET = 2_400_000          # triangles in an exported textured mesh
VIEW_BUDGET = 700_000              # triangles in the viewer / renders


@dataclass
class MeshTexture:
    kind: str
    amplitude: float = 0.3                       # mm along the normal; negative presses into the surface
    scale: float = 4.0                           # mm: cell size, wavelength or pitch
    features: tuple = ()                         # feature ids it covers; () = every feature
    seed: int = 0
    octaves: int = 3
    projection: str = "triplanar"                # heightmap / hex: planar | cylindrical | spherical | triplanar
    axis: tuple = (0.0, 0.0, 1.0)
    center: tuple = (0.0, 0.0, 0.0)
    direction: str = "along"                     # ribs: "along" the axis (rings) or "around" it (flutes)
    image: str = ""
    max_edge: float | None = None                # triangle edge before displacing (default scale / 4)
    edge_falloff: float = 1.5                    # mm over which it fades out at borders and creases
    crease_deg: float = 35.0
    groove: float = 0.18                         # cells / hex: groove width as a fraction of the cell
    facing: str = "any"                          # "out": only triangles facing away from the region's centre (a
                                                 # shell's outside, not its inside)
    extra: dict = field(default_factory=dict)

    def validate(self) -> "MeshTexture":
        from ._common import need, num
        need(self.kind in KINDS, f"MeshTexture: unknown kind {self.kind!r}", "Use one of: " + ", ".join(KINDS), ["kind"])
        num(self.amplitude, "amplitude", lo=-5, hi=5)
        num(self.scale, "scale", lo=0.2, hi=500)
        need(abs(self.amplitude) < self.scale * 2, "MeshTexture: amplitude is larger than twice the scale",
             "Make the texture shallower or larger.", ["amplitude", "scale"])
        if self.kind == "heightmap":
            need(bool(self.image) and Path(self.image).is_file(), f"MeshTexture: heightmap image not found: {self.image!r}",
                 "Give the absolute path of a grayscale PNG or JPEG.", ["image"])
        self.features = tuple(self.features or ())
        return self

    def public(self) -> dict:
        d = asdict(self)
        d["features"] = list(self.features)
        d["label"] = LABEL
        return d


# ---- mesh plumbing ----------------------------------------------------------------------------------------------

def weld(P: np.ndarray, T: np.ndarray, tol: float = 1e-4):
    q = np.round(P / tol).astype(np.int64)
    _, idx, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    F = inv[T]
    keep = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0])
    return P[idx].astype(np.float64), F, keep


def face_normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    return n


def vertex_normals(V, F):
    fn = face_normals(V, F)
    vn = np.zeros_like(V)
    for i in range(3):
        np.add.at(vn, F[:, i], fn)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return vn / ln


def _edges(F):
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    return np.sort(E, axis=1)


def split_long_edges(V, F, tag, active, max_edge: float, budget: int):
    """Split every edge longer than max_edge that borders an active triangle (midpoint), repeatedly, keeping the mesh
    watertight (the decision is per edge, so both neighbours split it the same way). tag and active ride along with
    each child triangle. Stops early at the triangle budget. Returns V, F, tag, active, reached (bool)."""
    for _ in range(24):
        n = len(F)
        E = _edges(F)
        key = E[:, 0].astype(np.int64) * len(V) + E[:, 1]
        uk, inv = np.unique(key, return_inverse=True)
        ea, eb = uk // len(V), uk % len(V)
        L = np.linalg.norm(V[ea] - V[eb], axis=1)
        act_e = np.zeros(len(uk), dtype=bool)
        np.logical_or.at(act_e, inv, np.tile(active, 3))
        split = act_e & (L > max_edge)
        if not split.any():
            return V, F, tag, active, True
        est = n + 3 * int(np.bincount(inv, minlength=len(uk))[split].sum() // 2 + split.sum())
        if est > budget:
            return V, F, tag, active, False
        mid_id = -np.ones(len(uk), dtype=np.int64)
        mid_id[split] = len(V) + np.arange(split.sum())
        V = np.concatenate([V, (V[ea[split]] + V[eb[split]]) / 2])
        m = mid_id[inv].reshape(3, n).T                           # per triangle: midpoint of e0 (v0v1), e1 (v1v2), e2 (v2v0)
        code = (m[:, 0] >= 0) * 1 + (m[:, 1] >= 0) * 2 + (m[:, 2] >= 0) * 4
        v0, v1, v2 = F[:, 0], F[:, 1], F[:, 2]
        m0, m1, m2 = m[:, 0], m[:, 1], m[:, 2]
        out, otag, oact = [], [], []

        def add(sel, *tris):
            for t in tris:
                out.append(np.stack([x[sel] for x in t], axis=1))
                otag.append(tag[sel])
                oact.append(active[sel])

        s = code == 0; add(s, (v0, v1, v2))
        s = code == 1; add(s, (v0, m0, v2), (m0, v1, v2))
        s = code == 2; add(s, (v0, v1, m1), (v0, m1, v2))
        s = code == 4; add(s, (v0, v1, m2), (m2, v1, v2))
        s = code == 3; add(s, (m0, v1, m1), (v0, m0, m1), (v0, m1, v2))
        s = code == 6; add(s, (m1, v2, m2), (v0, v1, m1), (v0, m1, m2))
        s = code == 5; add(s, (v0, m0, m2), (m0, v1, v2), (m0, v2, m2))
        s = code == 7; add(s, (v0, m0, m2), (m0, v1, m1), (m2, m1, v2), (m0, m1, m2))
        F = np.concatenate(out).astype(np.int64)
        tag, active = np.concatenate(otag), np.concatenate(oact)
    return V, F, tag, active, True


# ---- patterns -----------------------------------------------------------------------------------------------------

def _hash(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663) ^ (iz.astype(np.int64) * 83492791) \
        ^ np.int64(seed * 2654435761 % (1 << 31))
    h = h.astype(np.uint64)
    h ^= h >> np.uint64(13)
    h *= np.uint64(0x5BD1E995)
    h ^= h >> np.uint64(15)
    return (h & np.uint64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def value_noise(X, seed=0):
    i = np.floor(X).astype(np.int64)
    f = X - i
    u = f * f * (3 - 2 * f)
    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (u[:, 0] if dx else 1 - u[:, 0]) * (u[:, 1] if dy else 1 - u[:, 1]) * (u[:, 2] if dz else 1 - u[:, 2])
                out = out + w * _hash(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return out


def fbm(X, octaves=3, seed=0):
    tot, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        tot = tot + amp * value_noise(X * (2 ** o), seed + 17 * o)
        norm += amp
        amp *= 0.5
    return tot / norm


def worley(X, seed=0):
    """F1 and F2 distances (in cell units) to jittered feature points, one per unit cell."""
    i = np.floor(X).astype(np.int64)
    F1 = np.full(len(X), 9.0)
    F2 = np.full(len(X), 9.0)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = i + np.array([dx, dy, dz])
                fp = c + np.stack([_hash(c[:, 0], c[:, 1], c[:, 2], seed + k) * 0.8 + 0.1 for k in (1, 2, 3)], axis=1)
                d = np.linalg.norm(X - fp, axis=1)
                F2 = np.where(d < F1, F1, np.minimum(F2, d))
                F1 = np.minimum(F1, d)
    return F1, F2


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def _hex_height(u, v, s, groove):
    """Plateau hex tiles of size s (flat to flat) with grooves; 1 on a tile, 0 in the groove."""
    a, b = u / s, v / s
    r3 = math.sqrt(3)
    # two candidate lattices; nearest hex centre
    gx, gy = a, b / (r3 / 2)
    cands = []
    for ox, oy in ((0, 0), (0.5, 1)):
        ry = np.round((gy - oy) / 2) * 2 + oy
        rx = np.round(gx - ox) + ox
        cands.append(np.stack([rx, ry * (r3 / 2)], 1))
    pts = np.stack([a, b], 1)
    d0 = np.linalg.norm(pts - cands[0], axis=1)
    d1 = np.linalg.norm(pts - cands[1], axis=1)
    c = np.where((d0 <= d1)[:, None], cands[0], cands[1])
    p = np.abs(pts - c)
    hexd = np.maximum(p[:, 0] * 1.0, p[:, 0] * 0.5 + p[:, 1] * (r3 / 2))   # 0.5 at the tile edge (flat to flat = 1)
    return _smooth((0.5 - hexd) / max(groove, 1e-3))


def _weave_height(u, v, s):
    """2x2 twill: tows s wide, each passing over two and under two; rounded tow cross-section."""
    a, b = u / s, v / s
    cu, cv = np.floor(a), np.floor(b)
    fu, fv = a - cu, b - cv
    over_u = (np.floor((cu + cv) / 2) % 2) == 0             # which direction's tow is on top in this cell
    prof = lambda t: np.sqrt(np.clip(np.sin(np.pi * t), 0, 1))
    top = np.where(over_u, prof(fv), prof(fu))
    return 0.25 + 0.75 * top


def _frame(axis, center):
    ax = np.asarray(axis, float)
    ax = ax / (np.linalg.norm(ax) or 1)
    ref = np.array([1.0, 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(ax, ref)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    return ax, e1, e2, np.asarray(center, float)


def pattern(spec: MeshTexture, V, N):
    s = float(spec.scale)
    if spec.kind == "noise":
        return _smooth((fbm(V / s, spec.octaves, spec.seed) - 0.25) / 0.5)
    if spec.kind in ("cells", "grain"):
        F1, F2 = worley(V / s, spec.seed)
        h = _smooth((F2 - F1) / max(spec.groove * 2, 1e-3))
        if spec.kind == "grain":
            h = 0.65 * h + 0.35 * fbm(V / (s * 0.45), 2, spec.seed + 5)
        return h
    ax, e1, e2, c = _frame(spec.axis, spec.center)
    R = V - c
    z = R @ ax
    rad = np.hypot(R @ e1, R @ e2)
    th = np.arctan2(R @ e2, R @ e1)
    if spec.kind in ("hex", "weave"):
        fn2 = _hex_height if spec.kind == "hex" else (lambda a, b, s_, g: _weave_height(a, b, s_))
        w = np.abs(N) ** 4
        w /= w.sum(1, keepdims=True) + 1e-12
        h = (w[:, 0] * fn2(V[:, 1], V[:, 2], s, spec.groove) + w[:, 1] * fn2(V[:, 0], V[:, 2], s, spec.groove)
             + w[:, 2] * fn2(V[:, 0], V[:, 1], s, spec.groove))
        return h
    rref = float(np.median(rad)) if len(rad) else 1.0
    arc = th * rref
    tri = lambda x: 1 - 2 * np.abs(x - np.floor(x) - 0.5)
    if spec.kind == "knurl":
        return _smooth(np.minimum(tri((arc + z) / s), tri((arc - z) / s)) * 1.6)
    if spec.kind == "ribs":
        x = z / s if spec.direction == "along" else arc / s
        return _smooth(1.6 * tri(x) - 0.3)
    if spec.kind == "heightmap":
        from PIL import Image
        img = np.asarray(Image.open(spec.image).convert("L"), dtype=np.float64) / 255.0
        H, W = img.shape
        if spec.projection == "cylindrical":
            u = (th / (2 * math.pi)) % 1.0
            lo, hi = z.min(), z.max()
            v = (z - lo) / max(hi - lo, 1e-9)
        elif spec.projection == "spherical":
            u = (th / (2 * math.pi)) % 1.0
            v = np.arccos(np.clip(z / np.maximum(np.linalg.norm(R, axis=1), 1e-9), -1, 1)) / math.pi
        else:
            u = ((R @ e1) / s) % 1.0
            v = ((R @ e2) / s) % 1.0
        x, y = u * (W - 1), (1 - v) * (H - 1)
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        x1, y1 = np.minimum(x0 + 1, W - 1), np.minimum(y0 + 1, H - 1)
        fx, fy = x - x0, y - y0
        return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy) + img[y1, x0] * (1 - fx) * fy
                + img[y1, x1] * fx * fy)
    raise ValueError(spec.kind)


# ---- applying ------------------------------------------------------------------------------------------------------

def _falloff(V, F, seeds: np.ndarray, radius: float, iters: int = 40):
    """Approximate distance (mm, along edges) from the seed vertices, capped at radius."""
    d = np.where(seeds, 0.0, radius)
    E = _edges(F)
    E = np.unique(E, axis=0)
    L = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    for _ in range(iters):
        nd = d.copy()
        np.minimum.at(nd, E[:, 0], d[E[:, 1]] + L)
        np.minimum.at(nd, E[:, 1], d[E[:, 0]] + L)
        nd = np.minimum(nd, radius)
        if np.array_equal(nd, d):
            break
        d = nd
    return d


def apply(P: np.ndarray, T: np.ndarray, tri_feature: list | np.ndarray, specs: list, budget: int = EXPORT_BUDGET):
    """Texture a feature-tagged triangle soup. P (n, 3) float, T (m, 3) int, tri_feature: the feature id of each
    triangle. Returns (V, F, tri_feature_array, info)."""
    specs = [s.validate() if isinstance(s, MeshTexture) else MeshTexture(**s).validate() for s in specs]
    names, tag = np.unique(np.asarray(tri_feature, dtype=object).astype(str), return_inverse=True)
    V, F, keep = weld(np.asarray(P, float), np.asarray(T, np.int64))
    F, tag = F[keep], tag[keep]
    info = {"label": LABEL, "textures": [s.public() for s in specs], "triangles_in": int(len(F))}
    for s in specs:
        cover = np.ones(len(names), bool) if not s.features else np.isin(names, list(s.features))
        active = cover[tag]
        if s.facing == "out" and active.any():
            tc = V[F].mean(axis=1)
            c = (tc[active].min(0) + tc[active].max(0)) / 2
            active &= np.einsum("ij,ij->i", face_normals(V, F), tc - c) > 0
        if not active.any():
            info.setdefault("unused", []).append(s.kind)
            continue
        me = s.max_edge or max(s.scale / 4.0, 0.08)
        V, F, tag, active, reached = split_long_edges(V, F, tag, active, me, budget)
        if not reached:
            info.setdefault("coarser", []).append(f"{s.kind}: triangle budget {budget} reached before {me:.2f} mm edges")
        Nv = vertex_normals(V, F)
        fn = face_normals(V, F)
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
        # border seeds: vertices touching an uncovered triangle, and crease vertices
        inside = np.zeros(len(V), bool)
        outside = np.zeros(len(V), bool)
        for i in range(3):
            np.logical_or.at(inside, F[:, i], active)
            np.logical_or.at(outside, F[:, i], ~active)
        crease = np.zeros(len(V), bool)
        cosc = math.cos(math.radians(s.crease_deg))
        for i in range(3):
            dev = np.einsum("ij,ij->i", Nv[F[:, i]], fn) < cosc
            np.logical_or.at(crease, F[:, i], dev)
        seeds = outside | crease
        d = _falloff(V, F, seeds, s.edge_falloff) if s.edge_falloff > 0 else np.where(seeds, 0.0, 1.0)
        w = _smooth(d / max(s.edge_falloff, 1e-9)) if s.edge_falloff > 0 else (~seeds).astype(float)
        w[~inside] = 0.0
        sel = w > 0
        h = np.zeros(len(V))
        h[sel] = pattern(s, V[sel], Nv[sel])
        V = V + Nv * (s.amplitude * h * w)[:, None]
    info["triangles_out"] = int(len(F))
    return V, F, names[tag], info


def apply_to_faces(faces: list[dict], specs: list, budget: int = EXPORT_BUDGET):
    """faces: the kernel's per-face meshes [{"feature", "P", "T"}, ...] (form/kernel.py)."""
    P, T, tf, off = [], [], [], 0
    for f in faces:
        P.append(f["P"])
        T.append(f["T"] + off)
        tf += [f["feature"]] * len(f["T"])
        off += len(f["P"])
    return apply(np.concatenate(P), np.concatenate(T), tf, specs, budget)


def write_stl(path, V, F, name: str = "Form Studio textured mesh") -> None:
    tri = V[F].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(F), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, tri
    head = (name + " - " + LABEL).encode("ascii", "replace")[:80].ljust(80, b" ")
    with open(path, "wb") as fh:
        fh.write(head)
        fh.write(np.uint32(len(F)).tobytes())
        fh.write(rec.tobytes())


def declared(recipe, values) -> list:
    """The MeshTexture list a recipe declares for these values ([] when none)."""
    fn = getattr(recipe, "mesh_texture", None)
    if not callable(fn):
        return []
    out = fn(values) or []
    return [s if isinstance(s, MeshTexture) else MeshTexture(**s) for s in out]
