"""The wall-thickness field (form/thickness.py): every thin region in one deterministic answer."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from build123d import Box, Pos  # noqa: E402

import thickness_fixtures as fx  # noqa: E402
from form import kernel, thickness as th  # noqa: E402


def fresh(shape, floor=0.8):
    th._mem.clear()
    return th.regions(shape, floor)


class PlantedRegions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = {name: mk() for name, mk in fx.FIXTURES.items()}

    def test_every_planted_region_is_found_with_its_wall_and_kind(self):
        for name in ("block_with_seven", "tube_and_plate"):
            shape, planted = self.made[name]
            res = fresh(shape)
            n, hit = fx.recall(res["regions"], planted)
            self.assertEqual(n, len(planted), f"{name}: found {hit}")
            for p in planted:
                r = next(r for r in res["regions"] if fx.found(r, p))
                self.assertEqual(r["kind"], p["kind"], f"{name} {p['name']}")
            self.assertEqual(res["evidence"], "computed")
            self.assertEqual([r["min_mm"] for r in res["regions"]], sorted(r["min_mm"] for r in res["regions"]))

    def test_walls_are_measured_to_the_b_rep(self):
        shape, planted = self.made["block_with_seven"]
        res = fresh(shape)
        by = {p["name"]: next(r for r in res["regions"] if fx.found(r, p)) for p in planted}
        for name, want in (("fin", 0.5), ("skin", 0.4), ("web", 0.6), ("slot wall", 0.7), ("speck", 0.3)):
            self.assertAlmostEqual(by[name]["min_mm"], want, places=3, msg=name)
        self.assertLess(by["lip"]["min_mm"], 0.05)
        self.assertEqual(res["thinnest"]["t"], res["regions"][0]["min_mm"])
        tube = fresh(self.made["tube_and_plate"][0])
        self.assertAlmostEqual(next(r for r in tube["regions"] if r["min_mm"] > 0.5)["min_mm"], 0.6, places=3)

    def test_parts_that_touch_are_not_a_wall(self):
        res = fresh(self.made["touching_parts"][0])
        self.assertEqual(res["regions"], [])
        self.assertGreater(res["thinnest"]["t"], 4.9)

    def test_the_same_solid_gives_the_same_answer_every_time(self):
        shape, _ = self.made["block_with_seven"]
        first = json.dumps(fresh(shape), sort_keys=True)
        for _ in range(9):
            self.assertEqual(json.dumps(fresh(shape), sort_keys=True), first)


class CacheAndReuse(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="form-thickness-"))
        th._mem.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        for k in [k for k in kernel._cache if str(k[0]).startswith("thk-")]:
            kernel._cache.pop(k)

    def test_a_second_call_reads_the_answer_back_without_the_model(self):
        shape, _ = fx.block_with_seven()
        kernel._cache[("thk-a", 0.05)] = th.model_of_shape(shape)
        first = th.regions("thk-a", 0.8, directory=self.dir)
        self.assertTrue(any(self.dir.glob("thk-a-*.npz")))
        th._mem.clear()
        kernel._cache.pop(("thk-a", 0.05))                     # only the file is left
        self.assertEqual(json.dumps(th.regions("thk-a", 0.8, directory=self.dir), sort_keys=True),
                         json.dumps(first, sort_keys=True))

    def test_a_change_to_one_feature_remeasures_only_around_it(self):
        a, _ = fx.block_with_seven()
        b = a - Pos(70, 30, 0) * Box(4, 4, 19.5, align=fx.MIN)  # a new pocket from below: a 0.5 mm skin
        ma, mb = th.model_of_shape(a), th.model_of_shape(b)
        fa = th.ThicknessField.build(ma, 0.8)
        full = th.ThicknessField.build(mb, 0.8)
        inc = th.ThicknessField.build(mb, 0.8, base=fa)
        self.assertGreater(inc.meta["reused"], 0.5 * len(inc.t))
        np.testing.assert_array_equal(inc.S, full.S)
        np.testing.assert_array_equal(np.isnan(inc.t), np.isnan(full.t))
        np.testing.assert_array_equal(inc.t[np.isfinite(full.t)], full.t[np.isfinite(full.t)])
        ri, rf = inc.regions(mb, 0.8), full.regions(mb, 0.8)
        self.assertEqual(json.dumps(ri, sort_keys=True), json.dumps(rf, sort_keys=True))
        self.assertTrue(any(abs(r["min_mm"] - 0.5) < 1e-3 and r["bbox"][0][0] > 69 for r in rf["regions"]))


class Integration(unittest.TestCase):
    def test_the_kernel_reports_the_thinnest_and_every_region(self):
        shape, planted = fx.block_with_seven()
        th._mem.clear()
        thin, field = kernel._thickness(th.model_of_shape(shape), floor=0.8)
        self.assertEqual(thin["t"], field["regions"][0]["min_mm"])
        self.assertEqual(len(field["regions"]), len(planted))
        line = th.sentence(field)
        self.assertIn(f"{len(planted)} regions under 1.20 mm", line)
        self.assertIn("knife edge", line)

    def test_no_wall_at_all_says_so(self):
        th._mem.clear()
        res = th.regions(Box(30, 30, 30), 0.8)              # nothing within the cap: rays look across the part
        self.assertEqual(res["regions"], [])
        self.assertAlmostEqual(res["thinnest"]["t"], 30.0, places=3)
        self.assertEqual(th.sentence(res), "")


if __name__ == "__main__":
    unittest.main()
