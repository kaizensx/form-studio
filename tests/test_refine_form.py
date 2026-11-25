"""Primary-form operators (form/refine/ops_form.py), the fairness measure, and LOD-robust cage operators.

Always run: the fairness measure, every primary-form operator on small cages (closed manifold by construction, frozen
regions held, deterministic, the source still a cage source). With Blender: every detail operator (ops_cage) replayed
strict on the helmet exemplar, whose cage has zero-length edges beside its visor (a panel line there folded into
coincident points before), leaves a closed, manifold, consistently wound cage; and the quick bake of the kit rivets
that collapsed inside out at LOD3 passes the validator's geometric checks on every LOD."""
import math
import unittest

import numpy as np

from form import meshsource, refine
from form.adapters import blender as bl
from form.game import validate as gv
from form.refine import Analysis, Design, ops_form
from form.refine.analyze import fairness

HAS_BLENDER = bl.resolve({})["available"]


def _tris(V, F):
    return np.asarray(V, float), np.array([(f[0], f[k], f[k + 1]) for f in F for k in range(1, len(f) - 1)])


def _closed(V, F) -> dict:
    P, T = _tris(V, F)
    Pw, Tw = gv.weld(P, T)
    es = gv.edge_stats(Tw)
    return {**es, "volume": sum(gv.signed_volumes(Pw, Tw)), "coincident": len(P) - len(Pw)}


def _sphere(n=24, bumps=0.0):
    from form.exemplars.game.base import box
    b = box(np.linspace(-1, 1, n // 4 + 1), np.linspace(-1, 1, n // 4 + 1), np.linspace(-1, 1, n // 4 + 1), crease=0)
    V = b.V / np.linalg.norm(b.V, axis=1, keepdims=True) * 50.0
    if bumps:
        rng = np.random.default_rng(3)
        V = V * (1.0 + bumps * rng.standard_normal(len(V)))[:, None]
    return meshsource.cage(V, b.F, [], {})


def _source_of(*cages, materials=None):
    from form.exemplars.game.base import literal
    lits = "".join(literal(c, f"CAGE_{i}") for i, c in enumerate(cages))
    names = ", ".join(f"CAGE_{i}" for i in range(len(cages)))
    return f'"""test"""\nfrom form import meshsource\n\n{lits}CAGES = [{names}]\n'


def _design(src, brief="", frozen=()):
    V = np.concatenate([np.asarray(c.V) for c in __import__("form.game.pipeline", fromlist=["x"]).cages_in_source(src)])
    feats = {f: {"role": "fit"} for f in frozen}
    return Design(source=src, purpose="game", brief=brief, features=feats, bbox=(tuple(V.min(0)), tuple(V.max(0))))


def _limit(src):
    from form.game import pipeline
    from form.refine import game_eval
    P, T, _l = game_eval._mesh(pipeline.merge_cages(pipeline.cages_in_source(src)))
    return P, T


ANALYSIS = Analysis(deficits={k: 0.8 for k in refine.DEFICITS}, measures={})


class Fairness(unittest.TestCase):
    def test_lumpy_shell_measures_worse_than_a_fair_one(self):
        fair = fairness(*_limit(_source_of(_sphere())))
        lumpy = fairness(*_limit(_source_of(_sphere(bumps=0.06))))
        self.assertLess(fair["wobble"], lumpy["wobble"])
        self.assertLess(fair["deficit"], lumpy["deficit"])
        self.assertGreater(lumpy["deficit"], 0.3)

    def test_registered(self):
        self.assertIn("fairness", refine.DEFICITS)
        names = {o.name for o in refine.operators("cage")}
        self.assertTrue({"shell_fairing", "disc_dish", "band_massing", "pier_massing", "bar_taper"} <= names)


class Literals(unittest.TestCase):
    def test_parts_roundtrip(self):
        src = _source_of(_sphere(), _sphere())
        parts = ops_form.parts_of(src)
        self.assertEqual([p[0] for p in parts], ["CAGE_0", "CAGE_1"])
        out = ops_form.with_parts(src, parts + [("CAGE_2", ops_form.block([0, 0, 0], [10, 10, 10], 1.0), None)])
        compile(out, "<src>", "exec")
        self.assertEqual(len(ops_form.parts_of(out)), 3)
        self.assertIn("CAGES = [CAGE_0, CAGE_1, CAGE_2]", out)

    def test_block_is_one_closed_shell_wound_out(self):
        b = ops_form.block([0, 0, 0], [40, 20, 100], 2.0)
        st = _closed(b.V, b.F)
        self.assertEqual((st["open"], st["nonmanifold"], st["inconsistent"], st["coincident"]), (0, 0, 0, 0))
        self.assertAlmostEqual(st["volume"], 40 * 20 * 100, delta=1.0)
        self.assertTrue(all(len(f) == 4 for f in b.F))

    def test_carry_moves_points_on_low_points_exactly(self):
        low0 = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], float)
        low1 = low0 + [[1, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]]
        out = ops_form.carry(low0, low1, np.array([[0, 0, 0], [5, 5, 5]], float), k=4)
        self.assertTrue(np.allclose(out[0], [1, 0, 0]))
        self.assertGreater(out[1][0], 5.0)


def _assert_sound_patch(case, op, d, src):
    p = op.apply(d, ANALYSIS, dict(op.params))
    case.assertIsNotNone(p, op.name)
    out = p.edit(src)
    case.assertEqual(out, op.apply(d, ANALYSIS, dict(op.params)).edit(src), op.name)        # deterministic
    compile(out, "<src>", "exec")
    before = {n: low for n, low, _h in ops_form.parts_of(src)}
    for name, low, high in ops_form.parts_of(out):
        st = _closed(low.V, low.F)
        case.assertEqual((st["open"], st["nonmanifold"], st["inconsistent"]), (0, 0, 0), (op.name, name))
        case.assertGreater(st["volume"], 0, (op.name, name))
        if name in before:
            case.assertEqual(low.F, before[name].F, op.name)                    # faces never change
            case.assertEqual(ops_form.folded(before[name].V, low.V, low.F), 0, op.name)
    case.assertTrue(p.reason)
    case.assertFalse(op.check(_design(out, d.brief), ANALYSIS)[0], f"{op.name} runs once")
    return out


class Operators(unittest.TestCase):
    def test_contract(self):
        for op in ops_form.OPERATORS:
            self.assertEqual(op.domain, "cage")
            self.assertTrue(set(op.targets) <= set(refine.DEFICITS), op.name)
            model = Design(source=_source_of(_sphere()), purpose="model")
            self.assertFalse(op.check(model, ANALYSIS)[0], op.name)

    def test_fairing_smooths_and_holds_creases_and_frozen(self):
        c = _sphere(bumps=0.05)
        F = c.F
        creased = [(F[0][0], F[0][1], 1.0)]
        c = meshsource.cage(c.V, F, [list(x) for x in creased], {"latch": [5]})
        src = _source_of(c)
        d = _design(src, frozen=("latch",))
        op = ops_form.ShellFairing()
        out = _assert_sound_patch(self, op, d, src)
        (_n, low, _h), = ops_form.parts_of(out)
        V0 = np.asarray(c.V)
        for i in (F[0][0], F[0][1], *F[5]):
            self.assertTrue(np.allclose(low.V[i], V0[i], atol=0.011))           # held (literals keep 0.01 mm)
        self.assertLess(fairness(*_limit(out))["wobble"], fairness(*_limit(src))["wobble"])

    def test_dish_sinks_the_spokes_and_lifts_the_hub(self):
        from form.exemplars.game.base import box
        ring = _sphere()
        V = np.asarray(ring.V) * [3.0, 0.8, 3.0]                               # a fat disc, axis y
        hub = box([-20, 20], [-60, -10], [-20, 20], crease=0)
        rf = [i for i, f in enumerate(ring.F) if np.hypot(*V[f][:, [0, 2]].mean(0)) > 0.75 * 150]
        src = _source_of(meshsource.cage(V, ring.F, [], {"tyre": rf}),
                         meshsource.cage(hub.V, hub.F, [], {"hub": list(range(len(hub.F)))}))
        d = _design(src, "a wheel for a cart")
        op = ops_form.DiscDish()
        self.assertTrue(op.check(d, ANALYSIS)[0])
        out = _assert_sound_patch(self, op, d, src)
        parts = ops_form.parts_of(out)
        r = np.hypot(V[:, 0], V[:, 2])
        outer = r > 0.99 * 150.0 * 0.72
        self.assertTrue(np.allclose(parts[0][1].V[outer], V[outer], atol=0.011))   # the outer ring is not moved
        mid = (r > 0.6 * 108) & (r < 0.9 * 108) & (V[:, 1] < 0)
        self.assertGreater(parts[0][1].V[mid][:, 1].mean(), V[mid][:, 1].mean() + 0.5)   # the face sinks (+y: in)
        self.assertLess(parts[1][1].V[:, 1].mean(), hub.V[:, 1].mean() - 1.0)     # the hub stands out (-y)

    def test_band_massing_steps_lid_and_body(self):
        from form.exemplars.game.base import box
        body = box([-100, 100], [-60, 60], [0, 40, 80, 120], crease=0)
        lid = box([-100, 100], [-60, 60], [120, 170], crease=0)
        src = _source_of(meshsource.cage(body.V, body.F, [], {"plank_0": list(range(len(body.F)))}),
                         meshsource.cage(lid.V, lid.F, [], {"lid_0": list(range(len(lid.F)))}))
        d = _design(src, "a treasure chest")
        op = ops_form.BandMassing()
        self.assertTrue(op.check(d, ANALYSIS)[0])
        out = _assert_sound_patch(self, op, d, src)
        (_a, b1, _h1), (_b, l1, _h2) = ops_form.parts_of(out)
        self.assertGreater(l1.V[:, 0].max(), 100.0)                             # the lid overhangs
        self.assertGreater(l1.V[:, 2].max(), 170.0)                             # and its dome rises
        top = b1.V[b1.V[:, 2] > 100]
        self.assertLess(top[:, 0].max(), 100.0)                                 # the walls step in under it
        self.assertAlmostEqual(b1.V[b1.V[:, 2] < 1][:, 0].max(), 100.0)          # the foot keeps its width

    def test_piers_stay_inside_the_grid(self):
        from form.exemplars.game.base import box
        wall = box([-1000, 1000], [-150, 150], [0, 2400], crease=0)
        src = _source_of(meshsource.cage(wall.V, wall.F, [], {"coping": list(range(len(wall.F)))}))
        d = _design(src, "a modular dungeon wall piece")
        op = ops_form.PierMassing()
        self.assertTrue(op.check(d, ANALYSIS)[0])
        out = _assert_sound_patch(self, op, d, src)
        V = np.concatenate([low.V for _n, low, _h in ops_form.parts_of(out)])
        self.assertGreaterEqual(V[:, 0].min(), -1000.0 - 1e-6)                  # along the length: on the grid
        self.assertLessEqual(V[:, 0].max(), 1000.0 + 1e-6)
        self.assertGreater(V[:, 2].max(), 2400.0)                               # the piers stand above the top
        self.assertGreater(V[:, 1].max(), 150.0)                                # and proud of the faces
        self.assertEqual(len(ops_form.parts_of(out)), 5)

    def test_taper_only_for_a_handheld_bar(self):
        from form.exemplars.game.base import box
        bar = box(np.linspace(-95, 95, 9), [-25, 25], [0, 21], crease=0)
        src = _source_of(meshsource.cage(bar.V, bar.F, [], {}))
        op = ops_form.BarTaper()
        self.assertFalse(op.check(_design(src, "a sword with a wrapped grip"), ANALYSIS)[0])
        d = _design(src, "a tv remote")
        self.assertTrue(op.check(d, ANALYSIS)[0])
        out = _assert_sound_patch(self, op, d, src)
        (_n, low, _h), = ops_form.parts_of(out)
        mid = low.V[np.abs(low.V[:, 0] - (-95 + 0.38 * 190)) < 15]
        self.assertLess(np.abs(mid[:, 1]).max(), 25.0)                          # the waist


@unittest.skipUnless(HAS_BLENDER, "Blender is not installed")
class LodRobust(unittest.TestCase):
    """Every detail operator on the helmet replays strict to a closed, manifold, consistently wound cage."""

    @classmethod
    def setUpClass(cls):
        from form.exemplars.game import base, module
        from form.game import pipeline
        m = module("scifi_helmet")
        cls.m = m
        cls.src = base.design_source(base.build(m.ops()), m.TITLE, m.MATERIALS)
        V = np.concatenate([np.asarray(c.V) for c in pipeline.cages_in_source(cls.src)])
        cls.d = Design(source=cls.src, purpose="game", bbox=(tuple(V.min(0)), tuple(V.max(0))))

    def _refined(self, name):
        from form.refine import game_eval, ops_cage
        op = {o.name: o for o in ops_cage.OPERATORS}[name]
        p = op.apply(self.d, None, dict(op.params))
        self.assertIsNotNone(p, name)
        return game_eval.refined_cage(p.edit(self.src), None, None)

    def test_every_detail_operator_replays_closed_and_manifold(self):
        for name in ("panel_line", "crisp_regions", "inset", "trim_strip", "support_loops", "kit_place"):
            with self.subTest(op=name):
                cage = self._refined(name)
                st = _closed(cage.V, cage.F)
                self.assertEqual((st["open"], st["nonmanifold"], st["inconsistent"]), (0, 0, 0), name)

    def test_panel_line_by_the_zero_length_edge_does_not_fold(self):
        cage = self._refined("panel_line")
        V = np.asarray(cage.V, float)
        E = {(min(a, b), max(a, b)) for f in cage.F for a, b in zip(f, f[1:] + f[:1])}
        tol = 1e-6 * float(np.linalg.norm(V.max(0) - V.min(0)))
        self.assertEqual(sum(1 for a, b in E if np.linalg.norm(V[a] - V[b]) <= tol), 0)

    def test_kit_rivets_bake_sound_lods(self):
        import tempfile
        from pathlib import Path
        from form.game import pipeline
        cage = self._refined("kit_place")
        out = Path(tempfile.mkdtemp(prefix="form-test-lod-")) / "a"
        rep = pipeline.build({"cage": cage, "materials": self.m.MATERIALS}, out, asset="t", preset="gltf",
                             budgets=[10000, 5000, 2000, 600], texture_px=256, bake="preview", collision="none")
        bad = [(c["id"], c.get("lod"), c["value"]) for c in rep["validation"]["checks"]
               if c["id"] in ("manifold", "normals") and c["status"] != "PASS"]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
