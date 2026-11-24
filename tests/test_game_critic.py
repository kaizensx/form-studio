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
