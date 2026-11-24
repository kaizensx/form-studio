"""The refinement engine's evaluator for game assets: a cage design source (CAGE_<i> literals, REFINE_OPS, materials())
measured without a bake, and one bake at the end.

    ev = GameEvaluator(st, p, product_class)
    ev.evaluate([source, ...])    # per candidate: the refined cage (Blender's fixed runner replays REFINE_OPS), its
                                  # level-2 limit mesh for the analysis, LOD0's triangles from the LOD plan, and the
                                  # materials() zones (so material operators show their gain)
    ev.final_check(source)        # one bake: form.game.pipeline.build, then validate.validate and the budgets, and
                                  # the asset's game evidence (bevel coverage, value contrast, worn share)

    refined_cage(source, cfg)     # the cage the game pipeline builds from (form/game/__init__._source_for): the low
                                  # cage with REFINE_OPS replayed, the bake source (high) kept

Candidates are judged on the cage's geometry and materials only (the plan: "game candidates are scored on geometry
only; one bake runs at the end"). At most MAX_BLENDER Blender processes run at once.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path

from .engine import Evaluation, Evaluator, _h

MAX_BLENDER = 2
BUDGETS = [12000, 6000, 2500, 800]
LEVEL = 2
_sem = threading.BoundedSemaphore(MAX_BLENDER)


def _ops_hash(ops) -> str:
    return hashlib.sha1(json.dumps(ops, sort_keys=True, default=str).encode()).hexdigest()[:20]


def refined_cage(source: str, cfg: dict | None = None, cache_dir=None, timeout: float = 180.0):
    """The low cage with the source's REFINE_OPS replayed in Blender (ops_cage.replay), with the original bake
    source (high) kept on it, or None when the source has no REFINE_OPS. Cached by the op list."""
    from ..adapters import blender_model as bm
    from ..game import pipeline
    from .ops_cage import refine_ops_of, replay
    from .. import meshsource
    if not refine_ops_of(source):
        return None
    ops = replay(source)
    f = Path(cache_dir) / f"{_ops_hash(ops)}.json" if cache_dir else None
    cage = None
    if f is not None and f.is_file():
        try:
            cage = meshsource.CageData.load(f)
        except Exception:                                    # noqa: BLE001 - a bad cache file: replay again
            cage = None
    if cage is None:
        with _sem:
            cage = bm.run_ops(ops, cfg=cfg, timeout=timeout)["cage"]
        if f is not None:
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                cage.save(f)
            except OSError:
                pass
    orig = pipeline.merge_cages(pipeline.cages_in_source(source))
    hi = pipeline.high_of(orig)
    if hi is not None:
        try:
            cage.high = hi                     # the bake detail stays; the refine ops change the low cage only
        except AttributeError:
            pass
    return cage


def _mesh(cage):
    """The cage's level-2 subdivision as triangles, and the cage region each triangle comes from ("body" when none)."""
    import numpy as np
    from ..craft import subd
    from .. import meshsource
    V, Q, _cr, parent = subd.subdivide(cage.V, cage.F, meshsource.subd_creases(cage.creases), levels=LEVEL)
    Q = np.asarray(Q, dtype=np.int64)
    T = np.concatenate([Q[:, [0, 1, 2]], Q[:, [0, 2, 3]]])
    region = np.full(len(cage.F), "body", dtype=object)
    for name, fs in sorted((cage.regions or {}).items()):
        for f in fs:
            if 0 <= int(f) < len(region) and region[int(f)] == "body":
                region[int(f)] = name
    lab = region[np.asarray(parent, dtype=np.int64)]
    return np.asarray(V, float), T, list(np.concatenate([lab, lab]))


FEATURE_DEG, HARD_DEG = 20.0, 55.0


def edge_coverage(P, T) -> float:
    """A bake-free stand-in for the game critic's bevel coverage: of the limit surface's feature-edge length (turns
    over FEATURE_DEG), the share that is not a raw hard edge (over HARD_DEG). Support loops and bevels turn the
    surface in steps; a bare crease turns it at once."""
    from .analyze import _edge_table
    L, ang, _a, _b = _edge_table(P, T)
    feat = float(L[ang > FEATURE_DEG].sum())
    if feat <= 0:
        return 1.0
    return round(1.0 - float(L[ang > HARD_DEG].sum()) / feat, 4)


def zones_of(source: str) -> list:
    """materials() as appearance-like zones for the analysis: one per region (and "default")."""
    from ..game import materials as matlib
    mats, _note = matlib.materials_in_source(source or "")
    out = []
    for k, m in (mats or {}).items():
        if not isinstance(m, dict):
            continue
        out.append({"features": [k], "color": m.get("tint") or m.get("color") or "#b8b2a7",
                    "finish": m.get("material") or m.get("finish") or "matte"})
    return out


class GameEvaluator(Evaluator):
    purpose = "game"

    def __init__(self, st, p: dict, product_class: str | None = None, frozen: set | None = None,
                 budgets: list | None = None, preset: str = "gltf", texture_px: int = 1024, bake: str = "fast"):
        self.st, self.p = st, p
        self.product_class = product_class
        self.frozen = set(frozen or ())
        self.budgets = list(budgets or BUDGETS)
        self.preset, self.texture_px, self.bake = preset, texture_px, bake
        self.weights = None
        self.cache = Path(st.root) / ".cache" / "refine_cage"
        self._memo: dict = {}
        self._geo: dict = {}
        self.stats = {"measured": 0, "geometry_reused": 0, "memo": 0, "blender_runs": 0}

    def _cage(self, src: str):
        from ..game import pipeline
        from .ops_cage import refine_ops_of
        if not refine_ops_of(src):
            cs = pipeline.cages_in_source(src)
            if not cs:
                raise ValueError("the source holds no cage")
            return pipeline.merge_cages(cs)
        self.stats["blender_runs"] += 1
        return refined_cage(src, getattr(self.st, "cfg", None), self.cache)

    def _measure(self, src: str) -> Evaluation:
        from ..game import lod as lodmod
        from .analyze import Measurement, analyze
        t0 = time.time()
        h = _h(src)
        if h in self._memo:
            self.stats["memo"] += 1
            return self._memo[h]
        gk = geometry_key(src)
        geo = self._geo.get(gk)
        if geo is None:
            cage = self._cage(src)
            P, T, lab = _mesh(cage)
            plan = lodmod.plan_lods(cage.F, self.budgets)
            geo = {"P": P, "T": T, "tf": lab, "tris": int(plan[0]["expected_tris"]), "cage": cage,
                   "coverage": edge_coverage(P, T)}
            self._geo[gk] = geo
            self.stats["measured"] += 1
        else:
            self.stats["geometry_reused"] += 1
        a = analyze(Measurement(geo["P"], geo["T"], tri_feature=geo["tf"], zones=zones_of(src), purpose="game",
                                game={"edges": {"coverage": geo["coverage"]}}, product_class=self.product_class),
                    weights=self.weights)
        lo, hi = geo["P"].min(0), geo["P"].max(0)
        out = Evaluation(ok=True, analysis=a, checks=None, frozen=None, wall_mm=None, triangles=geo["tris"],
                         bbox=(tuple(lo.tolist()), tuple(hi.tolist())), seconds=round(time.time() - t0, 2),
                         extra={"faces": len(geo["cage"].F)})
        self._memo[h] = out
        return out

    def measure_base(self, src: str) -> Evaluation:
        try:
            return self._measure(src)
        except Exception as e:                                  # noqa: BLE001
            return Evaluation(ok=False, error=f"{type(e).__name__}: {e}"[:300])

    def evaluate(self, sources, timeout=None):
        from concurrent.futures import ThreadPoolExecutor
        results: list = [None] * len(sources)

        def one(i):
            try:
                results[i] = self._measure(sources[i])
            except Exception as e:                              # noqa: BLE001 - a candidate that does not replay
                results[i] = Evaluation(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        th = threading.Thread(target=lambda: list(ThreadPoolExecutor(max_workers=MAX_BLENDER).map(one, range(len(sources)))),
                              daemon=True, name="refine-game-batch")
        th.start()
        th.join(None if timeout is None else max(1.0, float(timeout)))
        return [r if r is not None else Evaluation(ok=False, error="over the time budget") for r in results]

    def final_check(self, source: str) -> Evaluation | None:
        """One bake of the refined asset: the validator, the budgets and the game evidence (worn share included)."""
        from .. import critique
        from ..game import materials as matlib
        from ..game import pipeline
        from .analyze import Measurement, analyze
        try:
            cage = self._cage(source)
            mats, _n = matlib.materials_in_source(source)
            out = Path(tempfile.mkdtemp(prefix="form-refine-bake-"))
            with _sem:
                rep = pipeline.build({"cage": cage, "materials": mats}, out / "asset", asset="refine",
                                     preset=self.preset, budgets=self.budgets, texture_px=self.texture_px,
                                     bake=self.bake, cfg=getattr(self.st, "cfg", None))
        except Exception as e:                                  # noqa: BLE001 - a result that does not bake fails
            return Evaluation(ok=False, error=f"the bake failed: {type(e).__name__}: {e}"[:300])
        gdir = out / "asset"
        ev = critique.game_evidence(gdir)
        base = self._measure(source)
        geo = self._geo[geometry_key(source)]
        a = analyze(Measurement(geo["P"], geo["T"], tri_feature=geo["tf"], zones=zones_of(source), game=ev,
                                purpose="game", product_class=self.product_class), weights=self.weights)
        lods = rep.get("lods") or []
        return Evaluation(ok=True, analysis=a, game=rep.get("validation"), triangles=lods[0]["triangles"] if lods else None,
                          bbox=base.bbox, extra={"dir": str(gdir), "evidence": ev})


def geometry_key(source: str) -> str:
    """What the cage geometry depends on: the CAGE_<i> literals and REFINE_OPS (not materials())."""
    from .ops_cage import cages_of, refine_ops_of
    return _ops_hash([cages_of(source), refine_ops_of(source)])
