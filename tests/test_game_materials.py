"""Game materials, masks and bake (WP7): the procedural library, materials() read from a design's source without
running it, request checks that answer 400 not 500, the per-island texel and normal-detail measures, Blender's
lifetime (killed with Form Studio, stale work folders removed), and (with Blender) one bake with the library.

Everything except the Blender build runs without Blender."""
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from form import meshsource
from form.adapters import blender as bl
from form.game import materials as ml
from form.game import pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_game import box_cage, grid_box_cage, uv_cube  # noqa: E402

HAS_BLENDER = bl.resolve({})["available"]
RUNNER = Path(pipeline.RUNNER)


def stub_studio(source_text: str):
    root = Path(tempfile.mkdtemp())
    p = {"id": "chest", "name": "Chest", "head": 3}
    return types.SimpleNamespace(root=root, cfg={}, load=lambda pid: dict(p), keys=lambda p: {"geometry": "g" * 16},
                                 source_text=lambda p: source_text)


class Library(unittest.TestCase):
    def test_every_kind_sets_base_roughness_metallic_and_height(self):
        self.assertEqual(set(ml.KINDS), {"wood", "bare_metal", "brushed_metal", "painted_metal", "leather", "plastic",
                                         "rubber", "stone", "fabric", "emissive"})
        for k in ml.KINDS:
            s = ml.spec("x", {"material": k})
            self.assertEqual(len(s["color"]), 3)
            self.assertTrue(0 <= s["roughness"] <= 1 and s["metallic"] in (0.0, 1.0))
            if k != "emissive":
                self.assertGreater(s["height_mm"], 0, k)
            self.assertEqual(set(ml.for_runner(s)), set(ml.RUNNER_KEYS))
        self.assertGreater(ml.spec("x", {"material": "emissive"})["emission"], 0)
        self.assertEqual(ml.spec("x", {"material": "wood"})["emission"], 0)

    def test_parameters(self):
        s = ml.spec("lid", {"material": "painted_metal", "tint": "#336699", "grain_mm": 12, "wear": 0.9,
                            "roughness": 0.2})
        self.assertEqual((s["hex"], s["grain_mm"], s["wear"], s["roughness"]), ("#336699", 12.0, 0.9, 0.2))
        self.assertEqual(s["edge_metallic"], 1.0)                 # painted metal wears through to bare metal
        self.assertAlmostEqual(s["height_mm"], 12 * ml.KINDS["painted_metal"]["relief"])

    def test_the_first_runners_form_is_still_read(self):
        self.assertEqual(ml.spec("a", {"finish": "metal", "pattern": "brushed"})["kind"], "brushed_metal")
        self.assertEqual(ml.spec("a", {"finish": "metal"})["kind"], "bare_metal")
        self.assertEqual(ml.spec("a", {"finish": "matte", "pattern": "wood", "color": "#7a4a26"})["kind"], "wood")
        self.assertEqual(ml.spec("a", {"finish": "rubber"})["kind"], "rubber")
        self.assertEqual(ml.spec("a", {"finish": "gloss"})["kind"], "plastic")

    def test_bad_materials_name_what_is_wrong(self):
        for m in ({"material": "chrome"}, {"material": "wood", "tint": "red"}, {"material": "wood", "wear": 2},
                  {"material": "wood", "grain_mm": "big"}, {"material": "wood", "wear": True},
                  {"material": "wood", "script": "x"}, {"finish": "chrome"}, "wood", ["wood"]):
            with self.assertRaises(ml.MaterialError, msg=m):
                ml.spec("x", m)
        with self.assertRaises(ml.MaterialError):
            ml.check_map([{"material": "wood"}])


class SourceMaterials(unittest.TestCase):
    def test_read_without_running_the_source(self):
        src = ("import os\nos.system('echo no')\nclass Design:\n    def materials(self, v=None):\n"
               "        \"\"\"doc\"\"\"\n        return {'default': {'material': 'wood'}, 'bands': {'material': "
               "'painted_metal', 'wear': 0.7}}\n")
        with mock.patch("os.system", side_effect=AssertionError("source was executed")):
            got, note = ml.materials_in_source(src)
        self.assertEqual(got["bands"]["wear"], 0.7)
        self.assertEqual(note, "")

    def test_computed_or_wrong_materials_are_not_used_and_say_why(self):
        got, note = ml.materials_in_source("class D:\n    def materials(self, v):\n        return make()\n")
        self.assertIsNone(got)
        self.assertIn("literal", note)
        got, note = ml.materials_in_source("class D:\n    def materials(self, v):\n        return {'a': 'wood'}\n")
        self.assertIsNone(got)
        self.assertIn("not used", note)
        self.assertEqual(ml.materials_in_source("x = (")[0], None)
        self.assertEqual(ml.materials_in_source("MATERIALS = {'default': {'material': 'stone'}}\n")[0],
                         {"default": {"material": "stone"}})

    def test_cage_design_source_keeps_materials_and_the_cage(self):
        cage = grid_box_cage((0, 0, 0), (30, 20, 10))
        mats = {"default": {"material": "wood", "grain_mm": 40}, "top": {"material": "painted_metal"}}
        src = pipeline.cage_design_source(cage, "Crate", mats)
        ast.parse(src)
        self.assertEqual(ml.materials_in_source(src)[0], mats)
        self.assertEqual(len(pipeline.cages_in_source(src)), 1)
        with self.assertRaises(pipeline.GameError):
            pipeline.cage_design_source(cage, "Crate", {"lid": {"material": "wood"}})

    def test_game_asset_uses_the_design_materials_and_keys_on_them(self):
        from form import game
        cage = grid_box_cage((0, 0, 0), (30, 20, 10))
        seen = []

        def fake_build(src, out, **kw):
            seen.append(src.get("materials"))
            raise pipeline.GameError("stop here")
        keys = []
        for mats in (None, {"default": {"material": "leather"}}):
            st = stub_studio(pipeline.cage_design_source(cage, "Crate", mats))
            with mock.patch.object(pipeline, "build", side_effect=fake_build), \
                 mock.patch.object(pipeline, "options_key", side_effect=lambda o, m: keys.append(m) or "k"):
                with self.assertRaises(Exception):
                    game.game_asset(st, "chest")
        self.assertEqual(seen, [None, {"default": {"material": "leather"}}])
        self.assertEqual(keys, [None, {"default": {"material": "leather"}}])


class RequestChecks(unittest.TestCase):
    def test_app_options_answer_400_naming_the_field(self):
        from form.game import app
        from form.studio import StudioError
        for body, word in (({"texture_px": "big"}, "texture_px"), ({"texture_px": 1.5}, "texture_px"),
                           ({"texture_px": [1]}, "texture_px"), ({"materials": [{"material": "wood"}]}, "materials"),
                           ({"budgets": "many"}, "budgets"), ({"preset": 3}, "preset"), ([], "object")):
            with self.assertRaises(StudioError, msg=body) as cm:
                app._options(body)
            self.assertEqual(cm.exception.status, 400)
            self.assertIn(word, str(cm.exception))
        o = app._options({"texture_px": "2048", "materials": {"default": {"material": "stone"}}})
        self.assertEqual((o["texture_px"], o["materials"]), (2048, {"default": {"material": "stone"}}))
        self.assertIsNone(app._options({})["materials"])

    def test_game_asset_refuses_bad_materials_before_reading_anything(self):
        from form import game
        from form.studio import StudioError
        st = stub_studio("")
        st.load = mock.Mock(side_effect=AssertionError("the project was read"))
        for mats in ({"default": {"material": "chrome"}}, {"default": "wood"}, [{"material": "x"}]):
            with self.assertRaises(StudioError, msg=mats) as cm:
                game.game_asset(st, "chest", materials=mats)
            self.assertEqual(cm.exception.status, 400)

    def test_a_list_for_a_cage_is_a_game_error_not_a_type_error(self):
        cage = meshsource.cage(*box_cage((0, 0, 0), (10, 10, 10)))
        with self.assertRaises(pipeline.GameError):
            pipeline.region_materials(cage, [{"material": "wood"}])


class Measures(unittest.TestCase):
    def test_island_texel(self):
        P, N, UV, T, isl = uv_cube(4)
        r = pipeline.island_texel(P, UV, T, 1024)
        self.assertEqual(r["islands"], 6)
        self.assertLess(r["worst"], 0.01)
        UV2 = UV.copy()
        sel = np.unique(T[isl == 0])
        UV2[sel] = UV2[sel].mean(0) + (UV2[sel] - UV2[sel].mean(0)) * 0.5     # one face at half the density
        r2 = pipeline.island_texel(P, UV2, T, 1024)
        self.assertEqual(r2["outside"], 1)
        self.assertAlmostEqual(r2["worst"], 0.5, places=2)

    def test_normal_detail(self):
        P, N, UV, T, _ = uv_cube(4)
        flat = np.zeros((256, 256, 3))
        flat[..., :] = (0.5, 0.5, 1.0)
        self.assertEqual(pipeline.normal_detail(flat, UV, T)["blue_std"], 0.0)
        rng = np.random.default_rng(1)
        tilt = rng.normal(0, 0.35, (256, 256, 2))
        z = 1 / np.sqrt(1 + (tilt ** 2).sum(-1))
        bumpy = np.concatenate([(tilt * z[..., None] + 1) / 2, ((z + 1) / 2)[..., None]], axis=-1)
        self.assertGreater(pipeline.normal_detail(bumpy, UV, T)["blue_std"], pipeline.NORMAL_BLUE_STD_MIN)


class Lifetime(unittest.TestCase):
    def dead_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_stale_work_folders_are_removed_and_live_ones_kept(self):
        base = Path(tempfile.mkdtemp())
        dead = self.dead_pid()
        for name, owner in (("form-game-dead", {"pid": dead}), ("form-game-live", {"pid": os.getpid()})):
            (base / name).mkdir()
            (base / name / pipeline.OWNER).write_text(json.dumps(owner))
        (base / "form-game-fresh").mkdir()                               # no owner yet: too young to judge
        (base / f"0123456789abcdef.old-{dead}").mkdir()
        (base / "0123456789abcdef").mkdir()                               # a built asset: never touched
        removed = pipeline.cleanup_stale(base)
        self.assertEqual(sorted(removed), sorted(["form-game-dead", f"0123456789abcdef.old-{dead}"]))
        self.assertEqual(sorted(p.name for p in base.iterdir()),
                         ["0123456789abcdef", "form-game-fresh", "form-game-live"])

    @unittest.skipIf(os.name == "nt", "process groups")
    def test_blender_dies_with_form_studio(self):
        p = subprocess.Popen(["sleep", "30"], start_new_session=True)
        with pipeline._LIVE_LOCK:
            pipeline._LIVE[p.pid] = p
        self.assertEqual(pipeline.kill_all(), 1)
        t0 = time.time()
        p.wait(timeout=10)
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(pipeline._LIVE, {})

    def test_the_runner_watches_its_parent(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertIn("watch_parent", names)
        self.assertIn("getppid", RUNNER.read_text(encoding="utf-8"))


class HighOnly(unittest.TestCase):
    def test_an_optional_high_only_cage_is_accepted(self):
        cage = grid_box_cage((0, 0, 0), (30, 20, 10))
        self.assertIsNone(pipeline.high_of(cage))
        detail = grid_box_cage((0, 0, 0), (30, 20, 10), n=6)
        cage.high = detail
        h = pipeline.high_of(cage)
        self.assertEqual(len(h.F), len(detail.F))
        specs, face = pipeline.region_materials(cage, {"top": {"material": "rubber"}})
        arrays, level = pipeline._high_arrays(h, cage, face, specs, np.zeros(3), 3)
        self.assertEqual(level, 2)                                         # 4x the faces: one level fewer
        self.assertEqual(len(arrays["face_mat"]), len(detail.F))
        self.assertEqual(set(arrays["face_mat"].tolist()), {0, 1})       # "top" by region name, the rest nearest
        V, F = box_cage((0, 0, 0), (1, 1, 1))
        cage.high = (V, F[:-1])                                            # an open high cage is ignored
        self.assertIsNone(pipeline.high_of(cage))
        merged = pipeline.merge_cages([grid_box_cage((0, 0, 0), (1, 1, 1)), cage])
        self.assertIsNone(pipeline.high_of(merged))


@unittest.skipUnless(HAS_BLENDER and os.environ.get("FORM_TEST_GAME_BLENDER", "1") != "0", "needs Blender")
class Bake(unittest.TestCase):
    def test_library_materials_masks_and_emissive(self):
        cage = grid_box_cage((-40, -30, 0), (40, 30, 50))
        out = Path(tempfile.mkdtemp()) / "asset"
        rep = pipeline.build({"cage": cage, "materials": {"default": {"material": "painted_metal", "wear": 0.8},
                                                          "top": {"material": "emissive", "tint": "#40c0ff"}}},
                             out, asset="Panel", budgets=[1500, 700, 300, 60], texture_px=1024, timeout=900)
        self.assertEqual([m["kind"] for m in rep["materials"]], ["painted_metal", "emissive"])
        self.assertEqual(sorted(rep["bake"]["files"]), ["ao", "base_color", "curvature", "emissive", "normal", "orm",
                                                        "thickness"])
        w = rep["bake"]["wear"]                       # the worn share, measured on the baked wear mask over LOD0
        self.assertTrue(0.0 <= w["worn_share"] < 0.5, w)   # an uncreased cage subdivides smooth: no edge to wear
        self.assertEqual(set(w) >= {"worn_share", "convex_share", "worn_on_convex", "convex_of_worn"}, True)
        for r in rep["bake"]["rays"]:
            self.assertAlmostEqual(r["ray_mm"], 2 * r["extrusion_mm"], places=3)
            self.assertGreaterEqual(r["extrusion_mm"], r["p99_mm"] * 1.2 - 1e-3)
        checks = {c["id"]: c for c in rep["validation"]["checks"] if c.get("lod") in (0, None)}
        self.assertEqual(checks["normal_map"]["status"], "PASS", checks["normal_map"]["value"])
        self.assertEqual(checks["texel_islands"]["status"], "PASS", checks["texel_islands"]["value"])
        g = json.loads((out / "Panel.glb").read_bytes()[20:20 + int.from_bytes((out / "Panel.glb").read_bytes()[12:16],
                                                                               "little")])
        self.assertIn("emissiveTexture", g["materials"][0])
        self.assertEqual([p.name for p in out.parent.iterdir() if p.name.startswith("form-game-")], [])


if __name__ == "__main__":
    unittest.main()
