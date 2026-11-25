"""The staged design workflow (brief -> plan -> design -> critique), mesh textures through the export pipeline,
design views, critique metrics and the release gate, on a real Studio and kernel."""
import json
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-craft-")

from form import config, design_guide, exemplars, staged  # noqa: E402
from form import critique as crit  # noqa: E402
from form.craft import meshtex  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402


class Assess(unittest.TestCase):
    def test_complexity(self):
        self.assertTrue(staged.assess("a helmet with texture")["complex"])
        self.assertTrue(staged.assess("planetary gearbox, 5:1")["complex"])
        self.assertFalse(staged.assess("a 40 mm spacer with a 5 mm hole")["complex"])
        a = staged.assess("a spacer", "class Design(Recipe):\n    solids = 2\n")
        self.assertTrue(a["complex"])
        self.assertEqual(a["evidence"], "heuristic")
        self.assertIn("mechanisms", staged.topics_for(["mechanism"]))

    def test_topics(self):
        self.assertIn("contract", design_guide.topic("core")["guide"].lower())
        for t in ("surfacing", "mechanisms", "organic", "texture", "aesthetics", "dfm"):
            self.assertGreater(len(design_guide.topic(t)["guide"]), 300, t)
        self.assertIn("Not applicable", design_guide.topic("dfm", "model")["guide"])
        with self.assertRaises(KeyError):
            design_guide.topic("poetry")


class Exemplars(unittest.TestCase):
    def test_catalogue(self):
        cat = exemplars.catalogue()
        self.assertGreaterEqual(len(cat), 12)
        for e in cat:
            self.assertTrue(e["title"] and e["tags"] and len(e["lessons"]) >= 3, e["name"])
        self.assertEqual(exemplars.search("motorcycle helmet with texture")[0]["name"], "helmet")
        self.assertEqual(exemplars.search("planetary gear reduction")[0]["name"], "planetary_gearbox")
        self.assertIn("class Design(Recipe)", exemplars.get("knurled_knob")["source"])
        with self.assertRaises(KeyError):
            exemplars.get("../studio")

    def test_crude_exemplars_are_kept_but_never_retrieved(self):
        """character_mask, prop_mask and scifi_helmet read as eggs: kept and built, never offered to learn from."""
        crude = {"character_mask", "prop_mask", "scifi_helmet"}
        names = {e["name"] for e in exemplars.catalogue()}
        self.assertLessEqual(crude, names)                                       # still in the repo
        self.assertEqual(crude & {e["name"] for e in exemplars.retrievable()}, set())
        for q in ("a mask for cosplay", "half face mask", "sci-fi helmet", "character mask with magnet eyes",
                  "sculpted prop mask", "helmet"):
            self.assertEqual(crude & {h["name"] for h in exemplars.search(q, 10)}, set(), q)
        self.assertEqual(crude & {s["exemplar"] for s in exemplars.snippets("mask magnet eyes sculpted shell", 20)}, set())
        got = exemplars.get("prop_mask")                                         # by name: with the reason
        self.assertFalse(got["retrieval"])
        self.assertTrue(got["how_to_use"].startswith("Not for learning from"))
        form_dir = Path(exemplars.__file__).parents[1]
        guide = (form_dir / "design_guide.py").read_text(encoding="utf-8") + "".join(
            f.read_text(encoding="utf-8") for f in sorted((form_dir / "guidance").rglob("*.md")))
        for n in crude:
            self.assertNotIn(n, guide, "the guide does not point the agent at it")

    def test_not_in_the_library(self):
        from form.recipes import RecipeBook
        ids = " ".join(RecipeBook(None).builtins())
        self.assertNotIn("helmet", ids)


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_brief_plan_and_gate(self):
        st = self.st
        b = staged.save_brief(st, "Knob", "A knurled knob for a 6 mm D-shaft", ["grip with gloves"],
                              {"shaft_d": {"value": 6, "unit": "mm", "source": "measured"}}, unknowns=["panel thickness"])
        self.assertTrue(b["assessment"]["complex"])
        with self.assertRaises(StudioError):
            staged.save_plan(st, b["id"], [{"id": "grip", "label": "Grip", "how": "craft.knurl"}])      # too thin
        with self.assertRaises(StudioError):
            staged.require_plan(st, "a knurled knob", "", "")
        with self.assertRaises(StudioError):
            staged.require_plan(st, "a knurled knob", "", b["id"])                                      # no plan yet
        feats = [{"id": f, "label": f, "how": h} for f, h in (("skirt", "revolve"), ("grip", "craft.knurl diamond"),
                 ("cap", "cylinder + dish"), ("bore", "D bore"), ("missing_thing", "never built"))]
        staged.save_plan(st, b["id"], feats, risks=["knurl too fine to print"])
        self.assertTrue(staged.require_plan(st, "a knurled knob", "", b["id"])["complex"])
        src = exemplars.get("knurled_knob")["source"]
        p = st.create_design("Knob", src, "a knurled knob")
        staged.attach_pending(st, p["id"], b["id"])
        p = st.load(p["id"])
        self.assertEqual(p["design"]["brief"]["goal"], "A knurled knob for a 6 mm D-shaft")
        self.assertIn("No design critique", " ".join(st.gate(p)["reasons"]))
        r = crit.run(st, p["id"], "Looked at the cap and grip; fine.")
        m = r["metrics"]
        self.assertEqual(m["planned_missing"], ["missing_thing"])
        self.assertIsNotNone(m["smallest_fillet_mm"])
        self.assertGreater(m["symmetry"]["mirror_y"], 0.8)
        self.assertTrue(Path(r["closeups"]).is_file())
        self.assertTrue(any(i["attention"] for i in r["checklist"]))
        p = st.load(p["id"])
        self.assertNotIn("No design critique", " ".join(st.gate(p)["reasons"]))
        v = crit.design_views(st, p["id"])
        self.assertTrue(Path(v["sheet"]).is_file())
        self.assertTrue(Path(v["section"]).is_file(), v.get("section_error"))

    def test_unbriefed_design_is_not_gated_by_critique(self):
        p = self.st.create_design("Box", design_guide.EXAMPLE)
        self.assertIsNone(staged.needs_critique(self.st.load(p["id"])))

    def test_mesh_texture_reaches_stl_and_glb_not_step(self):
        st = self.st
        p = st.create_design("Handle", exemplars.get("ergonomic_handle")["source"], purpose="model")
        j = st.run_sync(p["id"], ["geometry", "exports"])
        self.assertEqual(j["state"], "done", j)
        p = st.load(p["id"])
        k = st.keys(p)
        ex = st.read(p, "exports", k["exports"])
        self.assertEqual(ex["mesh_texture"]["label"], meshtex.LABEL)
        d = st.apath(p, "exports", k["exports"])
        stl = d / ex["files"]["stl"]["name"]
        n_tri = int.from_bytes(stl.read_bytes()[80:84], "little")
        self.assertGreater(n_tri, 100_000)                                       # the grain is in the mesh
        self.assertIn("glb", ex["files"])
        self.assertIn("STEP carries", stl.read_bytes()[:80].decode("ascii", "replace"))
        step = (d / ex["files"]["step"]["name"]).read_text(errors="replace")
        self.assertIn("B_SPLINE_SURFACE", step)                                  # the smooth CAD body
        smooth = st.create_design("Handle smooth", exemplars.get("ergonomic_handle")["source"], values={"grain": 0},
                                  purpose="model")
        st.run_sync(smooth["id"], ["geometry", "exports"])
        s = st.load(smooth["id"])
        ex2 = st.read(s, "exports", st.keys(s)["exports"])
        self.assertNotIn("mesh_texture", ex2)
        view = st.view(p)
        self.assertEqual(view["mesh_texture"]["label"], meshtex.LABEL)

    def test_assembly_exemplar_is_accepted(self):
        p = self.st.create_design("Case", exemplars.get("hinged_case")["source"])
        self.assertEqual(self.st.recipe(self.st.load(p["id"])).solids, 2)


if __name__ == "__main__":
    unittest.main()
