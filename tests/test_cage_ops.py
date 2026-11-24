"""The cage vocabulary (bevel, support loops, inset, panel lines, trim, solidify, bridge, kit parts), the kit itself and
high_only detail for the bake source.

The schema and kit tests always run; the op tests run each op in real Blender and skip cleanly without it. Every op
test checks that the cage stays closed, manifold along its edges and consistently oriented."""
import json
import math
import unittest

import numpy as np

from form import meshsource
from form.adapters import blender as bl
from form.adapters import blender_model as bm
from form.game import kit

BLENDER = bl.resolve({})
HAS_BLENDER = BLENDER["available"]

BOX = [{"op": "cage_new", "primitive": "cube", "size": [40, 30, 20]}]
# the cages the existing tests model, and their values before this vocabulary existed (Blender 5.2.3)
MODEL = [
    {"op": "cage_new", "primitive": "cube", "size": [20, 20, 20]},
    {"op": "name_region", "name": "top", "faces": {"normal": [0, 0, 1], "within_deg": 10}},
    {"op": "extrude_region", "faces": {"region": "top"}, "offset": 5},
    {"op": "loop_cut", "edge": [0, 1], "cuts": 2},
    {"op": "move", "verts": {"region": "top"}, "by": [0, 0, 2]},
    {"op": "crease", "region_boundary": "top", "value": 1.0},
    {"op": "mirror", "axis": "x"},
    {"op": "sculpt_ops", "strokes": [{"brush": "inflate", "center": [0, 0, 17], "radius": 12, "strength": 0.5},
                                     {"brush": "smooth", "center": [0, 0, 0], "radius": 40, "strength": 0.2,
                                      "iterations": 2}]},
]
MODEL_HASH = "63edf55a242971228877ce1d7362408438adba7ea8c5f4835e6a31e9ace67456"
MODEL_FULL = "5e03367535e03d16caf91bd08632c679c3f99179b6e4d75d654788e80c81387b"
MODEL_KEY = "d53ab23984cba574"

DETAIL = BOX + [
    {"op": "support_loops", "edges": {"angle_deg": 30}, "distance": 1.0},
    {"op": "inset", "faces": {"normal": [0, 0, 1], "within_deg": 5}, "thickness": 3, "depth": -1.5, "name": "lid"},
    {"op": "kit_place", "part": "bolt_hex", "at": [[15, 10, 10], [-15, 10, 10], [15, -10, 10], [-15, -10, 10]],
     "snap": True, "scale": 0.6, "name": "bolts"},
    {"op": "panel_line", "edges": {"region_boundary": "lid"}, "width": 0.8, "depth": 0.5, "high_only": True},
    {"op": "kit_place", "part": "rivet_dome", "faces": {"normal": [1, 0, 0]}, "mode": "center", "high_only": True},
]


def closed(cage) -> bool:
    return cage.open_edges() == 0 and kit.closed_and_oriented(cage.F)


def euler(cage) -> int:
    E = {(min(a, b), max(a, b)) for f in cage.F for a, b in zip(f, f[1:] + f[:1])}
    return len(cage.V) - len(E) + len(cage.F)


class Kit(unittest.TestCase):
    def test_at_least_24_original_parts_each_documented(self):
        d = kit.describe()
        self.assertGreaterEqual(len(d), 24)
        for name, info in d.items():
            self.assertRegex(name, r"^[a-z][a-z0-9_]+$")
            self.assertIn(info["kind"], ("surface", "axial", "corner"))
            self.assertGreater(len(info["doc"]), 15, name)
            for p, (dv, lo, hi, kind) in info["params"].items():
                self.assertTrue(lo <= dv <= hi, f"{name}.{p}")

    def test_every_part_is_closed_oriented_and_deterministic(self):
        for name in kit.names():
            with self.subTest(part=name):
                a, b = kit.build(name), kit.build(name)
                self.assertTrue(np.array_equal(a.V, b.V))
                self.assertEqual((a.F, a.C), (b.F, b.C))
                self.assertTrue(kit.closed_and_oriented(a.F))
                for shell in kit.shells(a.F):           # every shell faces outward
                    self.assertGreater(kit.volume(a.V, [a.F[i] for i in shell]), 0)
                self.assertTrue(all(3 <= len(f) <= 64 for f in a.F))
                self.assertTrue(all(0 < w <= 1 for _a, _b, w in a.C))
                lo, hi = a.V.min(0), a.V.max(0)
                if kit.PARTS[name][1] != "corner":     # standing on z = 0, sunk a little into the surface
                    self.assertAlmostEqual(lo[2], -kit.EMBED, delta=1.6)
                    self.assertGreater(hi[2], 0)
                self.assertLess(len(a.V), 2000)

    def test_parameters_change_the_part_and_are_checked(self):
        self.assertFalse(np.array_equal(kit.build("bolt_hex").V, kit.build("bolt_hex", {"across_flats": 12}).V))
        a = kit.build("greeble_block", {"seed": 1}).V
        self.assertFalse(np.array_equal(a, kit.build("greeble_block", {"seed": 2}).V))
        for name, params, words in (("teapot", {}, "no kit part"), ("bolt_hex", {"size": 3}, "does not take"),
                                    ("bolt_hex", {"height": 1e6}, "outside"), ("vent_louver", {"slats": 2.5}, "whole"),
                                    ("washer", {"outer": 6, "inner": 6}, "inner"), ("rivet_dome", {"height": True},
                                                                                     "number")):
            with self.subTest(name=name, params=params):
                with self.assertRaises(kit.KitError) as cm:
                    kit.build(name, params)
                self.assertIn(words, str(cm.exception))


class Schema(unittest.TestCase):
    GOOD = {
        "bevel": {"op": "bevel", "edges": [[0, 1]], "width": 1.5},
        "support_loops": {"op": "support_loops", "edges": {"angle_deg": 30}, "distance": 0.5},
        "inset": {"op": "inset", "faces": {"normal": [0, 0, 1]}, "thickness": 2},
        "panel_line": {"op": "panel_line", "edges": {"path": [0, 1, 2], "closed": False}, "width": 1, "depth": 0.5},
        "trim_strip": {"op": "trim_strip", "edges": {"region_boundary": "top"}, "width": 2, "height": 1},
        "solidify": {"op": "solidify", "thickness": 2},
        "bridge": {"op": "bridge", "faces_a": {"region": "a"}, "faces_b": {"region": "b"}},
        "kit_place": {"op": "kit_place", "part": "rivet_dome", "faces": {"all": True}},
    }
    BAD = [
        ({"op": "bevel", "edges": [[0, 1]], "width": 0}, "outside"),
        ({"op": "bevel", "edges": [[0, 1]], "width": 1, "segments": 20}, "outside"),
        ({"op": "bevel", "edges": {"lasso": 1}, "width": 1}, "edge selection"),
        ({"op": "bevel", "edges": {"path": [3]}, "width": 1}, "two points"),
        ({"op": "support_loops", "edges": {"angle_deg": 0}, "distance": 1}, "outside"),
        ({"op": "inset", "faces": {"all": True}, "thickness": 1, "individual": "yes"}, "true or false"),
        ({"op": "panel_line", "edges": [[0, 1]], "width": 1}, "number"),
        ({"op": "trim_strip", "edges": [[0, 1]], "width": 1, "height": 1, "depth": 2}, "does not take"),
        ({"op": "solidify", "thickness": 0}, "zero"),
        ({"op": "bridge", "faces_a": {"region": "a"}}, "face selection"),
        ({"op": "kit_place", "part": "nope", "faces": {"all": True}}, "no kit part"),
        ({"op": "kit_place", "part": "rivet_dome"}, "faces"),
        ({"op": "kit_place", "part": "rivet_dome", "at": [[0, 0, 0]]}, "snap"),
        ({"op": "kit_place", "part": "rivet_dome", "at": [[0, 0, 0]], "snap": True, "normal": [0, 0, 1]}, "snap"),
        ({"op": "kit_place", "part": "rivet_dome", "at": [[0, 0, 0]] * 600, "snap": True}, "1..512"),
        ({"op": "kit_place", "part": "grip_wrap", "at": [[0, 0, 0]] * 100, "snap": True}, "exceed"),
        ({"op": "kit_place", "part": "rivet_dome", "faces": {"all": True}, "scale": 0}, "outside"),
        ({"op": "kit_place", "part": "rivet_dome", "faces": {"all": True}, "mode": "random"}, "mode"),
        ({"op": "kit_place", "part": "rivet_dome", "faces": {"all": True}, "code": "x"}, "does not take"),
        ({"op": "bevel", "edges": [[0, 1]], "width": 1, "high_only": "yes"}, "high_only"),
    ]

    def test_new_ops_are_in_the_schema_and_normalised(self):
        for k, o in self.GOOD.items():
            with self.subTest(op=k):
                self.assertIn(k, bm.OP_SCHEMA)
                n = bm.validate_ops(BOX + [o])
                self.assertEqual(n[1]["op"], k)
                self.assertEqual(bm.validate_ops(n), n)                 # normalising is idempotent
                self.assertEqual(json.loads(json.dumps(n)), n)
        n = bm.validate_ops(BOX + [self.GOOD["kit_place"]])[1]
        self.assertEqual(n["params"], kit.check_params("rivet_dome", {}))
        self.assertEqual((n["kit"], n["mode"], n["scale"]), (kit.KIT_VERSION, "each", [1.0, 1.0, 1.0]))
        self.assertEqual(bm.validate_ops(BOX + [self.GOOD["bevel"]])[1]["edges"], {"pairs": [[0, 1]]})

    def test_bad_ops_are_refused_before_blender_starts(self):
        for o, words in self.BAD:
            with self.subTest(o=str(o)[:90]):
                with self.assertRaises(bm.OpError) as cm:
                    bm.validate_ops(BOX + [o])
                self.assertIn(words, str(cm.exception))
                self.assertEqual(cm.exception.index, 1)

    def test_high_only_goes_last_and_never_on_cage_new(self):
        hi = dict(self.GOOD["bevel"], high_only=True)
        n = bm.validate_ops(BOX + [self.GOOD["inset"], hi])
        self.assertTrue(n[2]["high_only"])
        self.assertNotIn("high_only", n[1])
        with self.assertRaises(bm.OpError) as cm:
            bm.validate_ops(BOX + [hi, self.GOOD["inset"]])
        self.assertIn("must be high_only too", str(cm.exception))
        with self.assertRaises(bm.OpError):
            bm.validate_ops([dict(BOX[0], high_only=True)])
        # high_only false is the same op as no flag: the key does not change
        self.assertEqual(bm.op_key(BOX + [dict(self.GOOD["inset"], high_only=False)], "5.2.3"),
                         bm.op_key(BOX + [self.GOOD["inset"]], "5.2.3"))
        self.assertNotEqual(bm.op_key(BOX + [hi], "5.2.3"), bm.op_key(BOX + [self.GOOD["bevel"]], "5.2.3"))

    def test_existing_op_lists_keep_their_keys(self):
        self.assertEqual(bm.op_key(MODEL, "5.2.3"), MODEL_KEY)

    def test_kit_geometry_is_built_here_not_sent_by_the_agent(self):
        n = bm.validate_ops(BOX + [{"op": "kit_place", "part": "bolt_hex", "faces": {"all": True}, "scale": 2,
                                    "rotation": 90}])[1]
        self.assertNotIn("mesh", n)                                     # the key holds the numbers, not points
        e = bm.expand(n)
        part = kit.build("bolt_hex")
        V = np.array(e["mesh"]["V"])
        self.assertEqual(len(V), len(part.V))
        self.assertTrue(np.allclose(V[:, 0], -2 * part.V[:, 1], atol=1e-5))   # turned 90 degrees, then scaled
        self.assertTrue(np.allclose(V[:, 2], 2 * part.V[:, 2], atol=1e-5))
        with self.assertRaises(bm.OpError):                              # geometry sent with the op is refused
            bm.validate_ops(BOX + [dict(n, mesh=e["mesh"])])


class HighCage(unittest.TestCase):
    def test_high_round_trips_and_leaves_the_low_hash(self):
        V = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        low = meshsource.cage(V, [[0, 1, 2, 3]])
        high = meshsource.cage(V, [[0, 1, 2, 3]], high={"V": V, "F": [[3, 2, 1, 0]], "creases": [], "regions": {}})
        self.assertEqual(low.hash(), high.hash())
        self.assertNotEqual(low.full_hash(), high.full_hash())
        self.assertNotIn("high", low.to_dict())
        self.assertNotIn("high", low.literal())                          # old cages write the same source
        self.assertEqual(meshsource.CageData.from_dict(high.to_dict()).full_hash(), high.full_hash())
        ns = {}
        exec(high.literal(), {"meshsource": meshsource}, ns)            # generated source, not agent text
        self.assertEqual(ns["CAGE"].full_hash(), high.full_hash())
        self.assertIn("high", high.summary())
        from form.game import pipeline                                  # the game pipeline still reads the cage
        got = pipeline.cages_in_source("from form import meshsource\n" + high.literal())
        self.assertEqual(got[0].hash(), high.hash())


@unittest.skipUnless(HAS_BLENDER, BLENDER["reason"] or "Blender is not installed")
class Ops(unittest.TestCase):
    def run_ok(self, ops):
        r = bm.run_ops(ops)
        c = r["cage"]
        self.assertTrue(closed(c), f"open edges {c.open_edges()}")
        if c.high is not None:
            self.assertTrue(closed(c.high), f"high: open edges {c.high.open_edges()}")
        return r, c

    def test_bevel(self):
        _r, c = self.run_ok(BOX + [{"op": "bevel", "edges": {"angle_deg": 30}, "width": 2, "segments": 2,
                                    "crease": 0.5, "name": "chamfer"}])
        self.assertEqual(len(c.F), 6 + 12 * 2 + 8 * 3)           # 6 sides, 2 strips per edge, 3 per corner
        self.assertEqual(len(c.regions["chamfer"]), 12 * 2 + 8 * 3)
        self.assertTrue(c.creases and all(w == 0.5 for _a, _b, w in c.creases))
        self.assertAlmostEqual(float(c.V[:, 0].max()), 20.0, places=4)    # the outline is kept

    def test_support_loops(self):
        _r, c = self.run_ok(BOX + [{"op": "crease", "edges": [[0, 1]], "value": 1.0},
                                   {"op": "support_loops", "edges": {"angle_deg": 30}, "distance": 1}])
        self.assertTrue(c.is_quads())
        self.assertGreater(len(c.F), 6)
        lo, hi = c.V.min(0), c.V.max(0)
        self.assertTrue(np.allclose(hi - lo, [40, 30, 20], atol=1e-4))      # the corners stay where they were
        self.assertTrue(c.creases)                                          # the creased edge stays creased

    def test_inset(self):
        _r, c = self.run_ok(BOX + [{"op": "inset", "faces": {"normal": [0, 0, 1]}, "thickness": 4, "depth": -2,
                                    "name": "recess", "crease": 1}])
        lid = c.regions["recess"]
        self.assertEqual(len(lid), 1)
        z = c.V[c.F[lid[0]]][:, 2]
        self.assertTrue(np.allclose(z, 8.0, atol=1e-4))                     # 2 mm below the top
        _r, c2 = self.run_ok(BOX + [{"op": "inset", "faces": {"all": True}, "thickness": 2, "individual": True}])
        self.assertEqual(len(c2.F), 6 * 5)

    def test_panel_line(self):
        # a loop round the sides at z = 0, then a groove along it
        _r, c = self.run_ok(BOX + [{"op": "loop_cut", "edge": [0, 1], "cuts": 1},
                                   {"op": "panel_line", "edges": {"box": [[-99, -99, -0.01], [99, 99, 0.01]]},
                                    "width": 1, "depth": 0.6, "name": "seam"}])
        self.assertEqual(len(c.regions["seam"]), 4 * 2)                   # 4 sides, a strip either side
        mid = c.V[np.abs(c.V[:, 2]) < 1e-6]                                # the groove's bottom loop
        self.assertEqual(len(mid), 4)
        self.assertTrue(np.allclose(np.abs(mid[:, :2]), [19.4, 14.4], atol=1e-4))   # 0.6 mm in from both sides
        lips = c.V[np.abs(np.abs(c.V[:, 2]) - 0.5) < 1e-6]
        self.assertTrue(np.allclose(np.abs(lips[:, :2]), [20.0, 15.0], atol=1e-4))  # the lips stay on the surface
        self.assertTrue(any(w == 1.0 for _a, _b, w in c.creases))

    def test_trim_strip(self):
        _r, c = self.run_ok(BOX + [{"op": "loop_cut", "edge": [0, 1], "cuts": 1},
                                   {"op": "trim_strip", "edges": {"box": [[-99, -99, -0.01], [99, 99, 0.01]]},
                                    "width": 3, "height": 1.2, "name": "band"}])
        self.assertIn("band", c.regions)
        band = c.V[np.abs(c.V[:, 2]) <= 1.5 + 1e-6]
        self.assertAlmostEqual(float(band[:, 0].max()), 21.2, places=3)     # 1.2 mm proud of the side
        self.assertAlmostEqual(float(c.V[:, 2].max() - c.V[:, 2].min()), 20.0, places=4)
        self.assertTrue(c.creases)

    def test_solidify(self):
        _r, c = self.run_ok([{"op": "cage_new", "primitive": "plane", "size": [40, 40, 1], "segments": 4},
                             {"op": "solidify", "thickness": 3, "rim_crease": 1}])
        self.assertEqual(len(c.F), 16 * 2 + 16)
        self.assertAlmostEqual(float(c.V[:, 2].max() - c.V[:, 2].min()), 3.0, places=4)
        self.assertTrue(c.creases)

    def test_bridge(self):
        _r, c = self.run_ok([{"op": "cage_new", "primitive": "cube", "size": [40, 10, 40]},
                             {"op": "inset", "faces": {"normal": [0, 1, 0]}, "thickness": 10, "name": "a"},
                             {"op": "inset", "faces": {"normal": [0, -1, 0]}, "thickness": 10, "name": "b"},
                             {"op": "bridge", "faces_a": {"region": "a"}, "faces_b": {"region": "b"}, "cuts": 2,
                              "name": "hole"}])
        self.assertEqual(euler(c), 0)                                      # a torus: genus 1
        self.assertEqual(len(c.regions["hole"]), 4 * 3)
        self.assertTrue(c.is_quads())

    def test_kit_place(self):
        _r, c = self.run_ok(BOX + [{"op": "kit_place", "part": "bolt_hex", "faces": {"normal": [0, 0, 1]},
                                    "mode": "center", "scale": 1.5, "name": "bolts"},
                                   {"op": "kit_place", "part": "rivet_dome", "at": [[20, 0, 0], [20, 10, 5]],
                                    "snap": True, "rotation": 30},
                                   {"op": "kit_place", "part": "pommel_disc", "at": [[0, 0, -10]],
                                    "normal": [0, 0, -1], "scale": 0.5}])
        part = kit.build("bolt_hex")
        self.assertEqual(len(kit.shells(c.F)), 1 + len(kit.shells(part.F)) + 2 + 1)
        bolts = c.regions["bolts"]
        self.assertEqual(len(bolts), len(part.F))
        P = c.V[sorted({i for f in bolts for i in c.F[f]})]
        self.assertAlmostEqual(float(P[:, 2].max()), 10 + 1.5 * float(part.V[:, 2].max()), places=3)
        self.assertGreater(float(c.V[:, 0].max()), 20.5)                    # rivets stand out of the +X side
        self.assertLess(float(c.V[:, 2].min()), -10 - 0.5 * 12 + 0.1)       # the pommel hangs below

    def test_high_only_detail_goes_to_the_bake_source_only(self):
        low_ops = [o for o in DETAIL if not o.get("high_only")]
        r, c = self.run_ok(DETAIL)
        r_low = bm.run_ops(low_ops)
        self.assertEqual(c.hash(), r_low["cage"].hash())                   # the LOD cage is untouched
        self.assertIsNotNone(c.high)
        self.assertIsNone(r_low["cage"].high)
        self.assertGreater(len(c.high.F), len(c.F))
        self.assertEqual(len(c.high.regions["bolts"]), len(c.regions["bolts"]))   # a copy of the low cage, on
        self.assertEqual([o.get("high_only", False) for o in r["ops"]], [bool(o.get("high_only")) for o in DETAIL])
        self.assertEqual(r["stages"], len(DETAIL))

    def test_replay_is_deterministic(self):
        a = bm.run_ops(DETAIL)
        for _ in range(2):
            b = bm.run_ops(DETAIL)
            self.assertEqual(a["key"], b["key"])
            self.assertEqual(a["cage"].full_hash(), b["cage"].full_hash())

    def test_existing_cages_are_unchanged(self):
        r = bm.run_ops(MODEL)
        if not r["blender"].startswith("5.2."):
            self.skipTest("the recorded values are Blender 5.2's")
        self.assertEqual((r["hash"], r["cage"].full_hash(), r["key"]), (MODEL_HASH, MODEL_FULL, MODEL_KEY))
        self.assertIsNone(r["cage"].high)
        self.assertNotIn("high", r["cage"].to_dict())

    def test_detail_cage_builds_exact_subd_cad_data(self):
        from form.craft import subd_report
        _r, c = self.run_ok(BOX + [{"op": "support_loops", "edges": {"angle_deg": 30}, "distance": 1.5},
                                   {"op": "inset", "faces": {"normal": [0, 0, 1]}, "thickness": 4, "depth": -2}])
        d = subd_report.deviation(c.to_subd(), level=3)
        self.assertTrue(math.isfinite(d["max_mm"]))
        self.assertLess(d["max_per_100mm"], 0.5)


if __name__ == "__main__":
    unittest.main()
