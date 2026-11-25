"""Primary-form operators for subdivision cages: the big shapes a game asset is read by, before any detail.

Detail (panel lines, plates, kit parts: ops_cage.py) cannot rescue a lumpy shell, a flat slab or a plain disc; these
operators change the primary form itself, and every future cage asset gets them. Each one edits the CAGE_<i> literals
of a cage design source (form/exemplars/game/base.design_source): it moves points, or adds a closed part, and never
changes the faces of a part that is there, so every cage stays closed, manifold and wound as it was by construction
(no T-junction, no zero-area face). The bake source (high) of a part moves with its low cage: a space warp is applied
to both, and a per-part move (fairing) is carried to the high's points by inverse-distance weights over the nearest
low points. REFINE_OPS, which select by region, replay on the moved cage unchanged.

    ShellFairing      fairing of a lumpy shell: Taubin smoothing (lambda / mu, no shrink) of the cage's free points;
                      creased edges, region borders and frozen regions are held, so the features keep their lines
    DiscDish          a disc (wheel, rim, gear) gets a dished face: the spokes sink along the axis inside the outer
                      ring (smoothly to nothing at the ring) and the hub stands out, so the face reads in depth
                      instead of as a flat disc
    BandMassing       a box with a lid (chest, crate, trunk): the lid overhangs the body and rises into a fuller dome,
                      the body's upper walls step in under it while its foot keeps its width, so the outline steps
                      twice (foot, lid) instead of reading as a box
    PierMassing       a slab (wall, fence, panel): end piers as new closed parts, proud of both faces and standing
                      above the top, kept inside the slab's footprint (a kit piece stays on its grid)
    BarTaper          a handheld bar (remote, controller, torch): a waist where the hand closes and a slight taper to
                      the tail, in plan, so the outline is not a plain bar

Chosen by product class and style: words of the brief first (wheel, chest, wall, remote, ...), then the shape of the
cage (disc, box with a lid part, slab, bar). The engine scores each candidate as it scores detail: the 64 px outline
in six views, the lit interior read and, for fairing, the shell's fairness (analyze.fairness), on a quick bake. Frozen
geometry (regions named after a frozen feature) is never moved.
"""
from __future__ import annotations

import ast
import math

import numpy as np

from . import Operator, Patch
from .ops_cage import _frozen_regions, _game_cage, cages_of

FLIP_COS = 0.2                   # a cage face whose normal turns by more than ~78 degrees counts as folded


# ---- the cage literals of a source -----------------------------------------------------------------------------------

class _Cage:
    """A CageData-like record (V, F, creases, regions) that form/exemplars/game/base.literal writes."""

    def __init__(self, V, F, creases=(), regions=None):
        self.V = np.asarray(V, float)
        self.F = [list(map(int, f)) for f in F]
        self.creases = [(int(a), int(b), float(w)) for a, b, w in creases or ()]
        self.regions = {k: list(v) for k, v in (regions or {}).items()}


def parts_of(source: str) -> list[tuple[str, _Cage, _Cage | None]]:
    """[(name, low, high or None)] for every CAGE_<i> literal, in source order."""
    out = []
    for name, c in cages_of(source).items():
        hi = c.get("high")
        h = None
        if isinstance(hi, dict) and hi.get("V") is not None and hi.get("F") is not None:
            h = _Cage(hi["V"], hi["F"], hi.get("creases") or (), hi.get("regions") or {})
        out.append((name, _Cage(c["V"], c["F"], c["creases"], c["regions"]), h))
    return out


def with_parts(source: str, parts: list[tuple[str, _Cage, _Cage | None]]) -> str:
    """The source with each named CAGE_<i> literal rewritten (base.literal), and new names appended to CAGES."""
    from ..exemplars.game.base import literal
    tree = ast.parse(source)
    spans = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id.startswith("CAGE_"):
            spans[n.targets[0].id] = (n.lineno, n.end_lineno)
    lines = source.splitlines(keepends=True)
    new = [(name, low, high) for name, low, high in parts if name not in spans]
    for name, low, high in sorted((p for p in parts if p[0] in spans), key=lambda p: -spans[p[0]][0]):
        a, b = spans[name]
        lines[a - 1:b] = [literal(low, name, high)]
    text = "".join(lines)
    if new:
        tree = ast.parse(text)
        cages = next((n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                      and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "CAGES"), None)
        if cages is None:
            raise ValueError("not a cage design source (no CAGES list)")
        lines = text.splitlines(keepends=True)
        names = [e.id for e in cages.value.elts] + [name for name, _l, _h in new]
        lines[cages.lineno - 1:cages.end_lineno] = ["".join(literal(low, name, high) for name, low, high in new)
                                                    + "CAGES = [" + ", ".join(names) + "]\n"]
        text = "".join(lines)
    return text


def _held_frozen(c: _Cage, frozen: set) -> np.ndarray:
    held = np.zeros(len(c.V), bool)
    for r, fs in c.regions.items():
        if r in frozen:
            for f in fs:
                if 0 <= int(f) < len(c.F):
                    held[c.F[int(f)]] = True
    return held


def _normals(V, F) -> np.ndarray:
    out = np.zeros((len(F), 3))
    for i, f in enumerate(F):
        P = V[f]
        out[i] = 0.5 * np.cross(P, np.roll(P, -1, axis=0)).sum(0)
    return out


def folded(V0, V1, F) -> int:
    """Cage faces whose normal turned by more than acos(FLIP_COS), or whose area collapsed, between V0 and V1."""
    n0, n1 = _normals(np.asarray(V0, float), F), _normals(np.asarray(V1, float), F)
    l0, l1 = np.linalg.norm(n0, axis=1), np.linalg.norm(n1, axis=1)
    ok = l0 > 1e-12
    cos = np.einsum("ij,ij->i", n0, n1) / np.maximum(l0 * l1, 1e-24)
    return int((ok & ((cos < FLIP_COS) | (l1 < 1e-3 * l0))).sum())


def carry(low0: np.ndarray, low1: np.ndarray, pts: np.ndarray, k: int = 6) -> np.ndarray:
    """pts moved by the low cage's move (low0 -> low1): each point takes the inverse-square-distance mean of the
    moves of its k nearest low points (a point on a low point takes its move exactly)."""
    from scipy.spatial import cKDTree
    low0, low1, pts = np.asarray(low0, float), np.asarray(low1, float), np.asarray(pts, float)
    d = low1 - low0
    if not len(pts) or not np.abs(d).max(initial=0.0) > 0:
        return pts.copy()
    k = min(k, len(low0))
    dist, idx = cKDTree(low0).query(pts, k=k)
    dist, idx = np.atleast_2d(dist).reshape(len(pts), k), np.atleast_2d(idx).reshape(len(pts), k)
    w = 1.0 / np.maximum(dist, 1e-9) ** 2
    exact = dist[:, 0] < 1e-6
    w[exact] = 0.0
    w[exact, 0] = 1.0
    w /= w.sum(1, keepdims=True)
    return pts + (w[:, :, None] * d[idx]).sum(1)


def warp_parts(parts, fn, frozen: set, tries: int = 4):
    """Every part's low and high points through fn(points (n, 3), strength) -> points; frozen regions' points stay.
    The strength halves until no cage face folds (folded()); (parts, strength) or (None, 0) when even 1/8 folds."""
    s = 1.0
    for _ in range(tries):
        out, bad = [], 0
        for name, low, high in parts:
            held = _held_frozen(low, frozen)
            V1 = np.asarray(fn(low.V.copy(), s), float)
            V1[held] = low.V[held]
            bad += folded(low.V, V1, low.F)
            h1 = None
            if high is not None:
                hv = np.asarray(fn(high.V.copy(), s), float)
                hh = _held_frozen(high, frozen)
                hv[hh] = high.V[hh]
                bad += folded(high.V, hv, high.F)
                h1 = _Cage(hv, high.F, high.creases, high.regions)
            out.append((name, _Cage(V1, low.F, low.creases, low.regions), h1))
        if not bad:
            return out, s
        s *= 0.5
    return None, 0.0


def _bbox(parts):
    V = np.concatenate([low.V for _n, low, _h in parts])
    return V.min(0), V.max(0)


def _words(design) -> str:
    return f" {(design.brief or '').lower()} {(design.product_class or '').lower()} "


def _says(design, words) -> bool:
    t = _words(design)
    return any(f" {w}" in t for w in words)


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, float) - e0) / max(e1 - e0, 1e-12), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _done(design, name) -> bool:
    return f"# refine: {name}" in (design.source or "")


def _mark(source: str, name: str, text: str) -> str:
    """A comment line above CAGES saying what the operator did (and that it ran: preconditions read it)."""
    i = source.find("\nCAGES = [")
    line = f"\n# refine: {name}: {text}"
    return source[:i] + line + source[i:] if i >= 0 else source + line + "\n"


# ---- fairing ---------------------------------------------------------------------------------------------------------

def held_points(c: _Cage, frozen: set) -> np.ndarray:
    """Points fairing must not move: on a creased edge (weight >= 0.5), on a region border or an open edge, or in a
    frozen region."""
    held = _held_frozen(c, frozen)
    for a, b, w in c.creases:
        if w >= 0.5:
            held[[a, b]] = True
    reg = np.full(len(c.F), "", dtype=object)
    for r, fs in sorted(c.regions.items()):
        for f in fs:
            if 0 <= int(f) < len(reg):
                reg[int(f)] = r
    ef: dict = {}
    for i, f in enumerate(c.F):
        for a, b in zip(f, f[1:] + f[:1]):
            ef.setdefault((min(a, b), max(a, b)), []).append(i)
    for (a, b), fs in ef.items():
        if len(fs) != 2 or reg[fs[0]] != reg[fs[1]]:
            held[[a, b]] = True
    return held


def taubin(V, F, held, iters: int = 8, lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    """Taubin's lambda / mu smoothing of the free points (umbrella operator over the cage's edges): lambda smooths,
    mu inflates back, so the shell keeps its size while its bumps go."""
    V = np.asarray(V, float).copy()
    n = len(V)
    E = set()
    for f in F:
        for a, b in zip(f, f[1:] + f[:1]):
            E.add((min(a, b), max(a, b)))
    if not E:
        return V
    E = np.array(sorted(E))
    A = np.concatenate([E, E[:, ::-1]])
    deg = np.maximum(np.bincount(A[:, 0], minlength=n), 1).astype(float)
    free = ~np.asarray(held, bool)
    for _ in range(int(iters)):
        for k in (lam, mu):
            s = np.zeros_like(V)
            np.add.at(s, A[:, 0], V[A[:, 1]])
            V[free] += k * (s[free] / deg[free, None] - V[free])
    return V


class ShellFairing(Operator):
    """A lumpy shell faired: Taubin smoothing of every large part's free cage points (creases, region borders and
    frozen regions held), carried to the bake source. Only when the shell measures lumpy (analyze.fairness)."""
    name = "shell_fairing"
    domain = "cage"
    targets = ("fairness",)
    cost = 0.5
    label = "Shell fairing"
    params = {"iters": 16, "min_share": 0.15}

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if _done(design, self.name):
            return False, "the shell is faired already"
        if analysis is not None and analysis.deficits.get("fairness", 0.0) < 0.15:
            return False, "the shell is fair already"
        return True, ""

    def apply(self, design, analysis, params):
        parts = parts_of(design.source)
        frozen = _frozen_regions(design)
        total = sum(len(low.F) for _n, low, _h in parts) or 1
        out, moved, worst = [], 0, 0.0
        for name, low, high in parts:
            if len(low.F) < float(params.get("min_share", 0.15)) * total:
                out.append((name, low, high))
                continue
            held = held_points(low, frozen)
            it = int(params.get("iters", 8))
            V1 = None
            while it >= 1:
                V1 = taubin(low.V, low.F, held, iters=it)
                if not folded(low.V, V1, low.F):
                    break
                it //= 2
                V1 = None
            if V1 is None:
                out.append((name, low, high))
                continue
            d = np.linalg.norm(V1 - low.V, axis=1)
            moved += int((d > 1e-6).sum())
            worst = max(worst, float(d.max(initial=0.0)))
            h1 = None
            if high is not None:
                hv = carry(low.V, V1, high.V)
                hv[_held_frozen(high, frozen)] = high.V[_held_frozen(high, frozen)]
                if folded(high.V, hv, high.F):
                    out.append((name, low, high))
                    continue
                h1 = _Cage(hv, high.F, high.creases, high.regions)
            out.append((name, _Cage(V1, low.F, low.creases, low.regions), h1))
        if not moved:
            return None
        text = f"{moved} cage points faired (Taubin), up to {worst:.3g} mm; creases and region borders held"

        def edit(src):
            return _mark(with_parts(src, out), self.name, text)
        return Patch(edit=edit, reason=f"The shell faired: {text}, so it reads as one controlled surface instead of "
                     "lumps.", params={"points": moved, "max_move_mm": round(worst, 3)})


# ---- shape classes ---------------------------------------------------------------------------------------------------

def dims(parts):
    lo, hi = _bbox(parts)
    return lo, hi, hi - lo


def disc_axis(size) -> int | None:
    """The axis of a disc: the shortest side, the other two within 15 % of each other and at least twice it."""
    k = int(np.argmin(size))
    a, b = [size[i] for i in range(3) if i != k]
    if min(a, b) > 0 and abs(a - b) / max(a, b) <= 0.15 and size[k] <= 0.5 * min(a, b):
        return k
    return None


def slab_axis(size) -> int | None:
    """The thin axis of a slab: at most a quarter of the middle side, and the slab stands (z is not the thin side)."""
    order = np.argsort(size)
    k = int(order[0])
    if size[k] <= 0.25 * size[order[1]] and k != 2:
        return k
    return None


def bar_axis(size) -> int | None:
    order = np.argsort(size)[::-1]
    if size[order[0]] >= 2.5 * size[order[1]] and size[order[1]] >= 1.4 * size[order[2]]:
        return int(order[0])
    return None


DISC_WORDS = ("wheel", "tyre", "tire", "rim", "gear", "disc", "disk", "pulley", "hubcap")
BOX_WORDS = ("chest", "crate", "trunk", "coffer", "strongbox", "casket", "box")
SLAB_WORDS = ("wall", "fence", "barrier", "panel", "partition", "gate")
HANDHELD_WORDS = ("remote", "controller", "torch", "flashlight", "handset", "phone", "wand")


# ---- dish --------------------------------------------------------------------------------------------------------------

class DiscDish(Operator):
    """A dished face for a disc: between the hub and the outer ring the face sinks along the axis (nothing at the
    ring), and the hub stands out of the face toward the side it is seen from, so a wheel reads in depth and its
    edge-on outline is not a plain disc. The tyre or outer ring itself is not moved."""
    name = "disc_dish"
    domain = "cage"
    targets = ("interior_read", "silhouette", "surface_breaks")
    cost = 1.0
    label = "Dished face"
    params = {"depth": 0.2, "ring": 0.72, "core": 0.55, "pop": 0.28}

    def _plan(self, design):
        parts = parts_of(design.source)
        if not parts:
            return None
        lo, hi, size = dims(parts)
        k = disc_axis(size)
        if k is None or not (_says(design, DISC_WORDS) or len(parts) > 1):
            return None
        return parts, lo, hi, size, k

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if _done(design, self.name):
            return False, "the face is dished already"
        if self._plan(design) is None:
            return False, "not a disc (a wheel, a rim, a gear)"
        return True, ""

    def apply(self, design, analysis, params):
        plan = self._plan(design)
        if plan is None:
            return None
        parts, lo, hi, size, k = plan
        c = (lo + hi) / 2
        R = 0.5 * float(max(size[i] for i in range(3) if i != k))
        ring = float(params.get("ring", 0.72)) * R
        names = [r for _n, low, _h in parts for r in low.regions]
        for nm in ("tyre", "tire"):                   # a tyre region: the ring starts where it does
            if nm in names:
                rr = []
                for _n, low, _h in parts:
                    for f in low.regions.get(nm, []):
                        q = np.delete(low.V[low.F[int(f)]] - c, k, axis=1)
                        rr.append(float(np.linalg.norm(q, axis=1).min()))
                if rr:
                    ring = min(ring, 0.98 * float(np.percentile(rr, 5)))
        # the face it is seen from: the side the parts that stand out of the main shell lean to (a hub cap, spokes)
        big = max(parts, key=lambda p: len(p[1].F))
        others = [p for p in parts if p is not big]
        lean = np.mean([p[1].V[:, k].mean() for p in others]) - c[k] if others else -1.0
        sign = -1.0 if lean < 0 else 1.0               # outward is sign; the face sinks the other way
        depth = float(params.get("depth", 0.2)) * float(size[k])
        pop = float(params.get("pop", 0.28)) * float(size[k])
        core = float(params.get("core", 0.3)) * ring

        def fn(P, s):
            q = np.delete(P - c, k, axis=1)
            r = np.linalg.norm(q, axis=1)
            cap = 1.0 - smoothstep(0.2 * ring, core, r)          # the hub stands out of the face
            dish = 1.0 - smoothstep(core, ring, r)              # the spokes between sink toward the ring
            P[:, k] += sign * s * (pop * cap - depth * dish * (1.0 - cap))
            return P
        out, s = warp_parts(parts, fn, _frozen_regions(design))
        if out is None:
            return None
        d, h = depth * s, pop * s
        text = (f"the spokes sunk up to {d:.3g} mm inside the {ring:.0f} mm ring and the hub cap {h:.3g} mm out of "
                f"the face, along {'xyz'[k]}")

        def edit(src):
            return _mark(with_parts(src, out), self.name, text)
        return Patch(edit=edit, reason=f"A dished face: {text}, so the wheel reads in depth and its edge-on outline "
                     "is not a plain disc.", params={"axis": "xyz"[k], "depth_mm": round(d, 3), "pop_mm": round(h, 3),
                                                     "ring_mm": round(ring, 2)})


# ---- lid and body massing --------------------------------------------------------------------------------------------

class BandMassing(Operator):
    """A box with a lid steps twice: the lid overhangs the body and its dome rises, the body's walls step in under
    the lid while the foot keeps its width. Lid parts: parts whose regions start with "lid", or every part that lies
    wholly above the seam (the lowest point of the lid regions)."""
    name = "band_massing"
    domain = "cage"
    targets = ("silhouette", "proportion", "interior_read")
    cost = 1.0
    label = "Lid and body massing"
    params = {"overhang": 0.035, "dome": 0.15, "tuck": 0.045, "foot": 0.14}

    def _plan(self, design):
        parts = parts_of(design.source)
        if not parts:
            return None
        # the lid: every part that carries a lid region (its lowest point is the seam)
        lid_z = [float(low.V[:, 2].min()) for _n, low, _h in parts
                 if any(r.startswith("lid") and fs for r, fs in low.regions.items())]
        if not lid_z or not (_says(design, BOX_WORDS) or len(parts) > 1):
            return None
        lo, hi, size = dims(parts)
        seam = min(lid_z)
        if not lo[2] + 0.35 * size[2] < seam < hi[2] - 0.1 * size[2]:
            return None
        return parts, lo, hi, size, seam

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if _done(design, self.name):
            return False, "the lid and body are massed already"
        if self._plan(design) is None:
            return False, "not a box with a lid (a chest, a crate)"
        return True, ""

    def apply(self, design, analysis, params):
        plan = self._plan(design)
        if plan is None:
            return None
        parts, lo, hi, size, seam = plan
        c = (lo + hi) / 2
        ov, dome = float(params.get("overhang", 0.035)), float(params.get("dome", 0.15))
        tuck, foot = float(params.get("tuck", 0.045)), float(params.get("foot", 0.14))
        z0, H = float(lo[2]), float(seam - lo[2])
        eps = 0.02 * size[2]
        lid = {n for n, low, _h in parts if low.V[:, 2].min() >= seam - eps}

        def body_fn(P, s):
            # walls step in above the foot: full width up to foot x height, tuck in over the next sixth
            t = smoothstep(z0 + foot * H, z0 + (foot + 0.16) * H, P[:, 2])
            k = 1.0 - tuck * s * t
            P[:, 0] = c[0] + (P[:, 0] - c[0]) * k
            P[:, 1] = c[1] + (P[:, 1] - c[1]) * k
            return P

        def lid_fn(P, s):
            k = 1.0 + ov * s
            P[:, 0] = c[0] + (P[:, 0] - c[0]) * k
            P[:, 1] = c[1] + (P[:, 1] - c[1]) * k
            P[:, 2] = seam + (P[:, 2] - seam) * (1.0 + dome * s)
            return P
        frozen = _frozen_regions(design)
        out_lid, s1 = warp_parts([p for p in parts if p[0] in lid], lid_fn, frozen)
        out_body, s2 = warp_parts([p for p in parts if p[0] not in lid], body_fn, frozen)
        if out_lid is None or out_body is None:
            return None
        order = {n: i for i, (n, _l, _h) in enumerate(parts)}
        out = sorted(out_lid + out_body, key=lambda p: order[p[0]])
        text = (f"the lid ({len(lid)} parts) {ov * s1 * 100:.3g} % wider and its dome {dome * s1 * 100:.3g} % "
                f"taller, the body's walls {tuck * s2 * 100:.3g} % in above the foot")

        def edit(src):
            return _mark(with_parts(src, out), self.name, text)
        return Patch(edit=edit, reason=f"Lid and body massing: {text}; the outline steps at the foot and under the "
                     "lid instead of reading as a box.", params={"lid_parts": len(lid), "seam_mm": round(seam, 2)})


# ---- piers -----------------------------------------------------------------------------------------------------------

def block(lo, hi, bevel: float) -> _Cage:
    """A closed quad cage of a box from lo to hi with a support loop `bevel` in from every face on each side (a 3 x 3
    grid per face), wound outward: Catmull-Clark rounds it to a box with tight, even edges. One closed manifold
    shell by construction."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    e = np.minimum(float(bevel), 0.3 * (hi - lo))
    ticks = [np.array([lo[i], lo[i] + e[i], hi[i] - e[i], hi[i]]) for i in range(3)]
    index: dict = {}
    V: list = []

    def pt(ix, iy, iz):
        key = (ix, iy, iz)
        if key not in index:
            index[key] = len(V)
            V.append([ticks[0][ix], ticks[1][iy], ticks[2][iz]])
        return index[key]
    F = []
    for axis in range(3):
        for side in (0, 3):
            u, v = [a for a in range(3) if a != axis]
            for a in range(3):
                for b in range(3):
                    quad = []
                    for da, db in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        g = [0, 0, 0]
                        g[axis], g[u], g[v] = side, a + da, b + db
                        quad.append(pt(*g))
                    P = np.asarray([V[i] for i in quad])
                    n = 0.5 * np.cross(P, np.roll(P, -1, axis=0)).sum(0)
                    out = np.zeros(3)
                    out[axis] = 1.0 if side == 3 else -1.0
                    if float(n @ out) < 0:
                        quad = quad[::-1]
                    F.append(quad)
    return _Cage(np.asarray(V), F, (), {})


class PierMassing(Operator):
    """End piers for a slab (a wall kit piece): new closed parts at both ends, proud of both faces and standing above
    the top, inside the slab's footprint along its length (a kit piece stays on its grid), so the slab's outline
    steps in every view. The piers take the region of the slab's top (its coping), so they share its material."""
    name = "pier_massing"
    domain = "cage"
    targets = ("silhouette", "interior_read", "detail_scales")
    cost = 1.5
    label = "End piers"
    params = {"width": 0.12, "proud": 0.3, "rise": 0.06, "bevel": 0.012, "cap": 0.5}

    def _plan(self, design):
        parts = parts_of(design.source)
        if not parts:
            return None
        lo, hi, size = dims(parts)
        k = slab_axis(size)
        if k is None or not _says(design, SLAB_WORDS):
            return None
        return parts, lo, hi, size, k

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if _done(design, self.name):
            return False, "the slab has its piers already"
        if self._plan(design) is None:
            return False, "not a standing slab (a wall, a fence, a panel)"
        return True, ""

    def apply(self, design, analysis, params):
        plan = self._plan(design)
        if plan is None:
            return None
        parts, lo, hi, size, k = plan
        L = 1 - k if k in (0, 1) else 0                 # the slab's length: the other horizontal axis
        w = float(params.get("width", 0.13)) * size[L]
        proud = float(params.get("proud", 0.35)) * size[k]
        rise = float(params.get("rise", 0.05)) * size[2]
        bev = float(params.get("bevel", 0.012)) * min(size[L], size[2])
        # the region the piers take: the region whose faces sit highest (the coping), else none
        top, top_z = None, -math.inf
        for _n, low, _h in parts:
            for r, fs in low.regions.items():
                if r in _frozen_regions(design) or not fs:
                    continue
                z = float(np.mean([low.V[low.F[int(f)]][:, 2].mean() for f in fs]))
                if z > top_z:
                    top, top_z = r, z
        new = []
        names = {n for n, _l, _h in parts}
        i = len(parts)
        for end in (0, 1):
            plo, phi = lo.copy(), hi.copy()
            if end == 0:
                phi[L] = lo[L] + w
            else:
                plo[L] = hi[L] - w
            plo[k] -= proud
            phi[k] += proud
            phi[2] += rise
            # the pier, and a cap on it: wider than the pier by half its proud each way (never past the slab's ends),
            # over its top, so the pier steps once more (a capital) instead of ending in a plain box
            cap = float(params.get("cap", 0.5))
            grow = np.array([cap * proud] * 3)
            grow[2] = 0.0
            clo, chi = plo - grow, phi + grow
            clo[L], chi[L] = max(clo[L], lo[L]), min(chi[L], hi[L])
            clo[2] = phi[2] - 0.6 * rise
            chi[2] = phi[2] + 0.4 * rise
            for b in (block(plo, phi, bev), block(clo, chi, 0.5 * bev)):
                if top:
                    b.regions = {top: list(range(len(b.F)))}
                while f"CAGE_{i}" in names:
                    i += 1
                new.append((f"CAGE_{i}", b, None))
                names.add(f"CAGE_{i}")
                i += 1
        text = (f"two end piers {w:.0f} mm wide, {proud:.0f} mm proud of each face and {rise:.0f} mm above the top, "
                "each with a cap")

        def edit(src):
            return _mark(with_parts(src, parts + new), self.name, text)
        return Patch(edit=edit, reason=f"End piers: {text}; the slab's outline steps in every view instead of "
                     "reading as a flat slab.", params={"width_mm": round(w, 1), "proud_mm": round(proud, 1),
                                                        "rise_mm": round(rise, 1), "region": top})


# ---- bar taper -------------------------------------------------------------------------------------------------------

class BarTaper(Operator):
    """A handheld bar (a remote, a controller) in plan: a waist where the hand closes (at 38 % of the length from the tail by default) and a
    taper to the tail, across the width only, so the outline is an ergonomic profile instead of a plain bar."""
    name = "bar_taper"
    domain = "cage"
    targets = ("silhouette", "proportion", "touch_points")
    cost = 1.0
    label = "Waist and taper"
    params = {"waist": 0.07, "at": 0.38, "spread": 0.2, "taper": 0.06}

    def _plan(self, design):
        parts = parts_of(design.source)
        if not parts or not _says(design, HANDHELD_WORDS):
            return None
        lo, hi, size = dims(parts)
        k = bar_axis(size)
        if k is None:
            return None
        order = np.argsort(size)[::-1]
        return parts, lo, hi, size, k, int(order[1])

    def preconditions(self, design, analysis):
        ok, why = _game_cage(design)
        if not ok:
            return ok, why
        if _done(design, self.name):
            return False, "the bar has its waist already"
        if self._plan(design) is None:
            return False, "not a handheld bar (a remote, a controller)"
        return True, ""

    def apply(self, design, analysis, params):
        plan = self._plan(design)
        if plan is None:
            return None
        parts, lo, hi, size, k, wax = plan
        c = (lo + hi) / 2
        waist, at = float(params.get("waist", 0.07)), float(params.get("at", 0.38))
        spread, taper = float(params.get("spread", 0.2)), float(params.get("taper", 0.06))

        def fn(P, s):
            t = (P[:, k] - lo[k]) / max(size[k], 1e-9)
            g = 1.0 - s * (waist * np.exp(-((t - at) / spread) ** 2) + taper * (1.0 - smoothstep(0.0, 0.6, t)))
            P[:, wax] = c[wax] + (P[:, wax] - c[wax]) * g
            return P
        out, s = warp_parts(parts, fn, _frozen_regions(design))
        if out is None:
            return None
        text = f"a {waist * s * 100:.3g} % waist at {at * 100:.0f} % of the length and a {taper * s * 100:.3g} % taper to the tail"

        def edit(src):
            return _mark(with_parts(src, out), self.name, text)
        return Patch(edit=edit, reason=f"Waist and taper: {text}, in plan.", params={"axis": "xyz"[k]})


OPERATORS = [ShellFairing(), DiscDish(), BandMassing(), PierMassing(), BarTaper()]
