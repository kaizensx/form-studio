"""The game critic (form/critique.py: game_evidence, _game_caps, blind passes) and the game exemplars
(form/exemplars/game). Nothing here needs Blender or OCCT: the bench (scripts/game_bench.py) runs the real assets."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from form import critique
from form.adapters import blender_model
from form.exemplars import game as gex
from form.exemplars.game import base


def evidence(**kw):
    ev = {"edges": {"coverage": 0.95, "feature_edges_mm": 9000.0, "hard_edges_mm": 500.0, "hard_baked_mm": 450.0,
                    "raw_share": 0.05},
          "materials": {"count": 3, "list": []}, "value_contrast": 0.4,
          "scales": {"primary": True, "secondary": True, "tertiary": True, "count": 3},
          "silhouette": {"complexity": 0.05}, "wear": {"present": True}}
    for k, v in kw.items():
        ev[k] = {**ev[k], **v} if isinstance(v, dict) and isinstance(ev.get(k), dict) else v
    return ev


ALL5 = {i: 5 for i, _, _ in critique.AESTHETIC}


class GameCaps(unittest.TestCase):
    def test_a_good_asset_is_not_capped_and_can_pass(self):
        r = critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=evidence())
        self.assertTrue(r["passed"], r)
        self.assertTrue(all(i["cap"] is None for i in r["items"]))

    def test_cad_caps_do_not_apply_to_a_game_asset(self):
        """A cage has no blend faces and no appearance() zones: the CAD caps would hold it at 1."""
        cad = {"sharp_edge_fraction": 0.95, "fillet_radii": [], "features": {"body": {}},
               "surface_mix": {"plane": 0.2, "free": 0.8}}
        self.assertFalse(critique.aesthetic_rubric(cad, [], ALL5)["passed"])
        g = critique.aesthetic_rubric(cad, [], ALL5, purpose="game", game=evidence())
        self.assertTrue(g["passed"])

    def test_the_control_fails_however_it_is_scored(self):
        blob = evidence(edges={"coverage": 1.0, "feature_edges_mm": 0.0, "hard_edges_mm": 0.0, "hard_baked_mm": 0.0,
                               "raw_share": 0.0},
                        materials={"count": 1}, value_contrast=0.01,
                        scales={"primary": False, "secondary": False, "tertiary": False, "count": 0},
                        silhouette={"complexity": 0.002}, wear={"present": False})
        r = critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=blob)
        self.assertFalse(r["passed"])
        caps = {i["id"]: i["cap"] for i in r["items"]}
        self.assertEqual(caps["material"], 1)
        self.assertEqual(caps["detail_rhythm"], 2)
        self.assertEqual(caps["silhouette"], 2)

    def test_raw_hard_edges_cap_the_edge_treatment(self):
        raw = evidence(edges={"coverage": 0.1, "raw_share": 0.9, "hard_edges_mm": 9000.0, "hard_baked_mm": 0.0})
        caps = {i["id"]: (i["cap"], i["why"]) for i in
                critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=raw)["items"]}
        self.assertEqual(caps["radius_hierarchy"][0], 1)
        self.assertIn("Bevel coverage", caps["radius_hierarchy"][1])
        self.assertEqual(caps["continuity"][0], 3)

    def test_no_asset_built_holds_the_game_items(self):
        r = critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=None)
        self.assertFalse(r["passed"])
        self.assertIn("game_asset", {i["id"]: i["why"] for i in r["items"]}["material"])

    def test_blind_passes_take_the_median(self):
        p = [dict(ALL5, silhouette=2), dict(ALL5, silhouette=4), dict(ALL5, silhouette=5)]
        r = critique.aesthetic_rubric({}, None, {"passes": p}, purpose="game", game=evidence())
        it = r["items"][0]
        self.assertEqual(it["score"], 4.0)
        self.assertEqual(it["passes"], [2.0, 4.0, 5.0])
        self.assertEqual(r["passes"], 3)

    def test_print_purpose_is_unchanged(self):
        m = {"surface_mix": {"plane": 0.95}, "fillet_faces": 0, "sharp_edge_fraction": 0.9, "features": {"body": {}}}
        a = critique.aesthetic_rubric(m, [], ALL5)
        b = critique.aesthetic_rubric(m, [], ALL5, purpose="print", game=evidence())
        self.assertEqual([i["cap"] for i in a["items"]], [i["cap"] for i in b["items"]])


class Measures(unittest.TestCase):
    def cube(self, s=100.0):
        V = np.array([[x, y, z] for x in (0, s) for y in (0, s) for z in (0, s)], float)
        Q = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
        T = np.array([t for q in Q for t in ([q[0], q[1], q[2]], [q[0], q[2], q[3]])])
        return V, T

    def test_a_raw_cube_has_no_bevel_coverage_and_a_flat_map_bakes_nothing(self):
        V, T = self.cube()
        P, UV = V[T].reshape(-1, 3), np.tile([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], (len(T), 1))
        TT = np.arange(len(P)).reshape(-1, 3)
        flat = np.zeros((64, 64, 3))
        flat[..., :] = [0.5, 0.5, 1.0]
        e = critique.edge_treatment(P, UV, TT, flat, 64)
        self.assertAlmostEqual(e["coverage"], 0.0, places=3)
        self.assertAlmostEqual(e["hard_edges_mm"], 1200.0, delta=1)

    def test_a_tilted_map_counts_as_baked(self):
        V, T = self.cube()
        P, UV = V[T].reshape(-1, 3), np.tile([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], (len(T), 1))
        TT = np.arange(len(P)).reshape(-1, 3)
        lean = np.zeros((64, 64, 3))
        lean[..., :] = [0.5 + 0.5 * math.sin(math.radians(30)), 0.5, 0.5 + 0.5 * math.cos(math.radians(30))]
        self.assertAlmostEqual(critique.edge_treatment(P, UV, TT, lean, 64)["coverage"], 1.0, places=3)

    def test_solidity(self):
        sq = np.zeros((40, 40), bool)
        sq[5:35, 5:35] = True
        self.assertGreater(critique.solidity(sq), 0.95)
        ring = sq.copy()
        ring[12:28, 12:28] = False
        self.assertLess(critique.solidity(ring), 0.8)

    def test_silhouettes_see_a_cube(self):
        V, T = self.cube()
        m = critique.silhouettes(V, T, 64)
        self.assertEqual(set(m), set(critique.GAME_VIEWS))
        self.assertGreater(critique.solidity(m["front"]), 0.95)

    def test_game_evidence_reads_an_asset_folder(self):
        V, T = self.cube(200.0)
        P, TT = V[T].reshape(-1, 3), np.arange(len(T) * 3).reshape(-1, 3)
        UV = np.tile([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], (len(T), 1))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "lods").mkdir()
            (d / "textures").mkdir()
            for k in (0, 1):
                np.savez(d / "lods" / f"lod{k}.npz", P=P, N=P * 0, UV=UV, T=TT)
            from PIL import Image
            Image.new("RGB", (32, 32), (128, 128, 255)).save(d / "textures" / "A_normal.png")
            Image.new("RGB", (32, 32), (120, 120, 120)).save(d / "textures" / "A_base_color.png")
            (d / "report.json").write_text(json.dumps({"asset": "A", "texture_px": 32, "materials": [
                {"name": "default", "kind": "plastic", "hex": "#777777", "wear": 0.0}]}), encoding="utf-8")
            ev = critique.game_evidence(d)
        self.assertEqual(ev["materials"]["count"], 1)
        self.assertLess(ev["value_contrast"], 0.02)
        self.assertEqual(ev["edges"]["coverage"], 0.0)
        self.assertFalse(ev["wear"]["present"])
        caps = critique._game_caps({}, ev)
        self.assertEqual(caps["radius_hierarchy"][0], 1)
        self.assertEqual(caps["material"][0], 1)


class WearAndReadAtAGlance(unittest.TestCase):
    """The measured worn share (the baked wear mask) and the 64 px silhouette read (form/refine/analyze.py)."""

    def caps(self, **kw):
        return {i["id"]: (i["cap"], i["why"]) for i in
                critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=evidence(**kw))["items"]}

    def test_worn_share_in_band_is_not_capped(self):
        c = self.caps(wear={"present": True, "worn_share": 0.05, "in_band": True})
        self.assertIsNone(c["material"][0])

    def test_too_little_or_too_much_wear_caps_the_material(self):
        c = self.caps(wear={"present": False, "worn_share": 0.004, "in_band": False})
        self.assertEqual(c["material"][0], 4)
        self.assertIn("0.4%", c["material"][1])
        c = self.caps(wear={"present": True, "worn_share": 0.3, "in_band": False})
        self.assertEqual(c["material"][0], 4)
        self.assertIn("damage", c["material"][1])

    def test_a_convex_64px_outline_is_capped_by_its_interior_read(self):
        c = self.caps(silhouette={"complexity": 0.028, "convexity_64": 0.049, "interior_regions": 11})
        self.assertEqual(c["silhouette"][0], 4)                  # the helmet: a blob outline, a rich interior
        c = self.caps(silhouette={"complexity": 0.028, "convexity_64": 0.047, "interior_regions": 5})
        self.assertEqual(c["silhouette"][0], 3)
        c = self.caps(silhouette={"complexity": 0.2, "convexity_64": 0.2, "interior_regions": 9})
        self.assertIsNone(c["silhouette"][0])
        c = self.caps(silhouette={"complexity": 0.6, "convexity_64": 0.6, "interior_regions": 9})
        self.assertEqual(c["silhouette"][0], 4)

    def test_the_control_blob_still_fails_with_the_64px_read(self):
        """The bench's control measured 0.0094 four-view complexity (over the old 0.005 floor, so it was never
        capped) and 0.027 convexity at 64 px with 4 value regions."""
        blob = evidence(edges={"coverage": 1.0, "feature_edges_mm": 0.0, "hard_edges_mm": 0.0, "hard_baked_mm": 0.0,
                               "raw_share": 0.0},
                        materials={"count": 1}, value_contrast=0.008,
                        scales={"primary": False, "secondary": False, "tertiary": False, "count": 0},
                        silhouette={"complexity": 0.0094, "convexity_64": 0.027, "interior_regions": 4},
                        wear={"present": False, "worn_share": 0.0, "in_band": False})
        r = critique.aesthetic_rubric({}, None, ALL5, purpose="game", game=blob)
        self.assertFalse(r["passed"])
        self.assertEqual({i["id"]: i["cap"] for i in r["items"]}["silhouette"], 2)

    def test_evidence_reads_the_baked_wear_measure_and_the_64px_read(self):
        V, T = Measures().cube(200.0)
        P, TT = V[T].reshape(-1, 3), np.arange(len(T) * 3).reshape(-1, 3)
        UV = np.tile([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], (len(T), 1))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "lods").mkdir()
            (d / "textures").mkdir()
            for k in (0, 1):
                np.savez(d / "lods" / f"lod{k}.npz", P=P, N=P * 0, UV=UV, T=TT)
            (d / "report.json").write_text(json.dumps({"asset": "A", "texture_px": 32, "materials": [
                {"name": "default", "kind": "wood", "hex": "#8a5a32", "wear": 0.6}],
                "bake": {"wear": {"worn_share": 0.061, "worn_on_convex": 0.4, "convex_of_worn": 0.8}}}),
                encoding="utf-8")
            ev = critique.game_evidence(d)
        self.assertEqual(ev["wear"]["worn_share"], 0.061)
        self.assertTrue(ev["wear"]["present"] and ev["wear"]["in_band"])
        self.assertIn("baked wear mask", ev["wear"]["measured"])
        self.assertLess(ev["silhouette"]["convexity_64"], 0.06)   # a cube is convex
        self.assertIn("interior_regions", ev["silhouette"])

    def test_the_wear_deficit_reads_the_worn_share(self):
        from form.refine import analyze
        self.assertEqual(analyze.wear({"wear": {"worn_share": 0.06, "edge_mask_share": 0.0}})["deficit"], 0.0)
        self.assertGreater(analyze.wear({"wear": {"worn_share": 0.002, "edge_mask_share": 0.3}})["deficit"], 0.8)


class MaterialOperators(unittest.TestCase):
    """form/refine/ops_material.py: zone assignment by region, the contrast pair and edge wear, as source edits."""

    CAD = ('from form.recipes.base import Feature, Recipe, Stage\n\n\nclass Design(Recipe):\n'
           '    features = [Feature("shell", "Shell", "structure"), Feature("grip", "Grip", "finish"),\n'
           '                Feature("clip", "Clip", "fit")]\n\n    def build(self, v):\n        return []\n')

    def analysis(self, **d):
        from form.refine import Analysis
        return Analysis(deficits=d, measures={"wear": {"share": d.pop("share", None)}} if "share" in d else {})

    def design(self, source, purpose="model", **kw):
        from form.refine import Design
        return Design(source=source, purpose=purpose, **kw)

    def test_the_operators_are_collected(self):
        from form.refine import operators
        self.assertEqual({o.name for o in operators("material")} >= {"material_zones", "contrast_pair", "edge_wear"},
                         True)

    def test_zones_by_region_for_a_cad_design(self):
        from form import appearance
        from form.adapters.blender import FINISHES
        from form.refine import ops_material as om
        p = om.MaterialZones().apply(self.design(self.CAD), self.analysis(material_zones=1.0), {})
        src = p.edit(self.CAD)
        zones = appearance.validate(om.appearance_in_source(src), {"shell", "grip", "clip"}, FINISHES)
        by = {f: z["label"] for z in zones for f in z["features"]}
        self.assertEqual(by, {"shell": "body", "grip": "accent", "clip": "function"})
        lums = [om.lum(z["color"]) for z in zones]
        self.assertGreaterEqual(max(lums) - min(lums), 0.15)
        self.assertEqual(p.edit(self.CAD), src)                  # deterministic
        self.assertFalse(om.MaterialZones().check(self.design(src), self.analysis(material_zones=0.0))[0])
        self.assertIsNone(om.MaterialZones().apply(self.design(src), self.analysis(material_zones=1.0), {}))

    def test_contrast_pair_reaches_the_minimum(self):
        from form.refine import ops_material as om
        src = om.write_appearance(self.CAD, [{"features": ["shell"], "finish": "matte", "color": "#777777"},
                                             {"features": ["grip"], "finish": "rubber", "color": "#707070"}])
        p = om.ContrastPair().apply(self.design(src), self.analysis(material_contrast=0.9), {"min_contrast": 0.15})
        zones = om.appearance_in_source(p.edit(src))
        lums = [om.lum(z["color"]) for z in zones]
        self.assertGreaterEqual(max(lums) - min(lums), 0.15)
        self.assertEqual([z["features"] for z in zones], [["shell"], ["grip"]])
        ok = om.push_apart({"a": "#ffffff", "b": "#000000"}, 0.15)
        self.assertEqual(ok, {"a": "#ffffff", "b": "#000000"})
        white = om.push_apart({"a": "#fafafa", "b": "#f0f0f0"}, 0.15)       # no room above: the dark one goes down
        self.assertGreaterEqual(om.lum(white["a"]) - om.lum(white["b"]), 0.15)

    def test_game_zones_and_wear_edit_materials(self):
        from form.game import materials as matlib
        from form.refine import ops_material as om
        a, c = base.box([0, 10], [0, 10], [0, 10]), base.box([20, 30], [0, 10], [0, 10])
        from form import meshsource
        V = np.concatenate([a.V, c.V])
        F = a.F + [[i + len(a.V) for i in f] for f in c.F]
        cage = meshsource.cage(V, F, [], {"strap": list(range(6, 12))})
        src = base.design_source(cage, "Two blocks", {"default": {"material": "wood", "wear": 0.2}})
        d = self.design(src, "game", style="stylised_fantasy")
        p = om.MaterialZones().apply(d, self.analysis(material_zones=1.0), {})
        mats, note = matlib.materials_in_source(p.edit(src))
        self.assertEqual(note, "")
        self.assertEqual(mats["strap"]["material"], "bare_metal")   # a strap is an accent: the style's iron
        p = om.EdgeWear().apply(d, self.analysis(wear=0.9, share=0.003), {"amount": 0.5})
        self.assertEqual(matlib.materials_in_source(p.edit(src))[0]["default"]["wear"], 0.5)
        p = om.EdgeWear().apply(d, self.analysis(wear=0.9, share=0.3), {"amount": 0.5})
        self.assertAlmostEqual(matlib.materials_in_source(p.edit(src))[0]["default"]["wear"], 0.14)
        self.assertFalse(om.EdgeWear().check(self.design(self.CAD), self.analysis(wear=1.0))[0])

    def test_a_module_level_materials_literal_is_rewritten_in_place(self):
        from form.game import materials as matlib
        from form.refine import ops_material as om
        src = 'MATERIALS = {"default": {"material": "stone"}}\n\n\nclass Design:\n    pass\n'
        out = om.write_materials(src, {"default": {"material": "stone", "wear": 0.4}})
        self.assertEqual(matlib.materials_in_source(out)[0], {"default": {"material": "stone", "wear": 0.4}})
        self.assertNotIn("def materials", out)


class RunnerWear(unittest.TestCase):
    def test_runner_version_and_wear_threshold(self):
        import ast as _ast
        from form.game import pipeline
        src = Path(pipeline.RUNNER).read_text(encoding="utf-8")
        tree = _ast.parse(src)
        ver = next(n.value.value for n in tree.body if isinstance(n, _ast.Assign)
                   and getattr(n.targets[0], "id", "") == "RUNNER_VERSION")
        self.assertEqual(ver, pipeline.RUNNER_VERSION)
        ns: dict = {}
        fn = next(n for n in tree.body if isinstance(n, _ast.FunctionDef) and n.name == "wear_threshold")
        consts = [n for n in tree.body if isinstance(n, _ast.Assign) and getattr(n.targets[0], "id", "") in
                  ("WEAR_RAMP",)]
        exec(compile(_ast.Module(body=consts + [fn], type_ignores=[]), "runner", "exec"), ns)
        th = [ns["wear_threshold"](w) for w in (0.0, 0.3, 0.5, 0.75, 1.0)]
        self.assertEqual(th, sorted(th, reverse=True))           # more wear, a lower threshold
        self.assertTrue('mk.inputs["Green"], worn)' in src)     # the mask the bake measures is the wear itself


class Exemplars(unittest.TestCase):
    def test_six_and_a_control_with_notes(self):
        self.assertEqual(len(gex.EXEMPLARS), 6)
        self.assertEqual(gex.names()[-1], gex.CONTROL)
        for n in gex.names():
            m = gex.module(n)
            self.assertTrue(m.TITLE and len(m.ORIGINALITY) > 40, n)
            self.assertTrue(hasattr(m, "ops") or hasattr(m, "SOURCE") or hasattr(m, "cage"), n)

    def test_op_lists_pass_the_checks_blender_would_get(self):
        for n in gex.EXEMPLARS:
            m = gex.module(n)
            if not hasattr(m, "ops"):
                continue
            ops = blender_model.validate_ops(m.ops())
            hi = [o.get("high_only", False) for o in ops]
            self.assertEqual(hi, sorted(hi), f"{n}: high_only ops must come last")
            for o in ops:                              # semi-sharp creases make the CAD limit surface explode
                for k in ("crease",):
                    if o["op"] != "crease" and k in o and not o.get("high_only"):
                        self.assertIn(o[k], (0.0, 1.0), f"{n}: {o['op']} crease {o[k]}")
            self.assertTrue(any(hi), f"{n}: no bake-only detail")

    def test_canonical_matches_the_runner_order(self):
        b = base.box([0, 1, 2], [0, 1], [0, 1])
        V, F, pm, fm = base.canonical(b.V, b.F)
        keys = [tuple(p) for p in V]
        self.assertEqual(keys, sorted(keys))
        rot = [tuple(f[f.index(min(f)):] + f[:f.index(min(f))]) for f in F]
        self.assertEqual(rot, sorted(rot))
        self.assertEqual(len(pm), len(b.V))
        self.assertEqual(sorted(fm.values()), list(range(len(F))))

    def test_blocks_are_closed_and_face_out(self):
        from form import meshsource
        for b in (base.box([0, 2], [0, 1, 3], [0, 1]), base.lathe([(5, -1), (7, -1), (7, 1), (5, 1)], 12, "y"),
                  base.quad_sphere(3, (2, 1, 1))):
            c = meshsource.cage(b.V, b.F)
            self.assertEqual(c.open_edges(), 0)
            vol = sum(np.dot(b.V[f[0]], np.cross(b.V[f[k]], b.V[f[k + 1]])) for f in b.F for k in range(1, len(f) - 1))
            self.assertGreater(vol, 0)

    def test_box_creases_only_its_twelve_border_lines(self):
        b = base.box([0, 1, 2, 3], [0, 1], [0, 1, 2])
        L = sum(np.linalg.norm(b.V[a] - b.V[c]) for a, c, _w in b.creases)
        self.assertAlmostEqual(L, 4 * (3 + 1 + 2))

    def test_design_source_keeps_high_detail_per_part(self):
        from form import meshsource
        from form.game import pipeline
        a, c = base.box([0, 10], [0, 10], [0, 10]), base.box([20, 30], [0, 10], [0, 10])
        rivet = base.box([4, 6], [-1, 0.5], [4, 6])
        V = np.concatenate([a.V, c.V + 0])
        F = a.F + [[i + len(a.V) for i in f] for f in c.F]
        hi = np.concatenate([V, rivet.V])
        HF = F + [[i + len(V) for i in f] for f in rivet.F]
        cage = meshsource.cage(V, F, [], {"b": list(range(6, 12))}, high={"V": hi.tolist(), "F": HF})
        src = base.design_source(cage, "Two blocks", {"default": {"material": "wood"}})
        back = pipeline.cages_in_source(src)
        self.assertEqual(len(back), 2)
        self.assertIsNotNone(back[0].high)             # the rivet went to the block it sits on
        self.assertEqual(len(back[0].high.F), 12)
        self.assertIsNone(back[1].high)                # the other block is unchanged: no copy in the source
        merged = pipeline.merge_cages(back)
        self.assertEqual(len(merged.high.F), 18)
        self.assertIn("def materials", src)


if __name__ == "__main__":
    unittest.main()
