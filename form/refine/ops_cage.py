"""Cage refinement operators: detail for subdivision cages (game assets), as model_mesh ops for Blender's fixed runner.

Two layers, both plain Python (no Blender, no OCCT at import; every function is deterministic):

  * Planners return model_mesh op dicts (form/adapters/blender_model.OP_SCHEMA). The game exemplars
    (form/exemplars/game/) are written with them, and the operators below use them too.

        crisp(region, distance)          the region's border creased with its corner points pinned (true corners
                                         instead of the round "pill" a creased quad subdivides into), and support
                                         loops either side at `distance` when the faces beside it are curved
        panel_line / trim_strip / inset  the runner's ops with checked numbers
        rhythm(n, ratios)                three sizes at a constant pitch (1 : 0.38 : 0.15 by default)
        kit_line(...)                    kit parts along a line at a constant pitch in that rhythm, never inside a
                                         frozen box
        kit_ring(...)                    kit parts round an axis at a constant pitch (geonodes_array, Geometry Nodes)
        view_deficits(P, T)              the 64 px convexity deficit (1 - solidity) per view
        breakers(P, T, available)        silhouette breakers (brow, vent, crest) ranked by the views they would fix
        breaker_op(kind, region, size)   the extrusion that makes one

  * Operators (form.refine.Operator, domain "cage") for the refinement engine. A cage design source
    (form/exemplars/game/base.design_source, form.game.pipeline.cage_design_source) carries its cage as CAGE_<i>
    literals; an operator adds model_mesh ops to the source's REFINE_OPS list (Patch.edit), and replay(source) gives
    the op list that rebuilds the refined cage (the cage's own points, regions and creases, then REFINE_OPS).
    The bake source (high) is kept as it was: the operators change the low cage only, and the engine's game gates
    (validator, LOD budgets) judge the result.

Frozen geometry: operators never select faces of a frozen feature (roles fit, access, mechanism, interface); for a
cage that means regions named after one, and kit_line drops every copy whose point lies in a frozen box.
"""
from __future__ import annotations

import ast
import json
import math
import re

import numpy as np

from . import Operator, Patch

HOOK = "REFINE_OPS"
RATIOS = (1.0, 0.38, 0.15)
# the rhythm of three sizes along a run: big at the ends of every bay of four, a medium in the middle, small between
MOTIF = (0, 2, 1, 2)
BREAKERS = {
    # kind: (outward direction, views whose outline it changes)
    "brow": ((0.0, -1.0, 0.0), ("left", "right", "three_quarter")),
    "crest": ((0.0, 0.0, 1.0), ("front", "back", "left", "right")),
    "vent": ((1.0, 0.0, 0.0), ("front", "back", "top")),
}


# ---- planners: model_mesh ops ----------------------------------------------------------------------------------

def _hi(op: dict, high_only: bool) -> dict:
    if high_only:
        op["high_only"] = True
    return op


def crisp(region: str | None = None, distance: float = 0.0, high_only: bool = False) -> list[dict]:
    """True corners: the region's border creased with its corners pinned, and (distance > 0) support loops either side
    of it. Catmull-Clark rounds a creased loop into a B-spline through its points, so a creased quad becomes a pill.
    Pinning gives each corner point of the loop a third creased edge, which makes it a corner: it stays where it is and
    the loop runs straight into it. Flat faces either side of the crease stay flat on their own; on curved ones the
    support loops at `distance` hold the surface up to the crease. No region: support loops (with pinned corners) on
    every creased edge."""
    d = float(distance or 0.0)
    if d < 0:
        raise ValueError("crisp: distance must be >= 0")
    if not region and not d:
        raise ValueError("crisp: give a region, a distance or both")
    ops = []
    if region:
        ops.append(_hi({"op": "crease", "region_boundary": region, "value": 1.0, "pin_corners": True}, high_only))
    if d:
        edges = {"region_boundary": region} if region else {"creased": True}
        ops.append(_hi({"op": "support_loops", "edges": edges, "distance": round(d, 4), "pin_corners": True},
                       high_only))
    return ops


def panel_line(edges: dict, width: float, depth: float, crease: float = 1.0, name: str | None = None,
               high_only: bool = False) -> dict:
    op = {"op": "panel_line", "edges": edges, "width": round(float(width), 4), "depth": round(float(depth), 4),
          "crease": float(crease)}
    if name:
        op["name"] = name
    return _hi(op, high_only)


def trim_strip(edges: dict, width: float, height: float, crease: float = 1.0, name: str | None = None,
               high_only: bool = False) -> dict:
    op = {"op": "trim_strip", "edges": edges, "width": round(float(width), 4), "height": round(float(height), 4),
          "crease": float(crease)}
    if name:
        op["name"] = name
    return _hi(op, high_only)


def inset(faces: dict, thickness: float, depth: float = 0.0, individual: bool = False, crease: float | None = 1.0,
          name: str | None = None, high_only: bool = False) -> dict:
    op = {"op": "inset", "faces": faces, "thickness": round(float(thickness), 4), "depth": round(float(depth), 4),
          "individual": bool(individual)}
    if crease is not None:
        op["crease"] = float(crease)
    if name:
        op["name"] = name
    return _hi(op, high_only)


def rhythm(n: int, ratios=RATIOS) -> list[float]:
    """n sizes at a constant pitch in three tiers: the motif big, small, medium, small repeats, and a run of more
    than one slot ends big too, so it reads as bays."""
    r = [float(x) for x in ratios]
    if len(r) != 3 or not r[0] >= r[1] >= r[2] > 0:
        raise ValueError("rhythm: three ratios, largest first, all > 0")
    out = [r[MOTIF[i % len(MOTIF)]] for i in range(int(n))]
    if n > 1:
        out[-1] = r[0]
    return out


def _inside(p, boxes, margin=0.0) -> bool:
    for lo, hi in boxes or ():
        if all(lo[k] - margin <= p[k] <= hi[k] + margin for k in range(3)):
            return True
    return False


def kit_line(part: str, params: dict, p0, p1, normal, count: int | None = None, pitch: float | None = None,
             ratios=RATIOS, scale: float = 1.0, frozen_boxes=(), margin: float = 0.5, snap: bool = False,
             name: str | None = None, high_only: bool = False, rotation: float = 0.0) -> list[dict]:
    """Kit parts from p0 to p1 at a constant pitch (count slots, or as many as `pitch` allows), sized by rhythm();
    one kit_place op per size tier. Copies whose point lies in a frozen box are dropped (the pitch of the others is
    unchanged)."""
    a, b = np.asarray(p0, float), np.asarray(p1, float)
    L = float(np.linalg.norm(b - a))
    if count is None:
        if not pitch or pitch <= 0:
            raise ValueError("kit_line: give count or a pitch > 0")
        count = max(1, int(math.floor(L / float(pitch) + 1e-9)) + 1)
    count = int(count)
    pts = [a + (b - a) * (i / (count - 1) if count > 1 else 0.5) for i in range(count)]
    sizes = rhythm(count, ratios)
    tiers: dict = {}
    for p, s in zip(pts, sizes):
        if _inside(p, frozen_boxes, margin):
            continue
        tiers.setdefault(s, []).append([round(float(x), 4) for x in p])
    ops = []
    for s in sorted(tiers, reverse=True):
        op = {"op": "kit_place", "part": part, "params": dict(params), "at": tiers[s],
              "scale": round(float(scale) * s, 4)}
        if snap:
            op["snap"] = True
        else:
            op["normal"] = [float(x) for x in normal]
        if rotation:
            op["rotation"] = float(rotation)
        if name:
            op["name"] = name
        ops.append(_hi(op, high_only))
    return ops


def kit_ring(part: str, params: dict, seeds, normal, axis: str, count: int, center=(0.0, 0.0, 0.0),
             scale=1.0, rotation: float = 0.0, name: str | None = None, high_only: bool = False) -> dict:
    """Kit parts round an axis at a constant pitch: each seed point gets a copy (+Z on `normal`), and Geometry Nodes
    turns that set round the axis through center in `count` equal steps (geonodes_array)."""
    op = {"op": "geonodes_array", "part": part, "params": dict(params), "count": int(count), "axis": axis,
          "center": [float(x) for x in center], "at": [[round(float(x), 4) for x in p] for p in seeds],
          "normal": [float(x) for x in normal], "scale": scale, "rotation": float(rotation)}
    if name:
        op["name"] = name
    return _hi(op, high_only)


# ---- the silhouette -----------------------------------------------------------------------------------------------

def triangles(V, F) -> tuple[np.ndarray, np.ndarray]:
    """A polygon cage as triangles (fans), for the 64 px masks."""
    T = [(f[0], f[k], f[k + 1]) for f in F for k in range(1, len(f) - 1)]
    return np.asarray(V, float), np.asarray(T, np.int64)


def view_deficits(P, T) -> dict:
    """{view: 1 - solidity} of the outline at 64 px in the six views of form/refine/analyze (0: a convex blob)."""
    from ..critique import solidity
    from .analyze import masks
    return {k: round(1.0 - float(solidity(m)), 4) for k, m in masks(P, T).items()}


def breakers(P, T, available=("brow", "crest", "vent")) -> list[tuple[str, float]]:
    """The silhouette breakers worth making, best first: each kind scores the mean blob-ness (how far its views are
    under analyze.SIL_BLOB convexity deficit) of the views whose outline it changes."""
    from .analyze import SIL_BLOB
    d = view_deficits(P, T)
    out = []
    for kind in available:
        views = BREAKERS[kind][1]
        need = float(np.mean([max(0.0, SIL_BLOB - d.get(v, 0.0)) / SIL_BLOB for v in views]))
        out.append((kind, round(need, 4)))
    return sorted(out, key=lambda kv: (-kv[1], kv[0]))


def breaker_op(kind: str, region: str, size: float, exaggeration: float = 1.0, sign: float = 1.0,
               direction=None) -> dict:
    """The extrusion that makes a breaker: the region pushed out along the kind's direction (times sign: -1 for a
    vent on the other side), by `size` x exaggeration mm. Its side walls take the region (sides "region"), so later
    ops that select the neighbouring regions see the same faces on both sides of a symmetric part."""
    if kind not in BREAKERS:
        raise ValueError(f"no breaker {kind!r}; kinds: {', '.join(BREAKERS)}")
    d = np.asarray(direction if direction is not None else BREAKERS[kind][0], float) * float(sign)
    d = d / (np.linalg.norm(d) or 1.0) * float(size) * float(exaggeration)
    return {"op": "extrude_region", "faces": {"region": region}, "vector": [round(float(x), 4) for x in d],
            "sides": "region"}


# ---- measures the bench and the tests use ----------------------------------------------------------------------

def pitch_variance(angles_deg) -> float:
    """Relative spread (std / mean) of the steps between sorted angles round a full turn."""
    a = np.sort(np.mod(np.asarray(angles_deg, float), 360.0))
    if len(a) < 2:
        return 0.0
    steps = np.diff(np.r_[a, a[0] + 360.0])
    return float(np.std(steps) / max(np.mean(steps), 1e-12))


# ---- cage design sources: CAGE_<i> literals and the REFINE_OPS hook -----------------------------------------------

_CAGE = re.compile(r"^(CAGE_\d+)\s*=\s*meshsource\.cage\(", re.M)


def cages_of(source: str) -> dict:
    """{name: {"V", "F", "creases", "regions", "high"}} of a cage design source, read with ast (nothing runs)."""
    out = {}
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return out
    for n in tree.body:
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id.startswith("CAGE_") and isinstance(n.value, ast.Call)):
            continue
        kw = {}
        for k in n.value.keywords:
            try:
                kw[k.arg] = ast.literal_eval(k.value)
            except ValueError:
                kw[k.arg] = None
        try:
            from .. import meshsource
            kw = meshsource.cage_fields(kw)
        except (ValueError, TypeError):
            continue
        if kw.get("V") is not None and kw.get("F") is not None:
            out[n.targets[0].id] = {"V": kw["V"], "F": kw["F"], "creases": kw.get("creases") or [],
                                    "regions": kw.get("regions") or {}, "high": kw.get("high")}
    return out


def regions_of(source: str) -> set:
    return {r for c in cages_of(source).values() for r, fs in (c["regions"] or {}).items() if fs}


def region_borders(source: str) -> dict:
    """{region: number of border edges} over every cage of the source: edges with a face of the region on one side
    only. A region that covers whole closed parts has none, so region_boundary selects nothing on it (the runner
    refuses an empty edge selection); operators that work on a region's border pick only regions listed here."""
    out: dict = {}
    for c in cages_of(source).values():
        F = c["F"]
        for r, fs in (c["regions"] or {}).items():
            cnt: dict = {}
            for i in set(fs or ()):
                if not 0 <= int(i) < len(F):
                    continue
                f = F[int(i)]
                for a, b in zip(f, f[1:] + f[:1]):
                    e = (min(a, b), max(a, b))
                    cnt[e] = cnt.get(e, 0) + 1
            n = sum(1 for v in cnt.values() if v == 1)
            if n:
                out[r] = out.get(r, 0) + n
    return out


def refine_ops_of(source: str) -> list:
    m = re.search(rf"^{HOOK}\s*=\s*(.*)$", source or "", re.M)
    if not m:
        return []
    try:
        from .. import meshsource
        out = meshsource.unpack(json.loads(m.group(1)))
        return out if isinstance(out, list) else []
    except ValueError:
        return []


PACK_OVER = 16_000                   # an op list longer than this (as JSON) is written packed (meshsource.pack)


def with_refine_ops(source: str, ops: list) -> str:
    """The source with REFINE_OPS set to ops (one JSON line after the CAGES list, or replacing the one there). A long
    list is written as one packed string literal (meshsource.pack), so kit detail never runs into the source limit."""
    text = json.dumps(ops, separators=(',', ':'))
    if len(text) > PACK_OVER:
        from .. import meshsource
        text = json.dumps(meshsource.pack(ops))
    line = f"{HOOK} = {text}"
    if re.search(rf"^{HOOK}\s*=", source, re.M):
        return re.sub(rf"^{HOOK}\s*=.*$", lambda _m: line, source, count=1, flags=re.M)
    m = re.search(r"^CAGES\s*=.*$", source, re.M)
    if not m:
        raise ValueError("not a cage design source (no CAGES list)")
    return source[:m.end()] + "\n" + line + source[m.end():]


def replay(source: str) -> list[dict]:
    """The model_mesh op list that rebuilds the refined cage: cage_new with every CAGE_<i> literal's points and
    faces, its regions and creases by index, then REFINE_OPS."""
    cs = list(cages_of(source).values())
    if not cs:
        raise ValueError("not a cage design source (no CAGE_<i> literals)")
    from ..exemplars.game.base import Block, start
    blocks = [Block(c["V"], c["F"], c["creases"], c["regions"]) for c in cs]
    return start(blocks) + list(refine_ops_of(source))


def _append(op_list):
    def edit(source):
        return with_refine_ops(source, refine_ops_of(source) + list(op_list))
    return edit


# ---- operators -----------------------------------------------------------------------------------------------------

def _frozen_regions(design) -> set:
    return set(design.frozen)


def _game_cage(design) -> tuple[bool, str]:
    if design.purpose != "game":
        return False, "cage operators refine game assets"
    if not cages_of(design.source):
        return False, "the source holds no subdivision cage"
    return True, ""


class SupportLoops(Operator):
    """True corners on every creased edge (crisp())."""
    name = "support_loops"
    domain = "cage"
    targets = ("edge_hierarchy",)
    cost = 0.5
    label = "Support loops"
    params = {"distance": 2.0}

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if any(o.get("op") == "support_loops" for o in refine_ops_of(design.source)):
            return False, "support loops already added"
        if not any(c["creases"] for c in cages_of(design.source).values()):
            return False, "no creased edges"
        return True, ""

    def apply(self, design, analysis, params):
        d = float(params.get("distance", 2.0))
        size = design.size()
        if size:
            d = min(d, 0.01 * min(size))                    # never wider than 1 % of the smallest dimension
        ops = crisp(None, d)
        return Patch(edit=_append(ops), reason=f"Support loops {d:g} mm either side of every crease, the corners "
                     "kept, so creased faces subdivide into true corners.", params={"distance": d, "ops": ops})


class _RegionOp(Operator):
    """Shared: picks the largest unfrozen region of the cage (deterministic: by face count, then name)."""

    border = True                                   # the op works on the region's border (region_boundary)

    def _region(self, design):
        frozen = _frozen_regions(design)
        borders = region_borders(design.source) if self.border else None
        counts: dict = {}
        for c in cages_of(design.source).values():
            for r, fs in (c["regions"] or {}).items():
                if r not in frozen and fs and (borders is None or r in borders):
                    counts[r] = counts.get(r, 0) + len(fs)
        if not counts:
            return None
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if self._region(design) is None:
            return False, ("no named region with a border to work on" if self.border else
                           "no named region to work on")
        if any(o.get("op") == self.name for o in refine_ops_of(design.source)):
            return False, f"{self.name} already added"
        return True, ""


class PanelLine(_RegionOp):
    name = "panel_line"
    domain = "cage"
    targets = ("surface_breaks", "detail_scales", "interior_read")
    cost = 0.75
    label = "Panel line"
    params = {"width": 0.6, "depth": 0.5}

    def apply(self, design, analysis, params):
        r = self._region(design)
        s = min(design.size() or (100.0,))
        w = max(float(params.get("width", 0.6)), 0.012 * s)
        dp = max(float(params.get("depth", 0.5)), 0.006 * s)
        op = panel_line({"region_boundary": r}, w, dp)
        return Patch(edit=_append([op]), reason=f"A {w:.3g} mm groove round the {r} region breaks the surface.",
                     params={"region": r, "width": w, "depth": dp})


class TrimStrip(_RegionOp):
    name = "trim_strip"
    domain = "cage"
    targets = ("surface_breaks", "detail_scales")
    cost = 1.0
    label = "Trim strip"
    params = {"width": 1.0, "height": 0.5}

    def apply(self, design, analysis, params):
        r = self._region(design)
        s = min(design.size() or (100.0,))
        w, h = 0.03 * s * float(params.get("width", 1.0)), 0.01 * s * float(params.get("height", 0.5)) * 2
        op = trim_strip({"region_boundary": r}, w, h)
        return Patch(edit=_append([op]), reason=f"A raised band round the {r} region frames it.",
                     params={"region": r, "width": w, "height": h})


class Inset(_RegionOp):
    name = "inset"
    domain = "cage"
    targets = ("surface_breaks", "interior_read", "detail_scales")
    cost = 0.75
    label = "Inset panel"
    params = {"depth": -0.5}
    border = False

    def apply(self, design, analysis, params):
        r = self._region(design)
        s = min(design.size() or (100.0,))
        t, d = 0.02 * s, 0.01 * s * float(params.get("depth", -0.5)) * 2
        op = inset({"region": r}, t, d, crease=1.0)
        return Patch(edit=_append([op]), reason=f"The {r} region inset {abs(d):.3g} mm with a {t:.3g} mm border.",
                     params={"region": r, "thickness": t, "depth": d})


class KitPlace(_RegionOp):
    """Kit rivets along the long side of the bounding box at a constant pitch in three sizes, kept off frozen boxes."""
    name = "kit_place"
    domain = "cage"
    targets = ("detail_scales", "interior_read")
    cost = 1.5
    label = "Kit detail"
    border = False
    params = {"ratios": list(RATIOS), "pitch": "constant", "part": "rivet_dome", "count": 9}

    def preconditions(self, design, analysis):
        ok, why = super().preconditions(design, analysis)
        if ok and not design.bbox:
            return False, "the design's size is not known"
        return ok, why

    def apply(self, design, analysis, params):
        (x0, y0, z0), (x1, y1, z1) = design.bbox
        size = (x1 - x0, y1 - y0, z1 - z0)
        k = int(np.argmax(size))
        p0, p1 = [(x0 + x1) / 2, y0, (z0 + z1) / 2], [(x0 + x1) / 2, y0, (z0 + z1) / 2]
        p0[k] = (x0, y0, z0)[k] + 0.1 * size[k]
        p1[k] = (x0, y0, z0)[k] + 0.9 * size[k]
        if k == 1:                                         # the long side is Y: run along the top instead
            p0[2] = p1[2] = z1
        d = 0.04 * min(s for s in size if s > 0)
        ops = kit_line(str(params.get("part", "rivet_dome")), {"diameter": round(max(1.0, min(40.0, d)), 3),
                                                              "height": round(max(0.4, min(20.0, d * 0.35)), 3)},
                       p0, p1, None, count=int(params.get("count", 9)), ratios=params.get("ratios", RATIOS),
                       frozen_boxes=list(design.frozen_boxes.values()), snap=True)
        if not ops:
            return None
        return Patch(edit=_append(ops), reason="Kit detail at a constant pitch in three sizes (1 : 0.38 : 0.15).",
                     params={"ops": ops})


def region_normals(source: str) -> dict:
    """{region: (mean outward unit normal, share of the cage's faces)} of the source's bordered regions (Newell
    normals of the cage faces, area weighted)."""
    acc: dict = {}
    total = 0
    borders = region_borders(source)
    for c in cages_of(source).values():
        V = np.asarray(c["V"], float)
        total += len(c["F"])
        for r, fs in (c["regions"] or {}).items():
            if r not in borders:
                continue
            n, k = acc.get(r, (np.zeros(3), 0))
            for i in fs or ():
                f = c["F"][int(i)]
                P = V[f]
                n = n + 0.5 * np.cross(P, np.roll(P, -1, axis=0)).sum(0)
                k += 1
            acc[r] = (n, k)
    out = {}
    for r, (n, k) in acc.items():
        ln = float(np.linalg.norm(n))
        if ln > 1e-9:
            out[r] = (n / ln, k / max(total, 1))
    return out


class SilhouetteBreaker(Operator):
    """A brow, crest or vent extrusion, chosen from the 64 px convexity deficit of the views it would change, on the
    cage region named after it. A cage without such regions gets its plainest view broken instead: the bordered
    region (3-25 % of the faces) whose mean normal lies most across that view's line of sight is pushed out along
    it, its seat creased (a plate, a lid band, a boss standing out of the outline)."""
    name = "silhouette_breaker"
    domain = "cage"
    targets = ("silhouette",)
    cost = 1.5
    label = "Silhouette breaker"
    params = {"exaggeration": 1.0}

    def _generic(self, design, analysis, done):
        from .analyze import VIEWS6, _rot
        sol = ((analysis.measures or {}).get("silhouette") or {}).get("solidity") if analysis else None
        if not sol:
            return None
        worst = max(sol, key=lambda v: (sol[v], v))
        fwd = _rot(*VIEWS6[worst])[2]
        frozen = _frozen_regions(design)
        best = None
        for r, (n, share) in sorted(region_normals(design.source).items()):
            if r in frozen or r in done or not 0.03 <= share <= 0.25:
                continue
            across = 1.0 - abs(float(n @ fwd))
            if across < 0.7:
                continue
            key = (round(across, 3), round(share, 4), r)
            if best is None or key > best[0]:
                best = (key, r, n)
        return None if best is None else ("region", best[1], [float(x) for x in best[2]])

    def _plan(self, design, analysis):
        regs = regions_of(design.source) - _frozen_regions(design)
        done = {o.get("faces", {}).get("region") for o in refine_ops_of(design.source)
                if o.get("op") == "extrude_region"}
        avail = [k for k in BREAKERS if k in regs and k not in done]
        if not avail:
            return self._generic(design, analysis, done)
        sol = ((analysis.measures or {}).get("silhouette") or {}).get("solidity") if analysis else None
        if sol:
            from .analyze import SIL_BLOB
            d = {v: 1 - s for v, s in sol.items()}
            ranked = sorted(((k, float(np.mean([max(0.0, SIL_BLOB - d.get(v, 0.0)) for v in BREAKERS[k][1]])))
                             for k in avail), key=lambda kv: (-kv[1], kv[0]))
        else:
            ranked = [(k, 0.0) for k in sorted(avail)]
        return ranked[0][0]

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if self._plan(design, analysis) is None:
            return False, "no brow, crest, vent or other bordered region left to push out"
        return True, ""

    def apply(self, design, analysis, params):
        kind = self._plan(design, analysis)
        ex = float(params.get("exaggeration", 1.0))
        size = 0.06 * min(design.size() or (100.0,))
        if isinstance(kind, tuple):                       # the generic breaker: a region along its own normal
            _k, region, n = kind
            op = breaker_op("crest", region, size, ex, direction=n)
            return Patch(edit=_append([op] + crisp(region)), reason=f"The {region} region pushed out "
                         f"{size * ex:.3g} mm along its normal, its seat creased, breaks the plainest view's outline.",
                         params={"kind": "region", "region": region, "vector": op["vector"]})
        op = breaker_op(kind, kind, size, ex)
        # its seat creased with the corners kept: pushed out of a smooth shell without it, the breaker subdivides
        # into a swell (a lump) instead of a plate standing on the shell
        return Patch(edit=_append([op] + crisp(kind)), reason=f"A {kind} pushed out {size * ex:.3g} mm, its seat "
                     "creased, breaks the outline in the views that read as a blob at 64 px.",
                     params={"kind": kind, "vector": op["vector"]})


def soft_borders(source: str) -> dict:
    """{region: share of its border edges that are not creased} for the regions of the source's cages that have a
    border: a soft border subdivides into a smooth swell, which reads as a lump on a hard-surface part."""
    out: dict = {}
    for c in cages_of(source).values():
        F = c["F"]
        cr = {(min(int(a), int(b)), max(int(a), int(b))) for a, b, w in c["creases"] or [] if float(w) >= 0.5}
        for r, fs in (c["regions"] or {}).items():
            cnt: dict = {}
            for i in set(fs or ()):
                if 0 <= int(i) < len(F):
                    f = F[int(i)]
                    for a, b in zip(f, f[1:] + f[:1]):
                        e = (min(a, b), max(a, b))
                        cnt[e] = cnt.get(e, 0) + 1
            border = [e for e, n in cnt.items() if n == 1]
            if border:
                soft, tot = out.get(r, (0, 0))
                out[r] = (soft + sum(1 for e in border if e not in cr), tot + len(border))
    return {r: round(s / t, 4) for r, (s, t) in out.items() if t}


class CrispRegions(Operator):
    """Hard-surface plates instead of lumps: the borders of up to three named regions whose borders are mostly soft
    creased with their corners pinned, and support loops beside them (crisp()). A pushed-out brow or a cheek plate
    whose border is not creased subdivides into a smooth swell; creased and supported it reads as a plate with a
    shut line."""
    name = "crisp_regions"
    domain = "cage"
    targets = ("edge_hierarchy", "surface_breaks", "interior_read")
    cost = 0.5
    label = "Crisp plates"
    params = {"count": 3, "soft": 0.5}

    def _pick(self, design, params):
        frozen = _frozen_regions(design)
        done = {o.get("region_boundary") for o in refine_ops_of(design.source) if o.get("op") == "crease"}
        soft = soft_borders(design.source)
        sizes = {}
        for c in cages_of(design.source).values():
            for r, fs in (c["regions"] or {}).items():
                sizes[r] = sizes.get(r, 0) + len(fs or ())
        cand = [r for r, s in soft.items() if s >= float(params.get("soft", 0.5)) and r not in frozen and r not in done]
        return sorted(cand, key=lambda r: (-sizes.get(r, 0), r))[:int(params.get("count", 3))]

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if not self._pick(design, dict(self.params)):
            return False, "every region border is creased already"
        return True, ""

    def apply(self, design, analysis, params):
        regs = self._pick(design, params)
        if not regs:
            return None
        d = 0.006 * min(design.size() or (100.0,))
        ops = []
        for r in regs:
            ops += crisp(r, round(d, 3))
        return Patch(edit=_append(ops), reason="The borders of " + ", ".join(regs) + " creased with their corners "
                     f"kept and support loops {d:.2g} mm beside them: plates with a shut line instead of soft swells.",
                     params={"regions": regs, "distance": d})


OPERATORS = [SupportLoops(), PanelLine(), TrimStrip(), Inset(), KitPlace(), SilhouetteBreaker(), CrispRegions()]
