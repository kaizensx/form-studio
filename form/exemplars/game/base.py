"""Shared tools for the game exemplars: cage blocks in numpy, the opening model_mesh ops, and the design source.

A game exemplar starts as plain numpy blocks (boxes on chosen grid lines, lathed rings, quad spheres), each a closed,
outward-facing quad shell with its regions and crease edges. Kit.ops() turns them into the first model_mesh ops:
cage_new with every point and face, then name_region and crease by index. The indices are the ones Blender's runner
will use: it sorts points by position and faces by their points after every op (blender_ops.canonical), and
canonical() here sorts the same way, so the blocks are handed over already in that order. Every later op picks its
geometry by region, normal, box or angle, never by index.

design_source() writes the finished cage into a design (one literal per connected part, as
form.game.pipeline.cage_design_source does) and keeps the high-only bake source with it: each part carries the shells
of the high cage that belong to it, so game_asset bakes that detail while the LODs stay the low cage.
"""
from __future__ import annotations

import json
import math

import numpy as np

from ... import meshsource


# ---- blocks ----------------------------------------------------------------------------------------------------------

class Block:
    """One closed shell: V (n, 3), F (quads), creases [(a, b, weight)], regions {name: [face, ...]}."""

    def __init__(self, V, F, creases=(), regions=None):
        self.V = np.asarray(V, float)
        self.F = [list(map(int, f)) for f in F]
        self.creases = [(int(a), int(b), float(w)) for a, b, w in creases]
        self.regions = {k: list(v) for k, v in (regions or {}).items()}

    def region(self, name, faces=None):
        """Name faces (all of them by default) as a region."""
        self.regions.setdefault(name, []).extend(range(len(self.F)) if faces is None else faces)
        return self

    def crease(self, pred, w=1.0):
        """Crease every edge whose two points satisfy pred(p, q)."""
        seen = {(min(a, b), max(a, b)) for a, b, _w in self.creases}
        for f in self.F:
            for a, b in zip(f, f[1:] + f[:1]):
                e = (min(a, b), max(a, b))
                if e not in seen and pred(self.V[a], self.V[b]):
                    seen.add(e)
                    self.creases.append((a, b, w))
        return self

    def map(self, fn):
        """Move every point: fn(V (n, 3)) -> V."""
        self.V = np.asarray(fn(self.V.copy()), float)
        return self

    def faces_where(self, pred) -> list[int]:
        """Faces whose centre satisfies pred(c)."""
        return [i for i, f in enumerate(self.F) if pred(self.V[f].mean(0))]

    def oriented(self):
        """Reverse every face if the shell's signed volume is negative (faces must face out)."""
        vol = 0.0
        for f in self.F:
            for k in range(1, len(f) - 1):
                vol += np.dot(self.V[f[0]], np.cross(self.V[f[k]], self.V[f[k + 1]]))
        if vol < 0:
            self.F = [f[::-1] for f in self.F]
        return self


def box(xs, ys, zs, crease=1.0) -> Block:
    """A box whose surface grid runs through the given coordinates on each axis, the 12 border edges creased."""
    xs, ys, zs = (np.asarray(a, float) for a in (xs, ys, zs))
    nx, ny, nz = len(xs) - 1, len(ys) - 1, len(zs) - 1
    ids, V = {}, []

    def pid(i, j, k):
        if (i, j, k) not in ids:
            ids[(i, j, k)] = len(V)
            V.append((xs[i], ys[j], zs[k]))
        return ids[(i, j, k)]
    F = []
    for i in range(nx):
        for j in range(ny):
            F.append([pid(i, j, 0), pid(i, j + 1, 0), pid(i + 1, j + 1, 0), pid(i + 1, j, 0)])
            F.append([pid(i, j, nz), pid(i + 1, j, nz), pid(i + 1, j + 1, nz), pid(i, j + 1, nz)])
    for i in range(nx):
        for k in range(nz):
            F.append([pid(i, 0, k), pid(i + 1, 0, k), pid(i + 1, 0, k + 1), pid(i, 0, k + 1)])
            F.append([pid(i, ny, k), pid(i, ny, k + 1), pid(i + 1, ny, k + 1), pid(i + 1, ny, k)])
    for j in range(ny):
        for k in range(nz):
            F.append([pid(0, j, k), pid(0, j, k + 1), pid(0, j + 1, k + 1), pid(0, j + 1, k)])
            F.append([pid(nx, j, k), pid(nx, j + 1, k), pid(nx, j + 1, k + 1), pid(nx, j, k + 1)])
    b = Block(V, F)
    if crease:
        inv = {v: k for k, v in ids.items()}
        on = lambda k: sum((k[0] in (0, nx), k[1] in (0, ny), k[2] in (0, nz))) >= 2
        b.crease(lambda p, q: False)
        seen = set()
        for f in F:
            for a, c in zip(f, f[1:] + f[:1]):
                e = (min(a, c), max(a, c))
                ka, kc = inv[a], inv[c]
                if e not in seen and on(ka) and on(kc) and sum(x != y for x, y in zip(ka, kc)) == 1:
                    # both ends on the border and the edge runs along a border line (not across a face)
                    axis = next(t for t in range(3) if ka[t] != kc[t])
                    lim = (nx, ny, nz)
                    others = [t for t in range(3) if t != axis]
                    if all(ka[t] in (0, lim[t]) for t in others):
                        seen.add(e)
                        b.creases.append((a, c, crease))
    return b.oriented()


def span(a, b, n) -> list[float]:
    return list(np.linspace(a, b, n + 1))


def quad_sphere(n: int, scale=(1, 1, 1), at=(0, 0, 0)) -> Block:
    from ...craft import subd
    V, F = subd.quad_sphere(n, 1.0)
    return Block(np.asarray(V) * np.asarray(scale, float) + np.asarray(at, float), F).oriented()


def lathe(profile, n: int, axis: str = "z", at=(0, 0, 0), phase: float = 0.0) -> Block:
    """A closed ring: the closed 2D profile [(r, h), ...] (r > 0) turned round the axis in n steps."""
    prof = np.asarray(profile, float)
    m = len(prof)
    V, F = [], []
    for s in range(n):
        t = 2 * math.pi * s / n + math.radians(phase)
        c, sn = math.cos(t), math.sin(t)
        for r, h in prof:
            if axis == "z":
                V.append((r * c, r * sn, h))
            elif axis == "y":
                V.append((r * c, h, r * sn))
            else:
                V.append((h, r * c, r * sn))
    for s in range(n):
        for k in range(m):
            a, b = s * m + k, s * m + (k + 1) % m
            c2, d = ((s + 1) % n) * m + (k + 1) % m, ((s + 1) % n) * m + k
            F.append([a, b, c2, d])
    return Block(np.asarray(V) + np.asarray(at, float), F).oriented()


def rotate(V, axis: str, deg: float, about=(0, 0, 0)):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    R = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
         "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    o = np.asarray(about, float)
    return (np.asarray(V, float) - o) @ np.array(R).T + o


# ---- handing the blocks to Blender ----------------------------------------------------------------------------------

def canonical(V, F):
    """(V, F, point_map, face_map) in the order blender_ops.canonical() gives: points by position (as Blender stores
    them, float32, rounded to 1e-6), faces by their point indices read from the lowest."""
    V = np.asarray(V, float)
    key = [tuple(round(float(np.float32(x)), 6) for x in p) for p in V]
    order = sorted(range(len(V)), key=lambda i: (key[i], i))
    pmap = {old: new for new, old in enumerate(order)}
    F2 = [[pmap[i] for i in f] for f in F]

    def fkey(f):
        k = f.index(min(f))
        return tuple(f[k:] + f[:k])
    forder = sorted(range(len(F2)), key=lambda i: (fkey(F2[i]), i))
    fmap = {old: new for new, old in enumerate(forder)}
    return V[order], [F2[i] for i in forder], pmap, fmap


def start(blocks: list[Block]) -> list[dict]:
    """The first ops: cage_new with every block, then each region named and each crease set, by index."""
    V, F, C, R, off = [], [], [], {}, 0
    for b in blocks:
        for name, fs in b.regions.items():
            R.setdefault(name, []).extend(len(F) + i for i in fs)
        V.append(b.V)
        F += [[i + off for i in f] for f in b.F]
        C += [(a + off, b2 + off, w) for a, b2, w in b.creases]
        off += len(b.V)
    Vc, Fc, pmap, fmap = canonical(np.concatenate(V), F)
    ops = [{"op": "cage_new", "quads": {"V": np.round(Vc, 6).tolist(), "F": Fc}}]
    for name, fs in R.items():
        ops.append({"op": "name_region", "name": name, "faces": {"indices": sorted({fmap[i] for i in fs})}})
    by_w: dict = {}
    for a, b2, w in C:
        by_w.setdefault(round(w, 4), []).append([pmap[a], pmap[b2]])
    for w, es in sorted(by_w.items()):
        ops.append({"op": "crease", "edges": es, "value": w})
    return ops


def build(ops, cfg=None, timeout: float = 600.0) -> meshsource.CageData:
    """Run the op list in Blender's fixed runner and return the cage (with .high when ops were high_only)."""
    from ...adapters import blender_model
    return blender_model.run_ops(ops, cfg=cfg, timeout=timeout)["cage"]


# ---- the design source ---------------------------------------------------------------------------------------------

def _shells(cage: meshsource.CageData) -> list[list[int]]:
    from ...game import pipeline
    return [list(range(len(p.F))) for p in pipeline.split_cage(cage)]


def split_high(cage: meshsource.CageData) -> list[meshsource.CageData | None]:
    """The high cage cut into one piece per connected low part: a high shell goes to the low part whose points it
    keeps most of (the part itself, detailed), else to the low part nearest its centre (a kit part, a rivet)."""
    from scipy.spatial import cKDTree

    from ...game import pipeline
    lows = pipeline.split_cage(cage)
    hc = pipeline.high_of(cage)
    if hc is None:
        return [None] * len(lows)
    highs = pipeline.split_cage(hc)
    lowpts = [np.round(l.V, 4) for l in lows]
    keysets = [set(map(tuple, p)) for p in lowpts]
    allpts = np.concatenate([l.V for l in lows])
    owner = np.concatenate([np.full(len(l.V), i) for i, l in enumerate(lows)])
    tree = cKDTree(allpts)
    groups: dict = {}
    for h in highs:
        hp = set(map(tuple, np.round(h.V, 4)))
        share = [len(hp & ks) / max(len(ks), 1) for ks in keysets]
        best = int(np.argmax(share))
        if share[best] < 0.3:
            _d, i = tree.query(h.V.mean(0))
            best = int(owner[i])
        groups.setdefault(best, []).append(h)
    out = []
    for i, low in enumerate(lows):
        g = groups.get(i)
        if g and len(g) == 1 and len(g[0].V) == len(low.V) and len(g[0].F) == len(low.F) and \
                np.allclose(np.sort(g[0].V, axis=0), np.sort(low.V, axis=0), atol=1e-4):
            g = None                                   # the part itself, unchanged: it goes to the bake as it is
        out.append(pipeline.merge_cages(g) if g else None)
    return out


def _dumps(x) -> str:
    return json.dumps(x, separators=(",", ":"))


def _points(V) -> list:
    return [[float(f"{a:.2f}") + 0.0 for a in p] for p in np.asarray(V, float)]


def literal(c: meshsource.CageData, name: str, high: meshsource.CageData | None = None) -> str:
    """CageData.literal(), compact: points to 0.01 mm, no spaces (a design source is at most 200 kB)."""
    def body(k):
        return f"V={_dumps(_points(k.V))},F={_dumps(k.F)},creases={_dumps(k.creases)},regions={_dumps(k.regions)}"
    hi = ""
    if high is not None:
        hi = (",\n    high={" + f'"V":{_dumps(_points(high.V))},"F":{_dumps(high.F)},"creases":{_dumps(high.creases)},'
              f'"regions":{_dumps(high.regions)}' + "}")
    return f"{name} = meshsource.cage(\n    {body(c)}{hi})\n"


def design_source(cage: meshsource.CageData, title: str, materials: dict | None = None, note: str = "") -> str:
    """A design source whose solid is the cage's limit surface (one literal per connected part, fused), with the
    high-only bake source kept part by part and the materials as a materials() method."""
    from ...game import materials as matlib
    from ...game import pipeline
    if materials is not None:
        pipeline.region_materials(cage, materials)
    parts = pipeline.split_cage(cage)
    highs = split_high(cage)
    lits = [literal(c, f"CAGE_{i}", h) for i, (c, h) in enumerate(zip(parts, highs))]
    names = ", ".join(f"CAGE_{i}" for i in range(len(parts)))
    t = json.dumps(str(title))
    doc = (str(title).replace('"', "'") + ": a subdivision cage as exact CAD, with a high-only bake source. "
           + note.replace('"', "'")).strip()
    return f'''"""{doc}"""
from form import meshsource
from form.recipes.base import Feature, Param, Recipe, Stage

{"".join(lits)}
CAGES = [{names}]


class Design(Recipe):
    title = {t}
    summary = "A subdivision cage; its limit surface is the solid. High-only detail is baked into the game maps."
    solids = 1
    params = [Param("merge_faces", "Merge B-spline faces", 1, 0, 1, 1, "", "form", "body",
                    "1: regular patch blocks become multi-span B-spline faces (a lighter STEP); 0: one face per patch.")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        parts = [c.to_subd().solid(merge=bool(round(v["merge_faces"]))) for c in CAGES]
        body = parts[0].fuse(*parts[1:]).clean() if len(parts) > 1 else parts[0]   # one fuse: parts that meet join
        return [Stage("body", body)]
''' + ("\n" + matlib.source_method(materials) if materials else "")
