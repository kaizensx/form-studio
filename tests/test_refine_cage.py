"""Cage refinement operators (form/refine/ops_cage.py) and the game exemplars they fix.

The planner, operator and schema tests always run. The Blender tests run the ops in the fixed runner and skip cleanly
without Blender: support loops with pinned corners (true corners, no pills), a Geometry Nodes ring of kit parts at a
constant pitch, and the WP3 acceptance numbers on the exemplars (wall brick corner radius under 15 % of the brick's
short side, helmet 64 px convexity deficit at least double the old one, tread pitch spread under 5 %)."""
import math
import unittest

import numpy as np

from form import meshsource, refine
from form.adapters import blender as bl
from form.adapters import blender_model as bm
from form.refine import Analysis, Design, ops_cage

HAS_BLENDER = bl.resolve({})["available"]
HELMET_BEFORE = 0.0488            # LOD0 of the helmet before WP3 (game bench, 2026-11-24, Blender 5.2.3)


def _crease_map(cage):
    return {(min(a, b), max(a, b)): s for a, b, s in cage.creases}


class Planners(unittest.TestCase):
    def test_rhythm_three_sizes_constant_motif(self):
        r = ops_cage.rhythm(9)
        self.assertEqual(sorted(set(r), reverse=True), [1.0, 0.38, 0.15])
        self.assertEqual(r[0], 1.0)
        self.assertEqual(r[-1], 1.0)
        self.assertEqual(r[:4], [1.0, 0.15, 0.38, 0.15])
        with self.assertRaises(ValueError):
            ops_cage.rhythm(4, (0.2, 0.5, 1.0))

    def test_kit_line_constant_pitch_and_frozen_boxes(self):
        ops = ops_cage.kit_line("rivet_dome", {"diameter": 6.0}, [0, 0, 0], [80, 0, 0], [0, 0, 1], count=9,
                                frozen_boxes=[((35, -1, -1), (45, 1, 1))])
        pts = sorted(p[0] for o in ops for p in o["at"])
        self.assertNotIn(40.0, pts)                                  # the frozen slot is dropped
        self.assertEqual(len(pts), 8)
        steps = np.diff([0.0, 10.0, 20.0, 30.0, 50.0, 60.0, 70.0, 80.0])
        self.assertTrue(np.allclose(np.diff(pts), steps))           # the others keep the pitch
        self.assertEqual([o["scale"] for o in ops], [1.0, 0.38, 0.15])
        for o in bm.validate_ops([{"op": "cage_new", "primitive": "cube"}] + ops)[1:]:
            self.assertEqual(o["op"], "kit_place")

    def test_crisp_and_ring_validate(self):
        ops = [{"op": "cage_new", "primitive": "cube", "size": [40, 30, 20]},
               {"op": "name_region", "name": "top", "faces": {"normal": [0, 0, 1], "within_deg": 5}}]
        ops += ops_cage.crisp("top", 2.0)
        ops.append(ops_cage.kit_ring("tread_block", {}, [[20, 0, 0]], [1, 0, 0], "y", 12, name="lugs"))
        ops.append({"op": "inset", "faces": {"region": "top", "box": [[-5, -5, 9], [5, 5, 11]]}, "thickness": 1.0})
        norm = bm.validate_ops(ops)
        self.assertEqual(norm[-1]["faces"]["box"], [[-5.0, -5.0, 9.0], [5.0, 5.0, 11.0]])
        norm = norm[:-1]
        self.assertTrue(norm[-3]["pin_corners"])                            # the crease
        self.assertTrue(norm[-2]["pin_corners"])                            # the support loops
        self.assertEqual(norm[-1]["count"], 12)
        ex = bm.expand(norm[-1])
        self.assertIn("mesh", ex)
        self.assertEqual(bm.op_key(ops, "5.2.3"), bm.op_key(ops, "5.2.3"))
        ring = ops[-2]
        with self.assertRaises(bm.OpError):
            bm.validate_ops(ops[:-2] + [dict(ring, count=300)])
        with self.assertRaises(bm.OpError):
            bm.validate_ops(ops[:-2] + [dict(ring, axis="w")])

    def test_breakers_rank_by_blob_views(self):
        from form.exemplars.game.base import quad_sphere
        s = quad_sphere(4, (100, 100, 100))
        P, T = ops_cage.triangles(s.V, s.F)
        a, b = ops_cage.breakers(P, T), ops_cage.breakers(P, T)
        self.assertEqual(a, b)
        self.assertTrue(all(n > 0.4 for _k, n in a))                # a sphere reads as a blob from every view
        op = ops_cage.breaker_op("vent", "side", 10.0, sign=-1)
        self.assertEqual(op["vector"], [-10.0, 0.0, 0.0])

    def test_pitch_variance(self):
        self.assertAlmostEqual(ops_cage.pitch_variance([0, 90, 180, 270]), 0.0)
        self.assertGreater(ops_cage.pitch_variance([0, 10, 180, 270]), 0.3)


def _source():
    from form.exemplars.game.base import box, design_source
    b = box([0, 20, 40], [0, 20], [0, 10]).region("panel", [0, 1])
    c = meshsource.cage(b.V, b.F, [[a, c2, w] for a, c2, w in b.creases], b.regions)
    return design_source(c, "Test block")


class Operators(unittest.TestCase):
    def test_registered_as_cage_ops(self):
        names = {o.name for o in refine.operators("cage")}
        self.assertTrue({"support_loops", "panel_line", "trim_strip", "inset", "kit_place",
                         "silhouette_breaker"} <= names)

    def test_source_hook_roundtrip_and_replay(self):
        src = _source()
        self.assertEqual(list(ops_cage.cages_of(src)), ["CAGE_0"])
        self.assertEqual(ops_cage.refine_ops_of(src), [])
        s2 = ops_cage.with_refine_ops(src, [{"op": "crease", "region_boundary": "panel", "value": 1.0}])
        s3 = ops_cage.with_refine_ops(s2, ops_cage.refine_ops_of(s2) + [{"op": "support_loops",
                                                                         "edges": {"creased": True},
                                                                         "distance": 1.0}])
        self.assertEqual(len(ops_cage.refine_ops_of(s3)), 2)
        compile(s3, "<src>", "exec")
        ops = ops_cage.replay(s3)
        self.assertEqual(ops[0]["op"], "cage_new")
        bm.validate_ops(ops)

    def test_operators_follow_the_contract(self):
        src = _source()
        an = Analysis(deficits={k: 0.8 for k in refine.DEFICITS}, measures={"silhouette": {"solidity": {}}})
        game = Design.from_source(src, purpose="game", bbox=((0, 0, 0), (40, 20, 10)))
        model = Design.from_source(src, purpose="model", bbox=((0, 0, 0), (40, 20, 10)))
        for op in ops_cage.OPERATORS:
            self.assertEqual(op.domain, "cage")
            self.assertTrue(set(op.targets) <= set(refine.DEFICITS))
            self.assertFalse(op.check(model, an)[0], op.name)
            ok, why = op.check(game, an)
            if not ok:
                self.assertTrue(why, op.name)
                continue
            p1, p2 = op.apply(game, an, dict(op.params)), op.apply(game, an, dict(op.params))
            self.assertIsNotNone(p1.edit, op.name)
            out = p1.edit(src)
            self.assertEqual(out, p2.edit(src), op.name)              # deterministic
            self.assertGreater(len(ops_cage.refine_ops_of(out)), 0, op.name)
            bm.validate_ops(ops_cage.replay(out))
            self.assertTrue(p1.reason, op.name)


@unittest.skipUnless(HAS_BLENDER, "Blender is not installed")
class InBlender(unittest.TestCase):
    def _inset_box(self, extra):
        from form.exemplars.game.base import box, build, start
        b = box([0, 100, 200], [0, 50], [0, 60], crease=0)
        b.region("top", b.faces_where(lambda c: c[1] < 1e-6))
        o = start([b]) + [{"op": "inset", "faces": {"region": "top"}, "thickness": 6.0, "depth": 12.0,
                           "individual": True, "name": "brick"}]
        return build(o + extra)

    def _corner_creases(self, c):
        cm = _crease_map(c)
        V = np.asarray(c.V)
        corner = int(np.argmin(np.linalg.norm(V - [6.0, -12.0, 6.0], axis=1)))
        self.assertLess(np.linalg.norm(V[corner] - [6.0, -12.0, 6.0]), 1e-4)
        return sum(1 for e in cm if corner in e)

    def test_crease_and_support_loops_pin_corners(self):
        plain = self._inset_box([{"op": "crease", "region_boundary": "brick", "value": 1.0}])
        self.assertEqual(self._corner_creases(plain), 2)                     # a crease point: the pill
        for extra in (ops_cage.crisp("brick"), ops_cage.crisp("brick", 2.5)):
            c = self._inset_box(extra)
            self.assertGreaterEqual(self._corner_creases(c), 3)             # a corner, not a crease point
            self.assertEqual(c.hash(), self._inset_box(extra).hash())

    def test_breaker_walls_take_its_region(self):
        from form.exemplars.game.base import build
        o = [{"op": "cage_new", "primitive": "cube", "size": [40, 40, 40]},
             {"op": "name_region", "name": "vent", "faces": {"normal": [1, 0, 0], "within_deg": 5}}]
        c = build(o + [ops_cage.breaker_op("vent", "vent", 10.0)])
        self.assertEqual(len(c.regions["vent"]), 5)                     # the pushed face and its four walls
        plain = dict(ops_cage.breaker_op("vent", "vent", 10.0))
        plain.pop("sides")
        self.assertEqual(c.hash(), build(o + [plain]).hash())          # the same geometry either way

    def test_face_box_narrows_a_region(self):
        from form.exemplars.game.base import box, build, start
        b = box([0, 100, 200], [0, 50], [0, 60], crease=0)
        b.region("all")
        o = start([b]) + [{"op": "inset", "faces": {"region": "all", "box": [[-1, -1, -1], [101, 0.01, 61]]},
                           "thickness": 5.0, "depth": 2.0, "individual": True, "name": "picked"}]
        c = build(o)
        self.assertEqual(len(c.regions["picked"]), 1)                      # the one front face left of x = 100

    def test_ring_array_constant_pitch(self):
        from form.exemplars.game.base import build
        from form.game import pipeline
        ops = [{"op": "cage_new", "primitive": "cylinder", "radius": 100.0, "height": 40.0, "segments": 24},
               ops_cage.kit_ring("tread_block", {"width": 20.0, "length": 12.0}, [[100.0, 0.0, 0.0]],
                                 [1, 0, 0], "z", 18, name="lugs")]
        c = build(ops)
        parts = pipeline.split_cage(c)
        lugs = [p for p in parts if len(p.V) == 12]
        self.assertEqual(len(lugs), 18)
        ang = [math.degrees(math.atan2(p.V.mean(0)[1], p.V.mean(0)[0])) for p in lugs]
        self.assertLess(ops_cage.pitch_variance(ang), 1e-4)
        self.assertEqual(c.hash(), build(ops).hash())
        self.assertEqual(len(c.regions["lugs"]), 18 * 8)


@unittest.skipUnless(HAS_BLENDER, "Blender is not installed")
class Acceptance(unittest.TestCase):
    """The WP3 numbers on the exemplars' cages (the game bench measures the same on the built assets)."""

    def test_wall_brick_corners_are_true_corners(self):
        from form.craft import subd
        from form.exemplars import game as gex
        from form.exemplars.game import wall_kit as wk
        from form.game import pipeline
        hc = pipeline.high_of(gex.make("wall_kit")["cage"])
        r, k = 4, 2
        x0, z0 = wk.joints(r)[k], wk.rows()[r]
        V = np.asarray(hc.V)
        lo, hi = np.array([x0 - 40, wk.FACE - 60, z0 - 40]), np.array([x0 + 90, wk.FACE + 5, z0 + 90])
        keep = [i for i, f in enumerate(hc.F) if np.any(np.all((V[f] >= lo) & (V[f] <= hi), axis=1))]
        used = sorted({v for i in keep for v in hc.F[i]})
        m = {v: j for j, v in enumerate(used)}
        F = [[m[v] for v in hc.F[i]] for i in keep]
        cr = {(m[a], m[b]): s * 10.0 for a, b, s in hc.creases if a in m and b in m}
        Vs, _Q, _c, _p = subd.subdivide(V[used], F, cr, 4)
        top_y = wk.FACE - 12.0
        corner = np.array([x0 + 6.0, z0 + 6.0])
        on_top = np.abs(Vs[:, 1] - top_y) < 0.3
        d = np.linalg.norm(Vs[on_top][:, [0, 2]] - corner, axis=1).min()
        # a fillet of radius r leaves its arc r (sqrt 2 - 1) from the corner
        radius = d / (math.sqrt(2) - 1)
        short = (wk.rows()[1] - wk.rows()[0]) - 12.0
        self.assertLess(radius, 0.15 * short)

    def test_helmet_reads_at_64_px(self):
        from form.craft import subd
        from form.exemplars import game as gex
        from form.refine import analyze
        c = gex.make("scifi_helmet")["cage"]
        cr = {(a, b): s * 10 for a, b, s in c.creases}
        V, Q, _c, _p = subd.subdivide(c.V, c.F, cr, 2)
        P, T = ops_cage.triangles(V, Q.tolist())
        self.assertGreaterEqual(analyze.silhouette(P, T)["convexity_deficit"], 2 * HELMET_BEFORE)

    def test_wheel_tread_constant_pitch(self):
        from form.exemplars import game as gex
        from form.game import pipeline
        hc = pipeline.high_of(gex.make("vehicle_wheel")["cage"])
        rows: dict = {}
        for sh in pipeline.split_cage(hc):
            c = sh.V.mean(0)
            if math.hypot(c[0], c[2]) > 300 and max(sh.V.max(0) - sh.V.min(0)) < 150:
                rows.setdefault(int(round(c[1] / 20.0)), []).append(math.degrees(math.atan2(c[2], c[0])))
        self.assertEqual(len(rows), 2)
        for angles in rows.values():
            self.assertGreater(len(angles), 12)
            self.assertLess(ops_cage.pitch_variance(angles), 0.05)


if __name__ == "__main__":
    unittest.main()
