"""Every multi-part design gets assembled and exploded views: the enclosure and the gear pair declare how they go
together; a design that builds several bodies and declares nothing gets a view-only assembly from its solids.

Real kernel, temp data folder (the enclosure and gear pair need the [parts] extra)."""
import importlib.util
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-asmv-")

from form import assembly as asm, config  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.recipes.assembly import from_solids  # noqa: E402
from form.studio import Studio  # noqa: E402
from printing_cfg import with_printing  # noqa: E402
from test_assembly import model  # noqa: E402

PARTS = importlib.util.find_spec("py_gearworks") is not None and importlib.util.find_spec("bd_warehouse") is not None
NO_ASSEMBLY = EXAMPLE.split("    def assembly(self, v):")[0]          # the example box, without its declaration

from fixtures.lying_design import LYING  # noqa: E402  (a part built lying down)


class Derived(unittest.TestCase):
    def test_from_solids_pulls_parts_away_from_the_middle_never_down(self):
        a = from_solids([[[0, 0, 0], [20, 20, 20]], [[40, 0, 0], [50, 10, 10]]])
        self.assertTrue(a.derived)
        self.assertEqual([p.solid for p in a.parts], [0, 1])
        self.assertLess(a.parts[0].explode[0], 0)                     # left part goes left
        self.assertGreater(a.parts[1].explode[0], 0)                  # right part goes right
        self.assertTrue(all(p.explode[2] >= 0 for p in a.parts))      # nothing goes through the plate
        self.assertEqual(a.parts[1].move, (0.0, 0.0, 0.0))            # "assembled" is the design as modelled
        stacked = from_solids([[[0, 0, 0], [20, 20, 10]], [[0, 0, 10], [20, 20, 14]]])
        self.assertGreater(stacked.parts[1].explode[2], 0)            # the upper part lifts
        self.assertEqual(a.public()["derived"], True)

    def test_explode_about_the_anchor(self):
        from form import poses
        parts = [{"id": "lid", "parent": "box", "bbox": [[0, 0, 30], [80, 60, 34]], "explode_total": [0, 0, 20]},
                 {"id": "box", "parent": "", "bbox": [[0, 0, 0], [80, 60, 30]], "explode_total": [0, 0, -5]},
                 {"id": "tray", "parent": "", "bbox": [[0, 0, 2], [70, 50, 6]], "explode_total": [0, 0, -40]},
                 {"id": "knob", "parent": "", "bbox": [[0, 0, 0], [10, 10, 10]], "explode_total": [-30, 0, 0]}]
        self.assertEqual(poses.anchor_of(parts), "box")              # fixed to the world, the largest footprint
        off = poses.explode_offsets(parts)
        self.assertEqual(off["box"], [0.0, 0.0, 0.0])                # the anchor stays exactly
        self.assertEqual(off["lid"], [0.0, 0.0, 25.0])               # relative to the anchor
        self.assertEqual(off["tray"], [0.0, 0.0, 35.0])              # -35 would go 33 mm into the ground: turned up
        self.assertEqual(off["knob"], [-30.0, 0.0, 5.0])             # sideways, and the anchor's -5 taken out
        for x in parts:
            self.assertGreaterEqual(x["bbox"][0][2] + off[x["id"]][2], 0)
        self.assertEqual(poses.anchor_of([dict(p, parent="") for p in parts[:2]]), "box")   # equal footprints: the lowest

    def test_get_derives_when_undeclared_and_checks_nothing(self):
        m = model(None)
        a = asm.get(m)
        self.assertIsNotNone(a)
        self.assertTrue(a["spec"].derived)
        self.assertEqual(len(a["spec"].parts), 2)
        self.assertEqual(asm.analyse(model(None)), [])


class Studio_(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(with_printing(config.load()))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def checks(self, p):
        return {c["id"]: c for c in self.st.read(p, "checks", self.st.keys(p)["checks"])["checks"]}

    def test_undeclared_multi_body_design_gets_views(self):
        p = self.st.create_design("Bodies", NO_ASSEMBLY)
        v = self.st.view(self.st.load(p["id"]))
        a = v["assembly"]
        self.assertTrue(a["derived"])
        self.assertEqual([x["id"] for x in a["parts"]], ["part1", "part2"])
        self.assertTrue(all(m["part"] in ("part1", "part2") for m in v["mesh"]))
        self.assertEqual(self.st.state(p["id"])["documents"], ["BOM.csv", "PRINT_REPORT.md", "MEASUREMENT_PLAN.md"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        self.assertFalse(any(k.startswith("asm_") for k in self.checks(self.st.load(p["id"]))))

    def test_a_part_built_lying_down_never_hangs_under_the_plate(self):
        import base64

        import numpy as np

        from form import render
        from form import poses
        p = self.st.create_design("Lying post", LYING)
        v = self.st.view(self.st.load(p["id"]))
        a = v["assembly"]
        self.assertEqual(a["anchor"], "base")                     # fixed to the world, the largest footprint
        post = next(x for x in a["parts"] if x["id"] == "post")
        self.assertEqual(np.ptp(np.array(post["print_bbox"])[:, 2]), 12.0)   # built lying down: 12 mm tall as printed
        self.assertAlmostEqual(post["bbox"][0][2], 6.0, places=3)             # stood on the base's top by its placement
        self.assertLess(post["bbox"][0][2] + post["explode_total"][2], -30)    # its offset as declared: through the ground

        def drawn(out, part):
            return np.concatenate([np.frombuffer(base64.b64decode(m["positions"]), np.float32).reshape(-1, 3)
                                   for m in out["mesh"] if m.get("part") == part])
        shown = {pose: render.posed(v, pose) for pose in ("assembled", "exploded")}
        for pose, out in shown.items():
            P = np.concatenate([drawn(out, x["id"]) for x in a["parts"]])
            self.assertGreaterEqual(float(P[:, 2].min()), -1e-3, pose)          # nothing below the plate
            self.assertGreater(float(np.ptp(drawn(out, "post")[:, 2])), 50, pose)   # the post stands upright
        base0, base1 = drawn(shown["assembled"], "base"), drawn(shown["exploded"], "base")
        self.assertTrue(np.allclose(base0, base1, atol=1e-4))                   # the anchor does not move at all
        self.assertAlmostEqual(float(base0[:, 2].min()), 0.0, places=3)          # and rests on the plate
        d = drawn(shown["exploded"], "post").min(axis=0) - drawn(shown["assembled"], "post").min(axis=0)
        self.assertTrue(np.allclose(d, [25, 0, 30], atol=1e-3), d)               # out, and up instead of down
        self.assertEqual(poses.explode_offsets(a["parts"])["post"], [25.0, 0.0, 30.0])
        png = render.render_png(shown["exploded"], [], "iso", None, size=(320, 240))
        self.assertTrue(png.startswith(b"\x89PNG"))

    @unittest.skipUnless(PARTS, "needs the [parts] extra")
    def test_enclosure_lid_seats_on_the_box(self):
        p = self.st.create("Enclosure", "enclosure")
        v = self.st.view(p)
        self.assertEqual([x["id"] for x in v["assembly"]["parts"]], ["box", "lid"])
        self.assertFalse(v["assembly"]["derived"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        c = self.checks(self.st.load(p["id"]))
        self.assertEqual(c["asm_interference"]["status"], "PASS")
        self.assertEqual(c["asm_clearance"]["value"], "contact only")     # the lid rests on the walls
        self.assertIn("ASSEMBLY.md", self.st.state(p["id"])["documents"])

    @unittest.skipUnless(PARTS, "needs the [parts] extra")
    def test_gear_pair_gears_sit_on_their_axles_in_mesh(self):
        p = self.st.create("Gears", "gear_pair")
        v = self.st.view(p)
        self.assertEqual([x["id"] for x in v["assembly"]["parts"]], ["plate", "gear_a", "gear_b"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        c = self.checks(self.st.load(p["id"]))
        self.assertEqual(c["asm_interference"]["status"], "PASS")
        self.assertLess(float(c["asm_clearance"]["value"].split()[0]), 0.5)    # teeth in mesh: a small backlash gap


if __name__ == "__main__":
    unittest.main()
