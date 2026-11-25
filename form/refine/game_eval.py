"""The refinement engine's evaluator for game assets: a cage design source (CAGE_<i> literals, REFINE_OPS, materials())
measured the way its asset will look, a quick bake per candidate, and one full bake at the end.

    ev = GameEvaluator(st, p, product_class)
    ev.evaluate([source, ...])    # per candidate: the refined cage (Blender's fixed runner replays REFINE_OPS on the
                                  # low cage and on the bake source), its level-2 limit mesh for the geometric
                                  # measures, and a quick bake (QUICK_PX px maps, few samples: form.game.pipeline with
                                  # bake="preview") whose game evidence (bevel coverage, value contrast, detail scales,
                                  # wear, the lit read with the baked base colour) drives the analysis, so a panel
                                  # line, a trim or a kit part counts for what it does once baked
    ev.final_check(source)        # one full bake: form.game.pipeline.build, then validate.validate and the budgets

    refined_cage(source, cfg)     # the cage the game pipeline builds from (form/game/__init__._source_for): the low
                                  # cage with REFINE_OPS replayed, and the bake source (high) with the same ops
                                  # replayed on it, so the bake carries the refinement instead of flattening it

Without the quick bake (quick=False) candidates are judged on the cage's geometry and materials only, with a
bake-free stand-in for the bevel coverage (edge_coverage). At most MAX_BLENDER Blender processes run at once.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .engine import Evaluation, Evaluator, _h

MAX_BLENDER = 2
BUDGETS = [12000, 6000, 2500, 800]
LEVEL = 2
QUICK_PX = 256
_sem = threading.BoundedSemaphore(MAX_BLENDER)


def _ops_hash(ops) -> str:
    return hashlib.sha1(json.dumps(ops, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _run_cached(ops, cfg, cache_dir, timeout):
    from ..adapters import blender_model as bm
    from .. import meshsource
    f = Path(cache_dir) / f"{_ops_hash(ops)}.json" if cache_dir else None
    if f is not None and f.is_file():
        try:
            return meshsource.CageData.load(f)
        except Exception:                                    # noqa: BLE001 - a bad cache file: replay again
            pass
    with _sem:
        cage = bm.run_ops(ops, cfg=cfg, timeout=timeout)["cage"]
    if f is not None:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            cage.save(f)
        except OSError:
            pass
    return cage


def high_ops(source: str):
    """The op list that rebuilds the bake source with the refinement on it: cage_new with the high cage's points,
    faces, regions and creases, then the REFINE_OPS that change geometry. None when the source has no bake source."""
    from ..exemplars.game.base import Block, start
    from ..game import pipeline
    from .ops_cage import refine_ops_of
    orig = pipeline.merge_cages(pipeline.cages_in_source(source))
    hi = pipeline.high_of(orig)
    if hi is None:
        return None
    ops = [o for o in refine_ops_of(source) if not o.get("high_only")]
    return start([Block(hi.V, hi.F, hi.creases, hi.regions)]) + ops


def refined_cage(source: str, cfg: dict | None = None, cache_dir=None, timeout: float = 180.0):
    """The low cage with the source's REFINE_OPS replayed in Blender (ops_cage.replay), and its bake source (high)
    with the same ops replayed on the high cage (high_ops), or None when the source has no REFINE_OPS. A refinement
    that only changed the low cage would be undone by the bake: the normal map carries the high's surface, so a
    groove cut in the low and missing from the high bakes flat. When an op cannot replay on the high (a selection
    that is empty there), the design's own bake source is kept (cage.high_note says so). Cached by the op lists."""
    from ..game import pipeline
    from .ops_cage import refine_ops_of, replay
    if not refine_ops_of(source):
        return None
    cage = _run_cached(replay(source), cfg, cache_dir, timeout)
    orig = pipeline.merge_cages(pipeline.cages_in_source(source))
    hi = pipeline.high_of(orig)
    note = None
    if hi is not None:
        hops = high_ops(source)
        try:
            hi = _run_cached(hops, cfg, cache_dir, timeout)
            note = "the bake source carries the refinement"
        except Exception as e:                               # noqa: BLE001 - the design's own bake source, as before
            note = f"the refinement did not replay on the bake source ({type(e).__name__}); its own is kept"
        try:
            cage.high = hi
        except AttributeError:
            pass
    try:
        cage.high_note = note
    except AttributeError:
        pass
    return cage


def _with_validation(ev: dict, asset_dir) -> dict:
    """The game evidence with the build's validator report (report.json "validation") as ev["validation"]."""
    try:
        ev["validation"] = json.loads((Path(asset_dir) / "report.json").read_text(encoding="utf-8")).get("validation")
    except (OSError, ValueError):
        ev["validation"] = None
    return ev


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
                 budgets: list | None = None, preset: str = "gltf", texture_px: int = 1024, bake: str = "fast",
                 quick: bool = True):
        self.st, self.p = st, p
        self.product_class = product_class
        self.frozen = set(frozen or ())
        self.budgets = list(budgets or BUDGETS)
        self.preset, self.texture_px, self.bake = preset, texture_px, bake
        self.quick = bool(quick)
        self.weights = None
        self.cache = Path(st.root) / ".cache" / "refine_cage"
        self.qcache = Path(st.root) / ".cache" / "refine_quick"
        self._memo: dict = {}
        self._geo: dict = {}
        self._quick: dict = {}
        self.stats = {"measured": 0, "geometry_reused": 0, "memo": 0, "blender_runs": 0, "quick_bakes": 0,
                      "quick_seconds": 0.0, "quick_errors": 0}

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

    def quick_evidence(self, src: str, cage) -> dict | None:
        """The game evidence of a quick bake of the candidate (pipeline.build, bake "preview", QUICK_PX px, no
        collision), cached by its geometry and materials. None when the bake fails (the candidate is then judged on
        its geometry, as without the quick bake)."""
        from .. import critique
        from ..game import materials as matlib
        from ..game import pipeline
        mats, _n = matlib.materials_in_source(src)
        k = _ops_hash([geometry_key(src), mats, self.budgets])
        if k in self._quick:
            return self._quick[k]
        d = self.qcache / k
        ev = None
        if (d / "report.json").is_file():
            try:
                ev = _with_validation(critique.game_evidence(d), d)
            except Exception:                                   # noqa: BLE001 - bake it again
                ev = None
        if ev is None:
            t0 = time.time()
            tmp = Path(tempfile.mkdtemp(prefix="form-refine-quick-"))
            try:
                with _sem:
                    pipeline.build({"cage": cage, "materials": mats}, tmp / "a", asset="quick", preset="gltf",
                                   budgets=self.budgets, texture_px=QUICK_PX, bake="preview", collision="none",
                                   cfg=getattr(self.st, "cfg", None))
                ev = _with_validation(critique.game_evidence(tmp / "a"), tmp / "a")
                self.stats["quick_bakes"] += 1
                try:
                    if d.exists():
                        shutil.rmtree(d, ignore_errors=True)
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp / "a"), str(d))
                except OSError:
                    pass
            except Exception:                                   # noqa: BLE001
                self.stats["quick_errors"] += 1
                ev = None
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
                self.stats["quick_seconds"] = round(self.stats["quick_seconds"] + time.time() - t0, 1)
        self._quick[k] = ev
        return ev

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
        game = self.quick_evidence(src, geo["cage"]) if self.quick else None
        validation = None
        if game is None:
            game = {"edges": {"coverage": geo["coverage"]}}
        else:
            # the quick bake's own validator (closed and manifold LODs, no flipped faces, ...): a candidate that would
            # fail the final bake is rejected here, not after the search has built on it
            validation = game.get("validation")
        a = analyze(Measurement(geo["P"], geo["T"], tri_feature=geo["tf"], zones=zones_of(src), purpose="game",
                                game=game, product_class=self.product_class), weights=self.weights)
        lo, hi = geo["P"].min(0), geo["P"].max(0)
        out = Evaluation(ok=True, analysis=a, checks=None, frozen=None, wall_mm=None, triangles=geo["tris"],
                         game=validation, bbox=(tuple(lo.tolist()), tuple(hi.tolist())), seconds=round(time.time() - t0, 2),
                         extra={"faces": len(geo["cage"].F), "quick": bool(game.get("dir"))})
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
        """One full bake of the refined asset: the validator, the budgets and the game evidence (worn share
        included)."""
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
